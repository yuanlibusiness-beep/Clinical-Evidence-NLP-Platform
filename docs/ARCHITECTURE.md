# Architecture

## System

```mermaid
flowchart TB
  subgraph client["Browser"]
    UI["Next.js 14 App Router<br/>evidence table · source reader · retrieval inspector"]
  end

  subgraph api["FastAPI"]
    AUTH["JWT auth<br/>bcrypt + PyJWT"]
    ING["Ingestion<br/>PDF · text · academic APIs"]
    RET["Hybrid retrieval<br/>BM25 + vectors + RRF + rerank"]
    EXT["Extraction pipeline<br/>schema · grounding · calibration"]
    EVAL["Evaluation harness"]
  end

  subgraph engines["Extraction engines"]
    LLM["LLM engine<br/>OpenAI-compatible, JSON mode"]
    RULE["Rule engine<br/>deterministic, offline"]
  end

  subgraph infra["Storage & workers"]
    DB[("PostgreSQL + pgvector<br/>(or SQLite + NumPy)")]
    REDIS[("Redis")]
    CELERY["Celery worker"]
  end

  EXTAPI["PubMed · Europe PMC · Crossref"]

  UI -->|"bearer token"| AUTH
  UI --> ING & RET & EXT & EVAL
  ING --> EXTAPI
  ING --> DB
  RET --> DB
  EXT --> RET
  EXT --> LLM
  EXT --> RULE
  LLM -.->|"abstains → backfill"| RULE
  EXT --> DB
  EVAL --> EXT
  EXT -.->|"async"| REDIS --> CELERY --> DB
```

## The extraction path, in order

```mermaid
sequenceDiagram
  autonumber
  participant U as User
  participant P as ExtractionPipeline
  participant R as HybridRetriever
  participant E as Engine
  participant G as Grounder
  participant C as Calibrator

  U->>P: POST /documents/{id}/extract
  loop 18 fields
    P->>R: targeted query for this field
    R-->>P: top-3 chunks
  end
  P->>P: union → evidence window (≤14 chunks, document order)
  P->>E: schema + window
  E-->>P: EvidenceReview (values + quotes + self-confidence)
  loop every answered field
    P->>G: does this quote exist in the source?
    alt matched
      G-->>P: offsets + match score
      P->>C: self-report + grounding + retrieval + section prior
      C-->>P: calibrated confidence
      alt below threshold
        P->>P: withhold, reason = low_confidence
      else
        P->>P: keep, store EvidenceSpan
      end
    else not matched
      G-->>P: none
      P->>P: withhold, reason = ungrounded
    end
  end
  P-->>U: evidence table + spans + abstentions
```

## Data model

```mermaid
erDiagram
  USER      ||--o{ DOCUMENT   : owns
  DOCUMENT  ||--o{ SECTION    : "split into"
  DOCUMENT  ||--o{ CHUNK      : "indexed as"
  SECTION   ||--o{ CHUNK      : contains
  DOCUMENT  ||--o{ EXTRACTION : "reviewed by"
  EXTRACTION ||--o{ EVIDENCE_SPAN : cites
  CHUNK     ||--o{ EVIDENCE_SPAN : "sourced from"

  DOCUMENT {
    string id PK
    text   raw_text "immutable once written"
    string status
  }
  CHUNK {
    string  id PK
    int     char_start "offset into raw_text"
    int     char_end
    string  section_name
    vector  embedding
  }
  EXTRACTION {
    string id PK
    json   payload "validated EvidenceReview"
    json   confidence "per field"
    json   abstentions "per field, with reason"
    float  grounded_field_ratio
  }
  EVIDENCE_SPAN {
    string id PK
    string field_path "pico.population, outcomes[0], …"
    text   quote "source text, not the model's wording"
    int    char_start
    int    char_end
    float  match_score
  }
```

**`raw_text` is written once and never mutated.** Every section, chunk and evidence span
addresses it by character offset, so editing it in place would silently invalidate every
stored citation while leaving them all looking valid. Re-ingesting creates a new document.

## Two backends, one ORM

The only genuinely database-specific thing in the project is the embedding column, and that
difference is confined to one `TypeDecorator` (`app/db_types.py`) plus one search function
(`app/retrieval/vector_store.py`):

| | PostgreSQL | SQLite |
|---|---|---|
| Column | `vector(N)` (pgvector) | packed `float32` blob |
| Search | `<=>` cosine distance, in the database | NumPy matrix multiply |
| Scales to | large corpora, with an ivfflat/hnsw index | hundreds of chunks per document |
| Used for | Docker, deployment | development, CI, `git clone && pytest` |

Both hand Python the same `numpy.ndarray`, so no call site knows which is active.

## Abstention: every way a field can be withheld

| Reason | Meaning |
|---|---|
| `not_reported` | The engine returned `null` — the paper does not state it. |
| `no_quote` | A value with no supporting quote. Cannot be verified, so it is dropped. |
| `ungrounded` | The quote could not be matched in the source. **This is the hallucination catch.** |
| `low_confidence(0.31)` | Grounded, but the calibrated score is below `ABSTAIN_THRESHOLD`. |

All four are returned to the client in `abstentions`, so "why is sample size blank?" is
always answerable.

## Request lifecycle

1. `X-Request-ID` is assigned (or taken from the header) by middleware and echoed on the
   response, so a user-reported error can be found in the logs.
2. `get_current_user` is the only place a token becomes an identity;
   `get_owned_document` is the only place a document is loaded by id. Single-sourcing both
   is what makes the ownership guarantee auditable — no route can accidentally read another
   user's document, because no route loads documents any other way.
3. A document owned by someone else returns **404, not 403**. A 403 would confirm the id
   exists.
4. Unhandled exceptions return JSON with the request id, and the exception text only outside
   staging/production — exception messages are where connection strings end up.

## Deployment shape

`docker compose up --build` starts Postgres+pgvector, Redis, the API, a Celery worker and
the frontend. The API and the worker share one image and one codebase and differ only in
their command, which is what makes "works in the API but not in the worker" impossible.

The frontend image uses Next's `standalone` output, so the runner stage carries only the
traced server bundle rather than `node_modules`. `NEXT_PUBLIC_API_URL` is inlined at build
time, so it is a build argument rather than a runtime variable.
