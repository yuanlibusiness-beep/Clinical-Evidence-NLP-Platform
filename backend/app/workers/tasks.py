"""Background tasks.

Each task owns its own database session (``session_scope``) rather than
inheriting one from a request -- a worker process has no request, and sharing a
session across process boundaries is how you get mysterious detached-instance
errors.

The ``Job`` row is the contract with the UI: the API returns a job id, the task
moves it through ``queued -> running -> completed | failed``, and the frontend
polls.  Every terminal state, including failure, is written back, so a job never
disappears without an explanation.
"""

from __future__ import annotations

import logging

from app.db import session_scope
from app.extraction.pipeline import run_extraction
from app.ingest.pipeline import index_document
from app.models import Document, Job
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _update_job(job_id: str, **fields) -> None:
    with session_scope() as db:
        job = db.get(Job, job_id)
        if job is None:
            logger.warning("Job %s vanished before update", job_id)
            return
        for key, value in fields.items():
            setattr(job, key, value)


@celery_app.task(name="extraction.run", bind=True, max_retries=2)
def extraction_task(self, job_id: str, document_id: str, user_id: str) -> dict:
    _update_job(job_id, status="running", progress=0.1, message="Loading document.")

    try:
        with session_scope() as db:
            document = db.get(Document, document_id)
            if document is None:
                raise ValueError(f"Document {document_id} no longer exists.")
            if document.status != "ready":
                raise ValueError(
                    f"Document {document_id} is '{document.status}', not 'ready'."
                )

            extraction = run_extraction(db, document, user_id=user_id)
            db.flush()
            extraction_id = extraction.id
            status = extraction.status
            error = extraction.error

        if status == "failed":
            _update_job(
                job_id,
                status="failed",
                progress=1.0,
                extraction_id=extraction_id,
                error=error,
                message="Extraction failed.",
            )
            return {"status": "failed", "extraction_id": extraction_id}

        _update_job(
            job_id,
            status="completed",
            progress=1.0,
            extraction_id=extraction_id,
            message="Extraction complete.",
        )
        return {"status": "completed", "extraction_id": extraction_id}

    except Exception as exc:
        logger.exception("Extraction task failed for job %s", job_id)
        _update_job(
            job_id, status="failed", progress=1.0, error=str(exc)[:1000],
            message="Extraction failed.",
        )
        # Retry transient failures only; a missing document will never succeed.
        if not isinstance(exc, ValueError):
            raise self.retry(exc=exc, countdown=30) from exc
        return {"status": "failed", "error": str(exc)}


@celery_app.task(name="ingest.reindex", bind=True, max_retries=1)
def reindex_task(self, job_id: str, document_id: str) -> dict:
    _update_job(job_id, status="running", progress=0.2, message="Re-indexing.")
    try:
        with session_scope() as db:
            document = db.get(Document, document_id)
            if document is None:
                raise ValueError(f"Document {document_id} no longer exists.")
            n_chunks = index_document(db, document)
        _update_job(
            job_id, status="completed", progress=1.0, message=f"Indexed {n_chunks} chunks."
        )
        return {"status": "completed", "chunks": n_chunks}
    except Exception as exc:
        logger.exception("Reindex task failed for job %s", job_id)
        _update_job(job_id, status="failed", progress=1.0, error=str(exc)[:1000])
        return {"status": "failed", "error": str(exc)}


# ------------------------------------------------------------------ enqueue
def enqueue_extraction(*, job_id: str, document_id: str, user_id: str) -> str | None:
    """Send the task to the broker, or run it inline in eager mode."""
    async_result = extraction_task.delay(job_id, document_id, user_id)
    return getattr(async_result, "id", None)
