"""Ingestion orchestration: bytes or text in, an indexed ``Document`` out.

    input (PDF | pasted text | API record)
      -> normalised raw_text            (offsets frozen here, never again)
      -> IMRaD sections                 (sectioniser)
      -> overlapping chunks             (chunker)
      -> embeddings                     (batched, one provider call)
      -> status = "ready"

``raw_text`` is written once and treated as immutable from that point on.  Every
section, chunk and evidence span addresses it by character offset, so mutating
it later would silently invalidate every stored citation.  Re-ingesting creates
a new document instead.
"""

from __future__ import annotations

import logging

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.ingest.chunker import chunk_sections
from app.ingest.pdf import ParsedPdf, parse_pdf
from app.ingest.sectioniser import detect_sections
from app.models import Chunk, Document, Section
from app.retrieval.embeddings import get_embedder
from app.retrieval.hybrid import invalidate_cache
from app.schemas import LiteratureHit
from app.text_utils import clean_pdf_text

logger = logging.getLogger(__name__)

MIN_TEXT_CHARS = 40


class IngestError(RuntimeError):
    pass


# --------------------------------------------------------------------- create
def create_document_from_text(
    db: Session,
    *,
    user_id: str,
    title: str,
    text: str,
    source_type: str = "text",
    source_label: str | None = None,
    source_url: str | None = None,
    authors: str | None = None,
    journal: str | None = None,
    year: int | None = None,
    doi: str | None = None,
    pmid: str | None = None,
    page_count: int = 0,
) -> Document:
    cleaned = clean_pdf_text(text)
    if len(cleaned) < MIN_TEXT_CHARS:
        raise IngestError(
            f"Document text is only {len(cleaned)} characters; "
            f"at least {MIN_TEXT_CHARS} are required."
        )

    document = Document(
        user_id=user_id,
        title=(title or "Untitled document").strip()[:500],
        authors=authors,
        journal=journal,
        year=year,
        doi=doi,
        pmid=pmid,
        source_type=source_type,
        source_label=source_label,
        source_url=source_url,
        raw_text=cleaned,
        char_count=len(cleaned),
        page_count=page_count,
        status="pending",
    )
    db.add(document)
    db.flush()
    return document


def create_document_from_pdf(
    db: Session, *, user_id: str, data: bytes, filename: str
) -> tuple[Document, ParsedPdf]:
    parsed = parse_pdf(data, filename=filename)
    document = create_document_from_text(
        db,
        user_id=user_id,
        title=parsed.title or filename,
        text=parsed.text,
        source_type="pdf",
        source_label=filename,
        year=parsed.year,
        doi=parsed.doi,
        page_count=parsed.page_count,
    )
    return document, parsed


def create_document_from_hit(
    db: Session, *, user_id: str, hit: LiteratureHit
) -> Document:
    body = hit.abstract or ""
    if not body.strip():
        raise IngestError(
            f"'{hit.title[:60]}' has no abstract in {hit.source}; "
            "upload the PDF instead."
        )
    # Prepending the title gives the sectioniser a title block to anchor on and
    # keeps the title retrievable as evidence.
    text = f"{hit.title}\n\nAbstract\n{body}"
    return create_document_from_text(
        db,
        user_id=user_id,
        title=hit.title,
        text=text,
        source_type=hit.source,
        source_label=f"{hit.source}:{hit.external_id}",
        source_url=hit.url,
        authors=hit.authors,
        journal=hit.journal,
        year=hit.year,
        doi=hit.doi,
        pmid=hit.external_id if hit.source == "pubmed" else None,
    )


# ---------------------------------------------------------------------- index
def index_document(
    db: Session, document: Document, *, page_map: list | None = None
) -> int:
    """(Re)build sections, chunks and embeddings for a document.

    Idempotent: existing sections and chunks are dropped first, so a failed or
    partial previous run cannot leave a half-populated index behind.
    """
    document.status = "parsing"
    db.flush()

    db.execute(delete(Chunk).where(Chunk.document_id == document.id))
    db.execute(delete(Section).where(Section.document_id == document.id))
    invalidate_cache(document.id)

    try:
        detected = detect_sections(document.raw_text, title=document.title)
        section_rows: list[Section] = []
        for item in detected:
            row = Section(
                document_id=document.id,
                name=item.name,
                heading=item.heading,
                order_index=item.order_index,
                char_start=item.char_start,
                char_end=item.char_end,
                text=item.text,
            )
            db.add(row)
            section_rows.append(row)
        db.flush()

        built = chunk_sections(detected, page_map=page_map)
        if not built:
            raise IngestError("Chunking produced no text; the document may be empty.")

        document.status = "indexing"
        db.flush()

        embedder = get_embedder()
        vectors = embedder.embed([chunk.text for chunk in built])

        for chunk, vector in zip(built, vectors, strict=True):
            section_row = (
                section_rows[chunk.section_index]
                if 0 <= chunk.section_index < len(section_rows)
                else None
            )
            db.add(
                Chunk(
                    document_id=document.id,
                    section_id=section_row.id if section_row else None,
                    order_index=chunk.order_index,
                    section_name=chunk.section_name,
                    text=chunk.text,
                    token_count=chunk.token_count,
                    char_start=chunk.char_start,
                    char_end=chunk.char_end,
                    page_no=chunk.page_no,
                    embedding=vector,
                )
            )

        document.status = "ready"
        document.error = None
        db.flush()
        logger.info(
            "Indexed document %s: %d sections, %d chunks",
            document.id,
            len(section_rows),
            len(built),
        )
        return len(built)

    except Exception as exc:
        document.status = "failed"
        document.error = str(exc)[:1000]
        db.flush()
        logger.exception("Indexing failed for document %s", document.id)
        raise
