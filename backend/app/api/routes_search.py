"""Federated literature search and one-click import.

Search fans out across the registered sources concurrently and returns partial
results with a per-source ``errors`` map rather than failing the request when
one database is slow or down.  The UI shows those errors next to the results,
which is more honest than silently returning fewer hits.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.config import settings
from app.db import get_db
from app.ingest.pipeline import IngestError, create_document_from_hit, index_document
from app.ingest.sources import available_sources, search_all
from app.models import User
from app.schemas import (
    DocumentOut,
    ImportHitRequest,
    LiteratureSearchRequest,
    LiteratureSearchResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/literature", tags=["literature"])


@router.get("/sources")
def list_sources() -> dict:
    return {"sources": available_sources(), "enabled": settings.external_search_enabled}


@router.post("/search", response_model=LiteratureSearchResponse)
def search(
    payload: LiteratureSearchRequest, _user: User = Depends(get_current_user)
) -> LiteratureSearchResponse:
    if not settings.external_search_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="External literature search is disabled (EXTERNAL_SEARCH_ENABLED=false).",
        )

    hits, errors = search_all(payload.query, payload.sources, payload.limit)
    if not hits and errors:
        # Every source failed -- that is a real failure, not an empty result.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"All literature sources failed: {errors}",
        )

    return LiteratureSearchResponse(
        query=payload.query, total=len(hits), hits=hits, errors=errors
    )


@router.post("/import", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
def import_hit(
    payload: ImportHitRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DocumentOut:
    try:
        document = create_document_from_hit(db, user_id=user.id, hit=payload.hit)
        index_document(db, document)
    except IngestError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    db.commit()
    db.refresh(document)
    return DocumentOut.model_validate(document)
