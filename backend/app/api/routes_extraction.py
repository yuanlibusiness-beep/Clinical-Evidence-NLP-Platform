"""Running and reading evidence extractions.

``POST /extract`` runs inline by default, which keeps the common case (one
paper, a few seconds) simple and observable.  ``async_mode=true`` hands the work
to Celery and returns a ``Job`` to poll -- the path that matters when a batch of
papers is queued or an LLM call is slow.

The route refuses to run on a document that is not fully indexed.  Extracting
from a half-built index silently produces a worse review, and a worse review
that looks identical to a good one is the failure mode this whole project is
designed to avoid.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_owned_document
from app.db import get_db
from app.extraction.pipeline import run_extraction
from app.models import Document, Extraction, Job, User
from app.retrieval.vector_store import index_health
from app.schemas import (
    EvidenceSpanOut,
    ExtractionOut,
    ExtractionRequest,
    JobOut,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["extraction"])


@router.post("/documents/{document_id}/extract", response_model=ExtractionOut)
def extract(
    payload: ExtractionRequest,
    document: Document = Depends(get_owned_document),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ExtractionOut:
    if document.status != "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Document is '{document.status}', not 'ready'. Re-index it first.",
        )

    health = index_health(db, document.id)
    if not health["complete"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Index incomplete: {health['embedded']}/{health['chunks']} chunks "
                "embedded. POST /documents/{id}/reindex first."
            ),
        )

    if not payload.force:
        existing = db.scalar(
            select(Extraction)
            .where(
                Extraction.document_id == document.id,
                Extraction.status == "completed",
            )
            .order_by(Extraction.created_at.desc())
        )
        if existing is not None:
            return _to_out(existing)

    if payload.async_mode:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Use POST /documents/{id}/extract-async for queued extraction.",
        )

    extraction = run_extraction(db, document, user_id=user.id)
    db.commit()
    db.refresh(extraction)

    if extraction.status == "failed":
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Extraction failed: {extraction.error}",
        )
    return _to_out(extraction)


@router.post(
    "/documents/{document_id}/extract-async",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def extract_async(
    document: Document = Depends(get_owned_document),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JobOut:
    from app.workers.tasks import enqueue_extraction

    job = Job(
        user_id=user.id,
        document_id=document.id,
        kind="extract",
        status="queued",
        message="Queued for extraction.",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    enqueue_extraction(job_id=job.id, document_id=document.id, user_id=user.id)
    return JobOut.model_validate(job)


@router.get("/documents/{document_id}/extractions", response_model=list[ExtractionOut])
def list_extractions(
    document: Document = Depends(get_owned_document), db: Session = Depends(get_db)
) -> list[ExtractionOut]:
    rows = db.scalars(
        select(Extraction)
        .where(Extraction.document_id == document.id)
        .order_by(Extraction.created_at.desc())
    ).all()
    return [_to_out(row) for row in rows]


@router.get("/extractions/{extraction_id}", response_model=ExtractionOut)
def get_extraction(
    extraction_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ExtractionOut:
    extraction = db.get(Extraction, extraction_id)
    if extraction is None or extraction.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Extraction not found."
        )
    return _to_out(extraction)


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(
    job_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> JobOut:
    job = db.get(Job, job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    return JobOut.model_validate(job)


def _to_out(extraction: Extraction) -> ExtractionOut:
    out = ExtractionOut.model_validate(extraction)
    out.spans = [EvidenceSpanOut.model_validate(span) for span in extraction.spans]
    return out
