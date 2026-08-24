"""Nearest-neighbour search, one interface over two backends.

PostgreSQL path: the comparison happens in the database using pgvector's ``<=>``
cosine-distance operator, so only the top-k rows cross the wire.  With an
``ivfflat``/``hnsw`` index this scales past what a Python loop can handle.

SQLite path: vectors come back as float32 blobs and are scored with a single
NumPy matrix multiply.  Exact, and fast enough for the scale a single paper
implies (hundreds of chunks), which is what makes the project runnable with no
services at all.

Both return the same thing: ``[(chunk_id, cosine_similarity)]``, descending.
All vectors are stored L2-normalised, so the dot product *is* cosine similarity.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Chunk

logger = logging.getLogger(__name__)


def search(
    db: Session,
    document_id: str,
    query_vector: np.ndarray,
    top_k: int = 30,
    *,
    section_names: Sequence[str] | None = None,
) -> list[tuple[str, float]]:
    query_vector = np.asarray(query_vector, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(query_vector))
    if norm == 0:
        return []
    query_vector = query_vector / norm

    if settings.is_postgres:
        return _search_pgvector(db, document_id, query_vector, top_k, section_names)
    return _search_numpy(db, document_id, query_vector, top_k, section_names)


def _search_pgvector(
    db: Session,
    document_id: str,
    query_vector: np.ndarray,
    top_k: int,
    section_names: Sequence[str] | None,
) -> list[tuple[str, float]]:
    distance = Chunk.embedding.cosine_distance(query_vector.tolist())
    statement = (
        select(Chunk.id, distance.label("distance"))
        .where(Chunk.document_id == document_id, Chunk.embedding.is_not(None))
        .order_by(distance)
        .limit(top_k)
    )
    if section_names:
        statement = statement.where(Chunk.section_name.in_(list(section_names)))

    return [(chunk_id, 1.0 - float(dist)) for chunk_id, dist in db.execute(statement)]


def _search_numpy(
    db: Session,
    document_id: str,
    query_vector: np.ndarray,
    top_k: int,
    section_names: Sequence[str] | None,
) -> list[tuple[str, float]]:
    statement = select(Chunk.id, Chunk.embedding).where(
        Chunk.document_id == document_id, Chunk.embedding.is_not(None)
    )
    if section_names:
        statement = statement.where(Chunk.section_name.in_(list(section_names)))

    rows = db.execute(statement).all()
    if not rows:
        return []

    ids = [row[0] for row in rows]
    matrix = np.vstack([np.asarray(row[1], dtype=np.float32) for row in rows])
    scores = matrix @ query_vector

    limit = min(top_k, len(ids))
    # argpartition finds the top-k without a full sort, then we sort just those.
    top_indices = np.argpartition(-scores, limit - 1)[:limit]
    top_indices = top_indices[np.argsort(-scores[top_indices])]
    return [(ids[int(i)], float(scores[int(i)])) for i in top_indices]


def index_health(db: Session, document_id: str) -> dict:
    """Counts used by ``/documents/{id}`` and the tests to assert the index is
    complete before an extraction is allowed to run."""
    total = (
        db.scalar(
            select(func.count())
            .select_from(Chunk)
            .where(Chunk.document_id == document_id)
        )
        or 0
    )
    embedded = (
        db.scalar(
            select(func.count())
            .select_from(Chunk)
            .where(Chunk.document_id == document_id, Chunk.embedding.is_not(None))
        )
        or 0
    )
    return {
        "chunks": int(total),
        "embedded": int(embedded),
        "backend": "pgvector" if settings.is_postgres else "numpy",
        "complete": total > 0 and total == embedded,
    }
