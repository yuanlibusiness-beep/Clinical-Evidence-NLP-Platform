"""The retriever: BM25 + dense vectors, fused by RRF, then reranked.

    query
      ├─ BM25          (lexical, exact drug names, dosages, scale names)
      └─ vector search (semantic, paraphrase, synonymy)
              │
          RRF fusion  -> ~60 candidates
              │
          rerank      -> top 8
              │
        evidence window for the extractor

Each stage exists because the one before it cannot do its job.  BM25 alone
misses "adverse events" when the paper says "safety outcomes".  Dense retrieval
alone drifts on rare tokens: it will happily return a chunk about *a* dose when
you asked about 81 mg.  Fusion keeps both, and reranking pays for precision only
where it is affordable.

The BM25 index is rebuilt per document and cached; the cache key includes the
chunk count so re-indexing a document invalidates it automatically.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Chunk
from app.retrieval import bm25, vector_store
from app.retrieval.embeddings import get_embedder
from app.retrieval.fusion import reciprocal_rank_fusion
from app.retrieval.rerank import RerankCandidate, get_reranker
from app.schemas import RetrievedChunk

logger = logging.getLogger(__name__)

_BM25_CACHE: dict[str, tuple[int, bm25.Bm25Index]] = {}
_BM25_CACHE_LIMIT = 32


class HybridRetriever:
    def __init__(self, db: Session, document_id: str) -> None:
        self.db = db
        self.document_id = document_id
        self._chunks: list[Chunk] | None = None

    # ------------------------------------------------------------------ data
    @property
    def chunks(self) -> list[Chunk]:
        if self._chunks is None:
            self._chunks = list(
                self.db.scalars(
                    select(Chunk)
                    .where(Chunk.document_id == self.document_id)
                    .order_by(Chunk.order_index)
                ).all()
            )
        return self._chunks

    def _bm25_index(self) -> bm25.Bm25Index:
        chunks = self.chunks
        cached = _BM25_CACHE.get(self.document_id)
        if cached and cached[0] == len(chunks):
            return cached[1]

        index = bm25.build_index([c.id for c in chunks], [c.text for c in chunks])
        if len(_BM25_CACHE) >= _BM25_CACHE_LIMIT:
            _BM25_CACHE.pop(next(iter(_BM25_CACHE)))
        _BM25_CACHE[self.document_id] = (len(chunks), index)
        return index

    # -------------------------------------------------------------- retrieve
    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 8,
        field: str = "",
        rerank: bool | None = None,
        section_filter: Sequence[str] | None = None,
    ) -> list[RetrievedChunk]:
        started = time.perf_counter()
        chunks = self.chunks
        if not chunks:
            return []

        by_id = {chunk.id: chunk for chunk in chunks}
        allowed = (
            {c.id for c in chunks if c.section_name in set(section_filter)}
            if section_filter
            else None
        )

        # --- lexical -------------------------------------------------------
        lexical = bm25.score(self._bm25_index(), query, top_k=settings.retrieval_top_k_bm25)
        if allowed is not None:
            lexical = [pair for pair in lexical if pair[0] in allowed]

        # --- dense ---------------------------------------------------------
        try:
            query_vector = get_embedder().embed_one(query)
            dense = vector_store.search(
                self.db,
                self.document_id,
                query_vector,
                top_k=settings.retrieval_top_k_vector,
                section_names=section_filter,
            )
        except Exception as exc:  # a dead embedding endpoint must not 500
            logger.warning("Vector search unavailable, using BM25 only: %s", exc)
            dense = []

        if not lexical and not dense:
            return []

        # --- fuse ----------------------------------------------------------
        fused = reciprocal_rank_fusion(
            {"bm25": lexical, "vector": dense},
            k=settings.retrieval_rrf_k,
            weights={"bm25": 1.0, "vector": 0.9},
            top_k=max(top_k * 4, settings.rerank_top_n * 3),
        )

        # --- rerank --------------------------------------------------------
        use_rerank = settings.rerank_enabled if rerank is None else rerank
        rerank_scores: dict[str, float] = {}
        if use_rerank and fused:
            candidates = [
                RerankCandidate(
                    chunk_id=item.doc_id,
                    text=by_id[item.doc_id].text,
                    section_name=by_id[item.doc_id].section_name,
                    prior_score=item.fused_score,
                )
                for item in fused
                if item.doc_id in by_id
            ]
            ordered = get_reranker().rerank(query, candidates, top_n=top_k, field=field)
            rerank_scores = {item.chunk_id: item.score for item in ordered}
            chosen_ids = [item.chunk_id for item in ordered]
        else:
            chosen_ids = [item.doc_id for item in fused[:top_k]]

        fused_by_id = {item.doc_id: item for item in fused}
        results: list[RetrievedChunk] = []
        for rank, chunk_id in enumerate(chosen_ids, start=1):
            chunk = by_id.get(chunk_id)
            if chunk is None:
                continue
            entry = fused_by_id.get(chunk_id)
            results.append(
                RetrievedChunk(
                    chunk_id=chunk.id,
                    order_index=chunk.order_index,
                    section_name=chunk.section_name,
                    text=chunk.text,
                    char_start=chunk.char_start,
                    char_end=chunk.char_end,
                    page_no=chunk.page_no,
                    bm25_score=entry.raw_scores.get("bm25", 0.0) if entry else 0.0,
                    vector_score=entry.raw_scores.get("vector", 0.0) if entry else 0.0,
                    fused_score=entry.fused_score if entry else 0.0,
                    rerank_score=rerank_scores.get(chunk_id),
                    rank=rank,
                )
            )

        logger.debug(
            "retrieve(%r) -> %d results in %.1f ms",
            query,
            len(results),
            (time.perf_counter() - started) * 1000,
        )
        return results


def invalidate_cache(document_id: str) -> None:
    _BM25_CACHE.pop(document_id, None)
