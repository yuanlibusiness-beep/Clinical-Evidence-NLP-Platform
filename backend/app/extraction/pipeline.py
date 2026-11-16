"""The extraction pipeline: retrieve -> generate -> ground -> calibrate -> abstain.

    for each field:
        targeted query -> hybrid retrieval -> top-3 evidence
    union of those -> one evidence window (<= MAX_EVIDENCE_CHUNKS)
        |
    engine (LLM under schema constraint, or rule engine)
        |
    grounding: every quote matched back to the source text
        |  ungrounded -> dropped, reason="ungrounded"
    calibration: blend self-report + grounding + retrieval + section prior
        |  below ABSTAIN_THRESHOLD -> dropped, reason="low_confidence"
        v
    persisted EvidenceReview + one EvidenceSpan per surviving claim

Why per-field retrieval rather than one query for the whole paper: "sample size"
and "limitations" live in different sections and share almost no vocabulary.  A
single pooled query retrieves chunks that are mediocre for both.  Eighteen
cheap queries against an in-memory BM25 index plus a local vector search cost
milliseconds, and the union window they produce is markedly better targeted.

Everything a field can be dropped for is recorded in ``abstentions`` with a
reason, so "the platform returned nothing for sample size" is always answerable:
not retrieved, not generated, not grounded, or not confident enough.
"""

from __future__ import annotations

import logging
import time

from sqlalchemy.orm import Session

from app.config import settings
from app.extraction import rules
from app.extraction.calibration import Calibrator
from app.extraction.engines import (
    EngineResult,
    ExtractionContext,
    ExtractionEngine,
    build_engine,
)
from app.extraction.grounding import (
    GroundedSpan,
    NormalisedIndex,
    ground_quote,
    locate_chunk,
)
from app.extraction.schema import (
    FIELD_TOPICS,
    EvidenceReview,
    ExtractedField,
    get_by_path,
    iter_grounded_items,
)
from app.ingest.sectioniser import section_priority
from app.llm.factory import get_llm
from app.models import Document, EvidenceSpan, Extraction, Section
from app.retrieval.hybrid import HybridRetriever
from app.schemas import RetrievedChunk

logger = logging.getLogger(__name__)


#: Targeted retrieval query per field.  Written as clinical-paper *phrasing*
#: rather than as questions, because BM25 matches surface form: papers say
#: "patients were randomly assigned", not "was this study randomised?".
FIELD_QUERIES: dict[str, str] = {
    "pico.population": "patients participants with condition eligible enrolled population studied",
    "pico.intervention": "randomly assigned to receive intervention treatment group dose administered",
    "pico.comparison": "placebo control group comparator usual care versus compared with",
    "pico.outcome": "primary outcome endpoint measured assessed at follow-up",
    "design.design": "randomised controlled trial cohort study design multicentre prospective",
    "design.randomised": "randomly assigned allocation randomisation sequence concealment",
    "design.blinding": "double-blind single-blind open-label masking blinded assessors",
    "design.setting": "conducted at hospitals centres sites clinics country multicentre",
    "design.duration": "follow-up period duration weeks months years study period",
    "design.registration_id": "registered ClinicalTrials.gov NCT ISRCTN trial registration number",
    "population.sample_size": "total of patients were randomised enrolled n = participants analysed",
    "population.age": "mean age median age years old range aged",
    "population.sex_distribution": "female male women men percent sex distribution",
    "population.inclusion_criteria": "inclusion criteria eligible if patients aged with diagnosis",
    "population.exclusion_criteria": "exclusion criteria excluded patients with history of",
    "limitations": "limitations of this study caution generalisability small sample",
    "conclusion": "in conclusion these findings suggest we conclude implications",
    "funding": "funded supported by grant sponsor conflict of interest",
}

#: Extra pooled queries used to surface reportable results for `outcomes`.
OUTCOME_QUERIES = [
    "primary outcome occurred hazard ratio 95% CI p value",
    "significantly reduced risk difference between groups percent versus percent",
    "adverse events serious adverse events safety outcomes incidence",
]


class ExtractionPipeline:
    def __init__(
        self,
        db: Session,
        *,
        engine: ExtractionEngine | None = None,
        calibrator: Calibrator | None = None,
    ) -> None:
        self.db = db
        self.engine = engine or build_engine(get_llm())
        self.calibrator = calibrator or Calibrator()

    # ------------------------------------------------------------------ run
    def run(self, document: Document, *, user_id: str) -> Extraction:
        started = time.perf_counter()
        extraction = Extraction(
            document_id=document.id,
            user_id=user_id,
            provider=self.engine.provider,
            model=self.engine.model,
            status="running",
        )
        self.db.add(extraction)
        self.db.flush()

        try:
            context, retrieval_scores = self._build_context(document)
            result = self.engine.run(context)
            payload, confidence, abstentions, spans = self._post_process(
                document, result, context, retrieval_scores
            )

            extraction.payload = payload
            extraction.confidence = confidence
            extraction.abstentions = abstentions
            extraction.provider = result.provider
            extraction.model = result.model
            extraction.prompt_tokens = result.prompt_tokens
            extraction.completion_tokens = result.completion_tokens
            answered = len(confidence)
            extraction.grounded_field_ratio = (
                round(len(spans) / answered, 4) if answered else 0.0
            )
            extraction.status = "completed"

            for span in spans:
                self.db.add(span)
                span.extraction_id = extraction.id

        except Exception as exc:
            extraction.status = "failed"
            extraction.error = str(exc)[:1000]
            logger.exception("Extraction failed for document %s", document.id)

        extraction.latency_ms = int((time.perf_counter() - started) * 1000)
        self.db.flush()
        return extraction

    # -------------------------------------------------------------- context
    def _build_context(
        self, document: Document
    ) -> tuple[ExtractionContext, dict[str, float]]:
        retriever = HybridRetriever(self.db, document.id)

        per_field: dict[str, list[RetrievedChunk]] = {}
        union: dict[str, RetrievedChunk] = {}
        best_retrieval: dict[str, float] = {}

        def absorb(chunks: list[RetrievedChunk]) -> None:
            for chunk in chunks:
                existing = union.get(chunk.chunk_id)
                if existing is None or (chunk.rerank_score or 0) > (
                    existing.rerank_score or 0
                ):
                    union[chunk.chunk_id] = chunk

        for path, query in FIELD_QUERIES.items():
            topic = FIELD_TOPICS.get(path, "")
            hits = retriever.retrieve(
                query, top_k=settings.per_field_evidence_chunks, field=topic
            )
            per_field[path] = hits
            if hits:
                best_retrieval[path] = _normalised_retrieval_score(hits[0])
            absorb(hits)

        for query in OUTCOME_QUERIES:
            absorb(retriever.retrieve(query, top_k=3, field="effect"))

        # Keep the window in document order: a model reading Methods before
        # Results is reading the paper the way a person would.
        evidence = sorted(union.values(), key=lambda c: c.order_index)
        if len(evidence) > settings.max_evidence_chunks:
            # Drop the weakest by rerank score, then restore document order.
            ranked = sorted(
                evidence,
                key=lambda c: (c.rerank_score if c.rerank_score is not None else c.fused_score),
                reverse=True,
            )[: settings.max_evidence_chunks]
            evidence = sorted(ranked, key=lambda c: c.order_index)

        sections = (
            self.db.query(Section)
            .filter(Section.document_id == document.id)
            .order_by(Section.order_index)
            .all()
        )
        sentence_source = (
            [(section.name, section.text) for section in sections]
            if sections
            else [("body", document.raw_text)]
        )

        context = ExtractionContext(
            title=document.title,
            journal=document.journal,
            year=document.year,
            evidence=evidence,
            per_field=per_field,
            sentences=rules.sentences_from(sentence_source),
        )
        return context, best_retrieval

    # --------------------------------------------------------- post-process
    def _post_process(
        self,
        document: Document,
        result: EngineResult,
        context: ExtractionContext,
        retrieval_scores: dict[str, float],
    ) -> tuple[dict, dict[str, float], dict[str, str], list[EvidenceSpan]]:
        index = NormalisedIndex(document.raw_text)
        review = result.review

        confidence: dict[str, float] = {}
        abstentions: dict[str, str] = {}
        spans: list[EvidenceSpan] = []

        for path, value, quote, self_reported in iter_grounded_items(review):
            if not value:
                # A model reading the evidence can judge that the paper is
                # silent; a regex that failed to fire cannot.  Saying "the paper
                # does not report this" on a rule miss is a false statement
                # about the paper, so the rule engine gets the weaker reason.
                abstentions[path] = (
                    "not_found" if result.provider == "offline" else "not_reported"
                )
                continue

            if not quote:
                self._clear(review, path)
                abstentions[path] = "no_quote"
                continue

            candidates = context.per_field.get(path) or context.evidence
            grounded: GroundedSpan | None = ground_quote(
                quote, index, candidates=context.evidence or candidates
            )
            if grounded is None:
                self._clear(review, path)
                abstentions[path] = "ungrounded"
                continue

            owning_chunk = locate_chunk(grounded.char_start, context.evidence)
            section_name = owning_chunk.section_name if owning_chunk else "body"
            topic = FIELD_TOPICS.get(path, "")

            rule_agreement = 1.0 if path in result.rule_sources else 0.0
            calibrated = self.calibrator.score(
                self_reported=self_reported,
                grounding=grounded.match_score,
                retrieval=retrieval_scores.get(path, 0.5),
                section_prior=section_priority(section_name, topic),
                rule_agreement=rule_agreement,
            )

            if calibrated < settings.abstain_threshold:
                self._clear(review, path)
                abstentions[path] = f"low_confidence({calibrated:.2f})"
                continue

            confidence[path] = calibrated
            self._write_back_quote(review, path, grounded.quote)
            spans.append(
                EvidenceSpan(
                    chunk_id=owning_chunk.chunk_id if owning_chunk else None,
                    field_path=path,
                    quote=grounded.quote,
                    section_name=section_name,
                    char_start=grounded.char_start,
                    char_end=grounded.char_end,
                    page_no=owning_chunk.page_no if owning_chunk else None,
                    match_score=grounded.match_score,
                )
            )

        payload = review.model_dump()
        payload["_meta"] = {
            "prompt_version": result.prompt_version,
            "engine": result.provider,
            "model": result.model,
            "rule_sources": result.rule_sources,
            "notes": result.notes,
            "evidence_chunks": [chunk.chunk_id for chunk in context.evidence],
            "calibrated": self.calibrator.is_fitted,
        }
        return payload, confidence, abstentions, spans

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _clear(review: EvidenceReview, path: str) -> None:
        """Remove a rejected claim so it can never surface in the UI."""
        if path.startswith("outcomes["):
            index = int(path[len("outcomes[") : -1])
            if 0 <= index < len(review.outcomes):
                review.outcomes[index].quote = None
                review.outcomes[index].confidence = 0.0
                review.outcomes[index].name = f"[withheld] {review.outcomes[index].name}"
            return
        item = get_by_path(review, path)
        if isinstance(item, ExtractedField):
            item.value = None
            item.quote = None
            item.confidence = 0.0

    @staticmethod
    def _write_back_quote(review: EvidenceReview, path: str, quote: str) -> None:
        """Replace the model's wording with the source text it matched."""
        if path.startswith("outcomes["):
            index = int(path[len("outcomes[") : -1])
            if 0 <= index < len(review.outcomes):
                review.outcomes[index].quote = quote
            return
        item = get_by_path(review, path)
        if isinstance(item, ExtractedField):
            item.quote = quote


def _normalised_retrieval_score(chunk: RetrievedChunk) -> float:
    """Squash a rerank/fusion score into [0, 1] for the calibrator."""
    if chunk.rerank_score is not None:
        return min(1.0, max(0.0, chunk.rerank_score))
    # RRF scores are tiny (~1/60); scale so a top-ranked chunk lands near 0.8.
    return min(1.0, chunk.fused_score * 30.0)


def run_extraction(db: Session, document: Document, *, user_id: str) -> Extraction:
    """Convenience entry point used by the API routes and the Celery task."""
    return ExtractionPipeline(db).run(document, user_id=user_id)
