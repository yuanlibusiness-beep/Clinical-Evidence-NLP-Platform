"""Document ingestion, listing and retrieval inspection.

The ``/retrieve`` endpoint is intentionally exposed to the UI even though the
extractor calls the retriever internally.  Being able to type a query and see
which chunks come back, with the BM25 score, the vector score, the fused score
and the rerank score side by side, is the difference between a retrieval stack
you can debug and one you can only trust.
"""

from __future__ import annotations

import logging
import time

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_owned_document
from app.db import get_db
from app.ingest.pdf import PdfParseError
from app.ingest.pipeline import (
    IngestError,
    create_document_from_pdf,
    create_document_from_text,
    index_document,
)
from app.models import Chunk, Document, User
from app.retrieval.hybrid import HybridRetriever, invalidate_cache
from app.retrieval.vector_store import index_health
from app.schemas import (
    ChunkOut,
    DocumentDetailOut,
    DocumentOut,
    RetrieveRequest,
    RetrieveResponse,
    SectionOut,
    TextIngestRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload", response_model=DocumentDetailOut, status_code=status.HTTP_201_CREATED)
async def upload_pdf(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DocumentDetailOut:
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only PDF uploads are supported. Paste the text instead.",
        )

    data = await file.read()
    try:
        document, parsed = create_document_from_pdf(
            db, user_id=user.id, data=data, filename=file.filename or "document.pdf"
        )
        index_document(db, document, page_map=parsed.page_map)
    except (PdfParseError, IngestError) as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    db.commit()
    db.refresh(document)
    return _detail(db, document)


@router.post("/text", response_model=DocumentDetailOut, status_code=status.HTTP_201_CREATED)
def ingest_text(
    payload: TextIngestRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DocumentDetailOut:
    try:
        document = create_document_from_text(
            db,
            user_id=user.id,
            title=payload.title,
            text=payload.text,
            source_type="text",
            source_label="pasted text",
            authors=payload.authors,
            journal=payload.journal,
            year=payload.year,
        )
        index_document(db, document)
    except IngestError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    db.commit()
    db.refresh(document)
    return _detail(db, document)


@router.get("", response_model=list[DocumentOut])
def list_documents(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    status_filter: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DocumentOut]:
    statement = (
        select(Document)
        .where(Document.user_id == user.id)
        .order_by(Document.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if status_filter:
        statement = statement.where(Document.status == status_filter)
    return [DocumentOut.model_validate(row) for row in db.scalars(statement).all()]


@router.get("/{document_id}", response_model=DocumentDetailOut)
def get_document(
    document: Document = Depends(get_owned_document), db: Session = Depends(get_db)
) -> DocumentDetailOut:
    return _detail(db, document)


@router.get("/{document_id}/chunks", response_model=list[ChunkOut])
def list_chunks(
    document: Document = Depends(get_owned_document), db: Session = Depends(get_db)
) -> list[ChunkOut]:
    rows = db.scalars(
        select(Chunk).where(Chunk.document_id == document.id).order_by(Chunk.order_index)
    ).all()
    return [ChunkOut.model_validate(row) for row in rows]


@router.post("/{document_id}/retrieve", response_model=RetrieveResponse)
def retrieve(
    payload: RetrieveRequest,
    document: Document = Depends(get_owned_document),
    db: Session = Depends(get_db),
) -> RetrieveResponse:
    started = time.perf_counter()
    results = HybridRetriever(db, document.id).retrieve(
        payload.query, top_k=payload.top_k, rerank=payload.rerank
    )
    return RetrieveResponse(
        query=payload.query,
        document_id=document.id,
        results=results,
        took_ms=int((time.perf_counter() - started) * 1000),
    )


@router.post("/{document_id}/reindex", response_model=DocumentDetailOut)
def reindex(
    document: Document = Depends(get_owned_document), db: Session = Depends(get_db)
) -> DocumentDetailOut:
    """Rebuild sections, chunks and embeddings -- e.g. after changing the
    embedding provider or the chunk size."""
    try:
        index_document(db, document)
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    db.commit()
    db.refresh(document)
    return _detail(db, document)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document: Document = Depends(get_owned_document), db: Session = Depends(get_db)
) -> None:
    invalidate_cache(document.id)
    db.execute(delete(Document).where(Document.id == document.id))
    db.commit()


# ------------------------------------------------------------------- helpers
def _detail(db: Session, document: Document) -> DocumentDetailOut:
    n_chunks = (
        db.scalar(
            select(func.count()).select_from(Chunk).where(Chunk.document_id == document.id)
        )
        or 0
    )
    detail = DocumentDetailOut.model_validate(document)
    detail.sections = [SectionOut.model_validate(s) for s in document.sections]
    detail.n_chunks = int(n_chunks)
    return detail


@router.get("/{document_id}/index-health")
def get_index_health(
    document: Document = Depends(get_owned_document), db: Session = Depends(get_db)
) -> dict:
    return index_health(db, document.id)
