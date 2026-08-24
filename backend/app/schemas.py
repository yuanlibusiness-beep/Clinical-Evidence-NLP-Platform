"""Transport schemas for the HTTP API.

These describe what crosses the wire.  The *domain* schema that constrains what
the language model is allowed to emit lives separately in
``app/extraction/schema.py`` -- keeping them apart means we can evolve the API
response shape without loosening the extraction contract, and vice versa.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ------------------------------------------------------------------------- auth
class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserOut(ORMModel):
    id: str
    email: EmailStr
    full_name: str | None = None
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int
    user: UserOut


# -------------------------------------------------------------------- documents
class TextIngestRequest(BaseModel):
    title: str = Field(default="Pasted document", max_length=512)
    text: str = Field(min_length=40)
    year: int | None = None
    authors: str | None = None
    journal: str | None = None


class SectionOut(ORMModel):
    id: str
    name: str
    heading: str | None = None
    order_index: int
    char_start: int
    char_end: int


class ChunkOut(ORMModel):
    id: str
    order_index: int
    section_name: str
    text: str
    token_count: int
    char_start: int
    char_end: int
    page_no: int | None = None


class DocumentOut(ORMModel):
    id: str
    title: str
    authors: str | None = None
    journal: str | None = None
    year: int | None = None
    doi: str | None = None
    pmid: str | None = None
    source_type: str
    source_label: str | None = None
    source_url: str | None = None
    char_count: int
    page_count: int
    status: str
    error: str | None = None
    created_at: datetime


class DocumentDetailOut(DocumentOut):
    raw_text: str
    sections: list[SectionOut] = Field(default_factory=list)
    n_chunks: int = 0


# -------------------------------------------------------------------- retrieval
class RetrievedChunk(BaseModel):
    chunk_id: str
    order_index: int
    section_name: str
    text: str
    char_start: int
    char_end: int
    page_no: int | None = None
    bm25_score: float = 0.0
    vector_score: float = 0.0
    fused_score: float = 0.0
    rerank_score: float | None = None
    rank: int = 0


class RetrieveRequest(BaseModel):
    query: str = Field(min_length=2, max_length=1000)
    top_k: int = Field(default=8, ge=1, le=50)
    rerank: bool = True


class RetrieveResponse(BaseModel):
    query: str
    document_id: str
    results: list[RetrievedChunk]
    took_ms: int


# ------------------------------------------------------------------- extraction
class EvidenceSpanOut(ORMModel):
    field_path: str
    quote: str
    section_name: str
    char_start: int
    char_end: int
    page_no: int | None = None
    match_score: float
    chunk_id: str | None = None


class ExtractionOut(ORMModel):
    id: str
    document_id: str
    provider: str
    model: str
    status: str
    error: str | None = None
    payload: dict[str, Any] | None = None
    confidence: dict[str, float] | None = None
    abstentions: dict[str, str] | None = None
    grounded_field_ratio: float
    latency_ms: int
    created_at: datetime
    spans: list[EvidenceSpanOut] = Field(default_factory=list)


class ExtractionRequest(BaseModel):
    force: bool = Field(
        default=False, description="Re-run even if a completed extraction exists."
    )
    async_mode: bool = Field(
        default=False, description="Queue on Celery instead of running inline."
    )


# -------------------------------------------------------------------- literature
class LiteratureSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    sources: list[str] = Field(default_factory=lambda: ["pubmed", "europepmc"])
    limit: int = Field(default=10, ge=1, le=50)


class LiteratureHit(BaseModel):
    source: str
    external_id: str
    title: str
    abstract: str | None = None
    authors: str | None = None
    journal: str | None = None
    year: int | None = None
    doi: str | None = None
    url: str | None = None


class LiteratureSearchResponse(BaseModel):
    query: str
    total: int
    hits: list[LiteratureHit]
    errors: dict[str, str] = Field(default_factory=dict)


class ImportHitRequest(BaseModel):
    hit: LiteratureHit


# -------------------------------------------------------------------------- jobs
class JobOut(ORMModel):
    id: str
    kind: str
    status: str
    progress: float
    message: str | None = None
    error: str | None = None
    document_id: str | None = None
    extraction_id: str | None = None
    created_at: datetime
    updated_at: datetime


# -------------------------------------------------------------------------- eval
class EvalRunRequest(BaseModel):
    name: str = Field(default="ad-hoc run", max_length=128)
    dataset: str = Field(default="gold_v1")
    limit: int | None = Field(default=None, ge=1, le=200)


class EvalRunOut(ORMModel):
    id: str
    name: str
    provider: str
    model: str
    dataset: str
    n_cases: int
    metrics: dict[str, Any] | None = None
    per_case: list[dict[str, Any]] | None = None
    created_at: datetime


# ------------------------------------------------------------------------ system
class HealthOut(BaseModel):
    status: str
    version: str
    environment: str
    database: str
    llm_provider: str
    llm_model: str
    embedding_provider: str
    embedding_dim: int
    workers: str
