"""Reciprocal Rank Fusion.

BM25 scores and cosine similarities live on incompatible scales; normalising
them (min-max, z-score) makes the blend depend on the score *distribution* of
whichever query happened to be asked, which is unstable on a corpus of a few
hundred chunks.  RRF sidesteps the problem by throwing the magnitudes away and
fusing on rank alone:

    RRF(d) = Σ_lists  weight_l / (k + rank_l(d))

``k`` (default 60, from Cormack et al. 2009) damps the top of each list so a
single list cannot dominate; a document ranked well by *both* retrievers beats
one ranked first by only one of them.  That is exactly the behaviour we want:
lexical precision from BM25, semantic recall from the vector index.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field


@dataclass
class FusedResult:
    doc_id: str
    fused_score: float
    ranks: dict[str, int] = field(default_factory=dict)
    raw_scores: dict[str, float] = field(default_factory=dict)


def reciprocal_rank_fusion(
    ranked_lists: dict[str, Sequence[tuple[str, float]]],
    *,
    k: int = 60,
    weights: dict[str, float] | None = None,
    top_k: int | None = None,
) -> list[FusedResult]:
    weights = weights or {}
    accumulator: dict[str, FusedResult] = {}

    for list_name, ranked in ranked_lists.items():
        weight = weights.get(list_name, 1.0)
        for position, (doc_id, raw_score) in enumerate(ranked):
            rank = position + 1
            entry = accumulator.get(doc_id)
            if entry is None:
                entry = FusedResult(doc_id=doc_id, fused_score=0.0)
                accumulator[doc_id] = entry
            entry.fused_score += weight / (k + rank)
            entry.ranks[list_name] = rank
            entry.raw_scores[list_name] = float(raw_score)

    results = sorted(
        accumulator.values(), key=lambda item: item.fused_score, reverse=True
    )
    return results[:top_k] if top_k else results
