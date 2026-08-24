"""ORM models.

Shape of the domain, top to bottom:

    User ──< Document ──< Section ──< Chunk
                   │
                   └──< Extraction ──< EvidenceSpan ──> Chunk

A ``Document`` is one clinical paper (uploaded PDF, pasted text, or a record
pulled from an academic API).  Parsing splits it into IMRaD ``Section`` rows and
then into retrieval-sized ``Chunk`` rows carrying embeddings.  An ``Extraction``
is one structured evidence review of that document; every non-null field it
emits is backed by at least one ``EvidenceSpan`` pointing at the exact character
range of the chunk it came from.  That link is what makes a claim auditable.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.config import settings
from app.db import Base
from app.db_types import EmbeddingVector


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.utcnow()


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    documents: Mapped[list[Document]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    title: Mapped[str] = mapped_column(Text, default="Untitled document")
    authors: Mapped[str | None] = mapped_column(Text, nullable=True)
    journal: Mapped[str | None] = mapped_column(Text, nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    doi: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    pmid: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)

    # "pdf" | "text" | "pubmed" | "europepmc" | "crossref"
    source_type: Mapped[str] = mapped_column(String(32), default="text")
    source_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    raw_text: Mapped[str] = mapped_column(Text, default="")
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    page_count: Mapped[int] = mapped_column(Integer, default=0)

    # "pending" | "parsing" | "indexing" | "ready" | "failed"
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)

    owner: Mapped[User] = relationship(back_populates="documents")
    sections: Mapped[list[Section]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="Section.order_index",
    )
    chunks: Mapped[list[Chunk]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="Chunk.order_index",
    )
    extractions: Mapped[list[Extraction]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="Extraction.created_at.desc()",
    )


class Section(Base):
    """One IMRaD-normalised section of a document."""

    __tablename__ = "sections"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    # canonical label: title/abstract/background/methods/results/discussion/...
    name: Mapped[str] = mapped_column(String(48), default="body", index=True)
    heading: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    char_start: Mapped[int] = mapped_column(Integer, default=0)
    char_end: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text, default="")

    document: Mapped[Document] = relationship(back_populates="sections")
    chunks: Mapped[list[Chunk]] = relationship(back_populates="section")


class Chunk(Base):
    """A retrieval unit: a window of one section, with its embedding."""

    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "order_index", name="uq_chunk_doc_order"),
        Index("ix_chunk_doc_section", "document_id", "section_id"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    section_id: Mapped[str | None] = mapped_column(
        ForeignKey("sections.id", ondelete="SET NULL"), nullable=True
    )

    order_index: Mapped[int] = mapped_column(Integer, default=0)
    section_name: Mapped[str] = mapped_column(String(48), default="body", index=True)
    text: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    # Character offsets into Document.raw_text -> lets the UI highlight in place.
    char_start: Mapped[int] = mapped_column(Integer, default=0)
    char_end: Mapped[int] = mapped_column(Integer, default=0)
    page_no: Mapped[int | None] = mapped_column(Integer, nullable=True)

    embedding = mapped_column(EmbeddingVector(settings.embedding_dim), nullable=True)

    document: Mapped[Document] = relationship(back_populates="chunks")
    section: Mapped[Section | None] = relationship(back_populates="chunks")


class Extraction(Base):
    """One structured evidence review of one document."""

    __tablename__ = "extractions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(String(32), index=True)

    provider: Mapped[str] = mapped_column(String(32), default="offline")
    model: Mapped[str] = mapped_column(String(128), default="rule-based")
    # "pending" | "running" | "completed" | "failed"
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # The validated EvidenceReview payload (see app/extraction/schema.py).
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Per-field calibrated confidence, 0..1.
    confidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Fields the model declined to answer, with the reason.
    abstentions: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    grounded_field_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)

    document: Mapped[Document] = relationship(back_populates="extractions")
    spans: Mapped[list[EvidenceSpan]] = relationship(
        back_populates="extraction", cascade="all, delete-orphan"
    )


class EvidenceSpan(Base):
    """Citation-level provenance for a single extracted field.

    ``field_path`` is a dotted path into the payload, e.g. ``pico.intervention``
    or ``outcomes.primary[0].effect_size``.  ``char_start``/``char_end`` are
    offsets into ``Document.raw_text`` so the reader can be taken to the exact
    sentence the model relied on.
    """

    __tablename__ = "evidence_spans"
    __table_args__ = (Index("ix_span_extraction_field", "extraction_id", "field_path"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    extraction_id: Mapped[str] = mapped_column(
        ForeignKey("extractions.id", ondelete="CASCADE"), index=True
    )
    chunk_id: Mapped[str | None] = mapped_column(
        ForeignKey("chunks.id", ondelete="SET NULL"), nullable=True
    )

    field_path: Mapped[str] = mapped_column(String(128))
    quote: Mapped[str] = mapped_column(Text)
    section_name: Mapped[str] = mapped_column(String(48), default="body")
    char_start: Mapped[int] = mapped_column(Integer, default=0)
    char_end: Mapped[int] = mapped_column(Integer, default=0)
    page_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # How closely the model's quote matched the source text (1.0 == verbatim).
    match_score: Mapped[float] = mapped_column(Float, default=0.0)

    extraction: Mapped[Extraction] = relationship(back_populates="spans")


class Job(Base):
    """Async unit of work (parse / index / extract) surfaced to the UI."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    document_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    extraction_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

    kind: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now
    )


class EvalRun(Base):
    """A stored automatic-evaluation run over the gold dataset."""

    __tablename__ = "eval_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(128))
    provider: Mapped[str] = mapped_column(String(32), default="offline")
    model: Mapped[str] = mapped_column(String(128), default="rule-based")
    dataset: Mapped[str] = mapped_column(String(128), default="gold_v1")
    n_cases: Mapped[int] = mapped_column(Integer, default=0)
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    per_case: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)
