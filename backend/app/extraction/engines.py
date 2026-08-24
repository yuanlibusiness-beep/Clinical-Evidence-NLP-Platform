"""Extraction engines: two ways to fill the same schema.

``RuleEngine``  -- deterministic patterns (``extraction/rules.py``).  Zero cost,
zero latency, no network.  High precision on the fields that have a
canonical surface form (registration IDs, sample sizes, p-values), and
correspondingly poor on the ones that need reading comprehension
(population, limitations, conclusion).

``LlmEngine``   -- schema-constrained generation against an OpenAI-compatible
endpoint, with the offline rules used as a **backfill** for the high-precision
fields when the model abstains.

Both return an ``EngineResult`` carrying a validated ``EvidenceReview``.  The
pipeline that grounds, calibrates and persists it does not know or care which
one produced it -- which is exactly what makes the two comparable on the same
gold set in ``evaluation/runner.py``.
"""

from __future__ import annotations

import abc
import logging
import time
from dataclasses import dataclass, field

from pydantic import ValidationError

from app.extraction import rules
from app.extraction.prompts import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    build_user_prompt,
)
from app.extraction.schema import (
    EvidenceReview,
    ExtractedField,
    Outcome,
    get_by_path,
)
from app.llm.base import LLMError, LLMProvider, parse_json_object
from app.schemas import RetrievedChunk

logger = logging.getLogger(__name__)


@dataclass
class ExtractionContext:
    title: str
    journal: str | None = None
    year: int | None = None
    #: The union evidence window shown to the model.
    evidence: list[RetrievedChunk] = field(default_factory=list)
    #: Per-field retrieval, used for calibration and for the rule engine.
    per_field: dict[str, list[RetrievedChunk]] = field(default_factory=dict)
    #: Section-labelled sentences over the whole document, for the rules.
    sentences: list[rules.Sentence] = field(default_factory=list)


@dataclass
class EngineResult:
    review: EvidenceReview
    provider: str
    model: str
    prompt_version: str = PROMPT_VERSION
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    #: field_path -> the rule that produced it, when a rule did.
    rule_sources: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


class ExtractionEngine(abc.ABC):
    provider: str
    model: str

    @abc.abstractmethod
    def run(self, context: ExtractionContext) -> EngineResult:
        ...


def _set_by_path(review: EvidenceReview, path: str, value: ExtractedField) -> None:
    parts = path.split(".")
    target = review
    for part in parts[:-1]:
        target = getattr(target, part)
    setattr(target, parts[-1], value)


# --------------------------------------------------------------------- rules
class RuleEngine(ExtractionEngine):
    provider = "offline"
    model = "rule-based-v1"

    def run(self, context: ExtractionContext) -> EngineResult:
        started = time.perf_counter()
        review = EvidenceReview()
        rule_sources: dict[str, str] = {}

        sentences = context.sentences
        for path, extractor in rules.FIELD_EXTRACTORS.items():
            try:
                hit = extractor(sentences)
            except Exception as exc:  # a bad regex must not kill the review
                logger.warning("Rule %s failed: %s", path, exc)
                continue
            if hit is None:
                continue
            _set_by_path(
                review,
                path,
                ExtractedField(
                    value=hit.value, quote=hit.quote, confidence=hit.confidence
                ),
            )
            rule_sources[path] = hit.rule

        for index, raw in enumerate(rules.extract_outcomes(sentences)):
            try:
                review.outcomes.append(Outcome(**raw))
                rule_sources[f"outcomes[{index}]"] = "statistics"
            except ValidationError as exc:
                logger.debug("Dropped malformed rule outcome: %s", exc)

        return EngineResult(
            review=review,
            provider=self.provider,
            model=self.model,
            latency_ms=int((time.perf_counter() - started) * 1000),
            rule_sources=rule_sources,
        )


# ----------------------------------------------------------------------- llm
class LlmEngine(ExtractionEngine):
    def __init__(self, provider: LLMProvider, *, backfill: bool = True) -> None:
        self._llm = provider
        self.provider = provider.name
        self.model = provider.model
        self.backfill = backfill
        self._rules = RuleEngine()

    def run(self, context: ExtractionContext) -> EngineResult:
        started = time.perf_counter()

        field_hints = self._build_hints(context)
        user_prompt = build_user_prompt(
            title=context.title,
            journal=context.journal,
            year=context.year,
            evidence=context.evidence,
            field_hints=field_hints,
        )

        result = self._llm.complete(
            system=SYSTEM_PROMPT, user=user_prompt, json_mode=True
        )

        try:
            payload = parse_json_object(result.text)
        except LLMError:
            # One repair attempt: hand the model its own broken output back.
            logger.warning("Malformed JSON from %s; attempting repair.", self.model)
            repair = self._llm.complete(
                system="You fix malformed JSON. Return only valid JSON, nothing else.",
                user=f"Fix this into a single valid JSON object:\n\n{result.text[:6000]}",
                json_mode=True,
            )
            payload = parse_json_object(repair.text)
            result.completion_tokens += repair.completion_tokens
            result.prompt_tokens += repair.prompt_tokens

        try:
            review = EvidenceReview.model_validate(payload)
        except ValidationError as exc:
            # Validation is per-field-tolerant by design (every field defaults),
            # so reaching here means the top-level shape is wrong.
            raise LLMError(f"Model output failed schema validation: {exc}") from exc

        notes: list[str] = []
        rule_sources: dict[str, str] = {}

        if self.backfill:
            filled = self._backfill(review, context)
            rule_sources.update(filled)
            if filled:
                notes.append(
                    f"Rule engine backfilled {len(filled)} field(s) the model left empty: "
                    + ", ".join(sorted(filled))
                )

        return EngineResult(
            review=review,
            provider=self.provider,
            model=result.model,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            latency_ms=int((time.perf_counter() - started) * 1000),
            rule_sources=rule_sources,
            notes=notes,
        )

    # ------------------------------------------------------------- helpers
    def _backfill(
        self, review: EvidenceReview, context: ExtractionContext
    ) -> dict[str, str]:
        """Fill high-precision fields the model declined to answer."""
        filled: dict[str, str] = {}
        for path in rules.HIGH_PRECISION_FIELDS:
            current = get_by_path(review, path)
            if isinstance(current, ExtractedField) and current.is_answered:
                continue
            extractor = rules.FIELD_EXTRACTORS.get(path)
            if extractor is None:
                continue
            hit = extractor(context.sentences)
            if hit is None:
                continue
            _set_by_path(
                review,
                path,
                ExtractedField(
                    value=hit.value,
                    quote=hit.quote,
                    # A rule that had to rescue a field is worth less than one
                    # that agrees with the model, so shade the confidence down.
                    confidence=min(0.8, hit.confidence),
                ),
            )
            filled[path] = hit.rule
        return filled

    @staticmethod
    def _build_hints(context: ExtractionContext) -> dict[str, list[int]]:
        """Map per-field retrieval back onto excerpt numbers for the prompt."""
        position = {chunk.chunk_id: index for index, chunk in enumerate(context.evidence, 1)}
        hints: dict[str, list[int]] = {}
        for path, chunks in context.per_field.items():
            ids = [position[c.chunk_id] for c in chunks[:3] if c.chunk_id in position]
            if ids:
                hints[path] = ids
        return hints


def build_engine(provider: LLMProvider | None) -> ExtractionEngine:
    return LlmEngine(provider) if provider is not None else RuleEngine()
