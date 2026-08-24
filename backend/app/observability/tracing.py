"""Tracing and LLM observability, both strictly optional.

Two independent integrations, each a no-op unless configured:

* **OpenTelemetry** -- auto-instruments FastAPI, SQLAlchemy and httpx, so a slow
  request can be attributed to retrieval, the database, or the model provider
  rather than guessed at.  Enabled by ``OTEL_ENABLED=true``.
* **Langfuse** -- LLM-specific tracing: prompt, completion, token counts, cost
  and latency per extraction, which is what you actually need when a prompt
  change makes quality worse and you want to see why.

Both are wrapped in try/except by design.  Observability failing must never take
the application down with it -- an unreachable collector is an inconvenience,
not an outage.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

_langfuse: Any | None = None


def setup_tracing(app: Any = None, engine: Any = None) -> None:
    if not settings.otel_enabled:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create(
            {
                "service.name": "clinical-evidence-nlp",
                "deployment.environment": settings.environment,
            }
        )
        provider = TracerProvider(resource=resource)
        if settings.otel_exporter_otlp_endpoint:
            provider.add_span_processor(
                BatchSpanProcessor(
                    OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint)
                )
            )
        trace.set_tracer_provider(provider)

        if app is not None:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

            FastAPIInstrumentor.instrument_app(app)
        if engine is not None:
            from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

            SQLAlchemyInstrumentor().instrument(engine=engine)

        logger.info("OpenTelemetry tracing enabled.")
    except ImportError:
        logger.warning(
            "OTEL_ENABLED=true but the OpenTelemetry packages are not installed; "
            "install the 'observability' extra."
        )
    except Exception as exc:  # pragma: no cover - collector issues
        logger.warning("Tracing setup failed (continuing without it): %s", exc)


def get_langfuse() -> Any | None:
    global _langfuse
    if _langfuse is not None:
        return _langfuse
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        return None
    try:
        from langfuse import Langfuse

        _langfuse = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        logger.info("Langfuse tracing enabled.")
        return _langfuse
    except Exception as exc:
        logger.warning("Langfuse unavailable (continuing without it): %s", exc)
        return None


def trace_extraction(
    *,
    document_id: str,
    provider: str,
    model: str,
    prompt_version: str,
    latency_ms: int,
    prompt_tokens: int,
    completion_tokens: int,
    grounded_ratio: float,
) -> None:
    """Record one extraction as a Langfuse trace, if configured."""
    client = get_langfuse()
    if client is None:
        return
    try:
        client.trace(
            name="evidence-extraction",
            metadata={
                "document_id": document_id,
                "provider": provider,
                "model": model,
                "prompt_version": prompt_version,
                "latency_ms": latency_ms,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "grounded_field_ratio": grounded_ratio,
            },
        )
    except Exception as exc:  # pragma: no cover
        logger.debug("Langfuse trace failed: %s", exc)
