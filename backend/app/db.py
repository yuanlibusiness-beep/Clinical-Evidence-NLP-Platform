"""Database engine, session lifecycle and dialect bootstrap.

The platform targets PostgreSQL + pgvector in production but must stay runnable
with zero infrastructure (SQLite) for local development, CI and reviewers who
just cloned the repository.  Both paths share the same ORM models; only the
vector column type and the nearest-neighbour search differ, and that difference
is isolated in ``app.retrieval.vector_store``.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


def _make_engine():
    url = settings.database_url
    kwargs: dict = {"echo": settings.sql_echo, "future": True}

    if url.startswith("sqlite"):
        # Ensure the parent directory of a file-backed SQLite DB exists.
        if ":///" in url and not url.endswith(":memory:"):
            path = url.split(":///", 1)[1]
            if path and path != ":memory:":
                os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs.update(pool_pre_ping=True, pool_size=5, max_overflow=10)

    return create_engine(url, **kwargs)


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


if settings.is_sqlite:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - trivial
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for background workers and scripts."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """Create the pgvector extension (if needed) and all tables.

    Real migrations live in Alembic; this is the idempotent bootstrap used by
    docker-compose, the test-suite and first-run local development.
    """
    if settings.is_postgres:
        with engine.connect() as conn:
            try:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                conn.commit()
            except Exception as exc:  # pragma: no cover - depends on grants
                logger.warning("Could not create pgvector extension: %s", exc)

    from app import models  # noqa: F401  (register mappers before create_all)

    Base.metadata.create_all(bind=engine)
    logger.info("Database ready (%s)", "postgres" if settings.is_postgres else "sqlite")
