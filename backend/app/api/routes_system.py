"""Health and capability reporting.

``/health`` answers the question a reviewer actually has on first contact:
*which* configuration am I looking at?  It reports the database backend, the
resolved LLM provider, the embedding provider and whether a worker broker is
attached -- so "why did my extraction come back rule-based?" is one request away
from an answer instead of a debugging session.
"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app import __version__
from app.config import settings
from app.db import engine
from app.extraction.calibration import load_scaler
from app.extraction.prompts import PROMPT_VERSION
from app.schemas import HealthOut

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        database = "postgres" if settings.is_postgres else "sqlite"
    except Exception as exc:
        database = f"unavailable: {exc}"

    return HealthOut(
        status="ok" if not database.startswith("unavailable") else "degraded",
        version=__version__,
        environment=settings.environment,
        database=database,
        llm_provider=settings.resolved_llm_provider,
        llm_model=settings.llm_model if settings.llm_api_key else "rule-based-v1",
        embedding_provider=settings.embedding_provider,
        embedding_dim=settings.embedding_dim,
        workers="celery+redis" if settings.redis_url else "inline (eager)",
    )


@router.get("/config")
def public_config() -> dict:
    """Non-secret configuration the frontend uses to explain itself."""
    scaler = load_scaler()
    return {
        "version": __version__,
        "prompt_version": PROMPT_VERSION,
        "llm_provider": settings.resolved_llm_provider,
        "llm_model": settings.llm_model if settings.llm_api_key else "rule-based-v1",
        "embedding_provider": settings.embedding_provider,
        "abstain_threshold": settings.abstain_threshold,
        "grounding_min_similarity": settings.grounding_min_similarity,
        "confidence_calibrated": scaler.fitted,
        "calibration_samples": scaler.n_samples,
        "external_search_enabled": settings.external_search_enabled,
        "max_evidence_chunks": settings.max_evidence_chunks,
    }
