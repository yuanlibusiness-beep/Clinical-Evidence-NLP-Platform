"""Central configuration.

Every knob of the platform is read from environment variables exactly once, at
import time, into a single frozen ``Settings`` object.  Modules never call
``os.getenv`` directly -- that keeps the runtime behaviour reproducible and makes
the whole surface testable via ``Settings(...)`` overrides.
"""

from __future__ import annotations

import functools
import json
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ------------------------------------------------------------------ app
    app_name: str = "Clinical Evidence NLP Platform"
    environment: Literal["local", "ci", "staging", "production"] = "local"
    debug: bool = True
    api_prefix: str = "/api/v1"
    # NoDecode: read the raw string from env/.env and let the validator below parse
    # it, so both "http://a,http://b" and '["http://a"]' work.  Without it,
    # pydantic-settings insists on JSON and the README's own .env crashes on boot.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )

    # ------------------------------------------------------------- security
    # NOTE: the default is deliberately obvious.  ``check_production_safety``
    # refuses to boot a non-local environment while it is still in place.
    jwt_secret: str = "dev-only-insecure-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 60 * 12
    password_hash_rounds: int = 12

    # ------------------------------------------------------------- database
    # postgresql+psycopg://user:pass@host:5432/db  -> pgvector backend
    # sqlite:///./data/app.db                      -> numpy brute-force backend
    database_url: str = "sqlite:///./data/cenp.db"
    sql_echo: bool = False

    # -------------------------------------------------------------- workers
    redis_url: str | None = None
    celery_task_always_eager: bool = True  # run inline unless a broker is set

    # ------------------------------------------------------------------ llm
    # "auto" picks openai_compatible when an api key is present, else offline.
    llm_provider: Literal["auto", "openai_compatible", "offline"] = "auto"
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_api_key: str | None = None
    llm_model: str = "llama-3.3-70b-versatile"
    llm_temperature: float = 0.0
    llm_max_output_tokens: int = 2048
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 3

    # ----------------------------------------------------------- embeddings
    # "hashing" is a deterministic, dependency-free local embedder so the whole
    # retrieval stack works offline and in CI.  "openai_compatible" swaps in a
    # real model without touching any call site.
    embedding_provider: Literal["hashing", "openai_compatible"] = "hashing"
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 384

    # ------------------------------------------------------------ retrieval
    chunk_target_tokens: int = 220
    chunk_overlap_tokens: int = 40
    retrieval_top_k_bm25: int = 30
    retrieval_top_k_vector: int = 30
    retrieval_rrf_k: int = 60
    rerank_top_n: int = 8
    rerank_enabled: bool = True

    # ----------------------------------------------------------- extraction
    # A field is only emitted when its calibrated confidence clears this bar and
    # its quote can be matched verbatim in the source.  Otherwise we abstain.
    abstain_threshold: float = 0.45
    grounding_min_similarity: float = 0.82
    #: Chunks retrieved per individual field.
    per_field_evidence_chunks: int = 3
    #: Size of the union evidence window shown to the model in one prompt.
    max_evidence_chunks: int = 14

    # -------------------------------------------------------- external apis
    pubmed_api_key: str | None = None
    contact_email: str = "research@example.org"
    http_timeout_seconds: float = 20.0
    external_search_enabled: bool = True

    # -------------------------------------------------------- observability
    otel_enabled: bool = False
    otel_exporter_otlp_endpoint: str | None = None
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str = "https://cloud.langfuse.com"

    # ---------------------------------------------------------- validators
    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value):
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("["):
                return json.loads(text)
            return [item.strip() for item in text.split(",") if item.strip()]
        return value

    # ----------------------------------------------------------- helpers
    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgres")

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def resolved_llm_provider(self) -> str:
        if self.llm_provider != "auto":
            return self.llm_provider
        return "openai_compatible" if self.llm_api_key else "offline"

    def check_production_safety(self) -> None:
        """Fail fast rather than silently shipping dev defaults."""
        if self.environment in ("staging", "production"):
            if self.jwt_secret == Settings.model_fields["jwt_secret"].default:
                raise RuntimeError(
                    "JWT_SECRET is still the development default; refusing to start."
                )
            if self.debug:
                raise RuntimeError("DEBUG must be false outside local/ci.")


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
