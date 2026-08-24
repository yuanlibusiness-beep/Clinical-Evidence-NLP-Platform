"""Reranking: cheap recall first, expensive precision second.

Fusion optimises recall over ~60 candidates.  The extractor can only afford to
read about 8.  Reranking is the step that decides which 8, and it is allowed to
be much more expensive per candidate because it sees so few.

Two implementations behind one interface:

``FeatureReranker`` (default, offline, deterministic)
    A small interpretable scoring function.  Not a neural cross-encoder, and not
    presented as one -- but it encodes the signals that actually separate a
    useful evidence chunk from a plausible-looking one in a clinical paper:
    query-term coverage, longest contiguous phrase overlap, whether the chunk
    carries the *kind* of content the query asks for (a query about effect size
    wants numbers, confidence intervals and p-values), and the IMRaD section
    prior.  Every component is inspectable in ``explain``, which matters when
    you have to defend a retrieval decision.

``CrossEncoderReranker`` (optional)
    A real ``sentence-transformers`` cross-encoder when the dependency is
    installed and ``RERANK_MODEL`` is set.  Strictly better quality, at the cost
    of a model download.
"""

from __future__ import annotations

import abc
import logging
import math
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.ingest.sectioniser import section_priority
from app.retrieval.bm25 import STOPWORDS
from app.retrieval.embeddings import tokenize

logger = logging.getLogger(__name__)

_STATISTIC = re.compile(
    r"(p\s*[<=>]\s*0?\.\d+)|(95\s*%\s*ci)|(\bci\b)|(\bhr\b)|(\bor\b\s*[=:])|"
    r"(\brr\b)|(\bsd\b)|(\bn\s*=\s*\d+)|(\d+\s*%)|(±)|(\bmean\b)|(\bmedian\b)",
    re.IGNORECASE,
)
_NUMERIC = re.compile(r"\d")


@dataclass
class RerankCandidate:
    chunk_id: str
    text: str
    section_name: str
    prior_score: float = 0.0


@dataclass
class RerankResult:
    chunk_id: str
    score: float
    explain: dict[str, float]


class Reranker(abc.ABC):
    name: str

    @abc.abstractmethod
    def rerank(
        self, query: str, candidates: Sequence[RerankCandidate], top_n: int, *, field: str = ""
    ) -> list[RerankResult]:
        ...


def _content_terms(text: str) -> list[str]:
    return [t for t in tokenize(text) if t not in STOPWORDS and len(t) > 1]


def _longest_common_run(query_terms: Sequence[str], chunk_terms: Sequence[str]) -> int:
    """Longest run of query terms appearing contiguously in the chunk."""
    if not query_terms or not chunk_terms:
        return 0
    positions: dict[str, list[int]] = {}
    for index, term in enumerate(chunk_terms):
        positions.setdefault(term, []).append(index)

    best = 0
    for start in range(len(query_terms)):
        for anchor in positions.get(query_terms[start], []):
            run = 0
            while (
                start + run < len(query_terms)
                and anchor + run < len(chunk_terms)
                and query_terms[start + run] == chunk_terms[anchor + run]
            ):
                run += 1
            best = max(best, run)
    return best


class FeatureReranker(Reranker):
    name = "feature"

    WEIGHTS = {
        "coverage": 0.40,
        "phrase": 0.22,
        "statistics": 0.14,
        "section": 0.14,
        "prior": 0.10,
    }

    def rerank(
        self, query: str, candidates: Sequence[RerankCandidate], top_n: int, *, field: str = ""
    ) -> list[RerankResult]:
        query_terms = _content_terms(query)
        query_set = set(query_terms)
        wants_statistics = bool(_STATISTIC.search(query)) or field in (
            "effect",
            "outcome",
            "sample_size",
        )

        best_prior = max((c.prior_score for c in candidates), default=0.0) or 1.0
        results: list[RerankResult] = []

        for candidate in candidates:
            chunk_terms = _content_terms(candidate.text)
            chunk_set = set(chunk_terms)

            coverage = (
                len(query_set & chunk_set) / len(query_set) if query_set else 0.0
            )

            run = _longest_common_run(query_terms, chunk_terms)
            phrase = min(1.0, run / 3.0) if run > 1 else 0.0

            if wants_statistics:
                hits = len(_STATISTIC.findall(candidate.text))
                digits = len(_NUMERIC.findall(candidate.text))
                statistics = min(
                    1.0, 0.6 * math.log1p(hits) + 0.4 * min(1.0, digits / 25.0)
                )
            else:
                # Off-topic numeric noise is mildly penalised for prose fields.
                statistics = 0.5

            section = min(1.0, (section_priority(candidate.section_name, field) - 0.9) / 0.5)
            section = max(0.0, section)

            prior = candidate.prior_score / best_prior if best_prior else 0.0

            components = {
                "coverage": coverage,
                "phrase": phrase,
                "statistics": statistics,
                "section": section,
                "prior": prior,
            }
            score = sum(self.WEIGHTS[key] * value for key, value in components.items())

            # Very short chunks rarely carry a defensible quote.
            if len(chunk_terms) < 12:
                score *= 0.75
                components["short_penalty"] = 1.0

            results.append(
                RerankResult(chunk_id=candidate.chunk_id, score=score, explain=components)
            )

        results.sort(key=lambda item: item.score, reverse=True)
        return results[:top_n]


class CrossEncoderReranker(Reranker):
    name = "cross_encoder"

    def __init__(self, model_name: str) -> None:
        from sentence_transformers import CrossEncoder  # type: ignore

        self.model_name = model_name
        self._model = CrossEncoder(model_name)

    def rerank(
        self, query: str, candidates: Sequence[RerankCandidate], top_n: int, *, field: str = ""
    ) -> list[RerankResult]:
        if not candidates:
            return []
        pairs = [(query, candidate.text) for candidate in candidates]
        scores = self._model.predict(pairs)
        results = [
            RerankResult(
                chunk_id=candidate.chunk_id,
                score=float(score),
                explain={"cross_encoder": float(score)},
            )
            for candidate, score in zip(candidates, scores, strict=True)
        ]
        results.sort(key=lambda item: item.score, reverse=True)
        return results[:top_n]


_reranker: Reranker | None = None


def get_reranker() -> Reranker:
    global _reranker
    if _reranker is not None:
        return _reranker

    model_name = os.getenv("RERANK_MODEL", "").strip()
    if model_name:
        try:
            _reranker = CrossEncoderReranker(model_name)
            logger.info("Reranker: cross-encoder (%s)", model_name)
            return _reranker
        except Exception as exc:
            logger.warning(
                "Cross-encoder '%s' unavailable (%s); using the feature reranker.",
                model_name,
                exc,
            )

    _reranker = FeatureReranker()
    return _reranker
