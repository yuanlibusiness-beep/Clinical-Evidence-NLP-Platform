"""Dialect-portable column types.

The only genuinely database-specific thing in this project is the embedding
column.  Rather than fork the ORM models per backend, we hide the difference in
one ``TypeDecorator``:

* PostgreSQL -> a real ``vector(N)`` column, so ANN search happens in the
  database via pgvector's ``<=>`` cosine-distance operator.
* SQLite     -> a packed ``float32`` blob, scored in NumPy.  Slower, but exact
  and dependency-free, which is what makes ``git clone && pytest`` work.

Both paths hand Python the same thing: a ``numpy.ndarray`` of shape ``(dim,)``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
from sqlalchemy import LargeBinary
from sqlalchemy.types import TypeDecorator


class EmbeddingVector(TypeDecorator):
    """Stores a fixed-width float32 vector on any supported dialect."""

    impl = LargeBinary
    cache_ok = True

    def __init__(self, dim: int, *args: Any, **kwargs: Any) -> None:
        self.dim = dim
        super().__init__(*args, **kwargs)

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            try:
                from pgvector.sqlalchemy import Vector

                return dialect.type_descriptor(Vector(self.dim))
            except ImportError as exc:  # pragma: no cover - misconfigured deployment
                raise RuntimeError(
                    "PostgreSQL backend selected but 'pgvector' is not installed. "
                    "Install it with: pip install pgvector"
                ) from exc
        return dialect.type_descriptor(LargeBinary())

    def process_bind_param(
        self, value: Sequence[float] | None, dialect
    ) -> Any | None:
        if value is None:
            return None
        array = np.asarray(value, dtype=np.float32).reshape(-1)
        if array.shape[0] != self.dim:
            raise ValueError(
                f"Embedding has dimension {array.shape[0]}, expected {self.dim}. "
                "Re-index after changing EMBEDDING_DIM or EMBEDDING_PROVIDER."
            )
        if dialect.name == "postgresql":
            return array.tolist()
        return array.tobytes()

    def process_result_value(self, value: Any, dialect) -> np.ndarray | None:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return np.asarray(value, dtype=np.float32)
        return np.frombuffer(value, dtype=np.float32)
