# Clinical Evidence NLP Platform

Turns a clinical paper into a structured evidence table where **every field carries the
verbatim sentence it came from — and stays blank when the paper does not say.**

```
PDF · pasted text · PubMed/Europe PMC/Crossref
        │
        ▼
 section-aware parsing        IMRaD detection, sentence-aligned chunking
        │
        ▼
 hybrid retrieval             BM25 + dense vectors → RRF fusion → rerank
        │
        ▼
 schema-constrained extraction    LLM under a Pydantic contract, or a rule-based engine
        │
        ▼
 grounding                    every quote matched back to the source, or dropped
        │
        ▼
 calibration + abstain        below threshold → withheld, with a reason
        │
        ▼
 evidence table + citation-level provenance
```

Two properties separate this from a "summarise my PDF" demo:

1. **Nothing is shown that cannot be traced.** Each extracted value is stored with the
   character offsets of the sentence supporting it. If the quote cannot be matched in the
   source, the field is discarded — not softened, not flagged, discarded.
2. **Abstention is a first-class answer.** "Not reported" is a valid, encodable output. The
   evaluation harness measures the two error types separately, because a fabricated sample
   size in a systematic review costs a reviewer far more than a blank cell.

---

## Run it in two minutes

**No API key is needed.** With no key the extractor runs a deterministic rule-based engine,
so the whole pipeline — ingestion, retrieval, extraction, grounding, evaluation — works on a
fresh clone.

```bash
git clone https://github.com/<your-username>/clinical-evidence-nlp-platform.git
cd clinical-evidence-nlp-platform
cp .env.example .env

# terminal 1 — API on :8000
cd backend
pip install -r requirements-dev.txt
uvicorn app.main:app --reload

# terminal 2 — UI on :3000
cd frontend
npm install
npm run dev
```

Open <http://localhost:3000>, create an account, paste an abstract, press **Extract evidence**.

Or the whole stack (Postgres + pgvector, Redis, API, Celery worker, Next.js):

```bash
docker compose up --build
```

To switch the extractor onto a language model, set two variables in `.env` — nothing else
changes:

```bash
LLM_API_KEY=sk-...
LLM_BASE_URL=https://api.groq.com/openai/v1     # or OpenAI, DeepSeek, a local vLLM …
```

---

## How the pieces fit

| Stage | Module | What it does and why it exists |
|---|---|---|
| Parsing | `backend/app/ingest/pdf.py` | PyMuPDF with block-level reading order, so two-column papers do not interleave. Builds a `page_map` so a span can be reported as "page 7". |
| Sectioning | `backend/app/ingest/sectioniser.py` | Conservative IMRaD detection. Section is used as a prior everywhere downstream: a sample size belongs in Methods, a p-value in Results. |
| Chunking | `backend/app/ingest/chunker.py` | Sentence-aligned, section-bounded, overlapping windows. Chunk text is sliced from the source so `raw_text[start:end] == chunk.text` holds exactly. |
| Retrieval | `backend/app/retrieval/` | BM25 (lexical precision) + dense vectors (semantic recall), fused by Reciprocal Rank Fusion, then reranked. |
| Extraction | `backend/app/extraction/` | One Pydantic schema constrains the output. Per-field targeted retrieval builds the evidence window. |
| Grounding | `backend/app/extraction/grounding.py` | Three tiers — exact, unicode/whitespace-normalised, then bounded fuzzy — returning offsets into the source. |
| Calibration | `backend/app/extraction/calibration.py` | Blends self-reported confidence, grounding score, retrieval rank and section prior; optional fitted Platt scaler. |
| Evaluation | `backend/app/evaluation/` | Runs the full pipeline over an annotated set and reports extraction, retrieval, grounding and calibration metrics. |

Architecture in more depth: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).
Design decisions and the arguments for them: [`docs/DESIGN_DECISIONS.md`](docs/DESIGN_DECISIONS.md).

---

## Why hybrid retrieval, and why reranking

BM25 alone misses "adverse events" when the paper writes "safety outcomes". Dense retrieval
alone drifts on rare tokens — ask about 81 mg and it will happily return a chunk about *a*
dose. Fusion keeps both. RRF fuses on **rank**, not score, because BM25 scores and cosine
similarities live on incompatible scales and normalising them makes the blend depend on the
score distribution of whichever query was asked.

Fusion optimises recall over ~60 candidates; the extractor can only read about 8. Reranking
is the step that chooses which 8, and it can afford to be expensive because it sees so few.

---

## Quality: what is measured, and what the numbers mean

```bash
cd backend
python -m app.evaluation.runner --rule-engine     # the offline baseline
python -m app.evaluation.runner                   # whatever is configured now
python -m app.evaluation.runner --fit-calibration # fit the confidence scaler
```

```
 EXTRACTION
   precision            1.000
   recall               0.923
   F1                   0.958
   coverage             0.611
   hallucination rate   0.000   (lower is better)
   missed rate          0.077
 GROUNDING
   grounded ratio       1.000
   mean match score     1.000
 RETRIEVAL
   recall@3             1.000
   nDCG@3               0.982
 CALIBRATION
   ECE                  0.225   (lower is better)
```

### Read those numbers with the following caveats

They are **not** a claim about performance on real literature, and the repository should not
be read as making one:

- **The bundled gold set is synthetic and tiny.** Four fixtures, written for this repository.
  Invented studies, invented drugs, invented numbers. `backend/app/evaluation/datasets/gold_v1.json`
  says so in its own `notice` field, and the UI shows that notice on the evaluation page.
- **The rule engine was developed against these four cases.** That is textbook overfitting.
  A precision of 1.000 on a set the rules were tuned on is a statement about the rules
  matching the fixtures, not about clinical extraction quality. Treat the baseline as a
  *regression guard* — it catches the day retrieval or chunking breaks — not as a benchmark.
- **The honest numbers here are the structural ones.** `grounded_ratio = 1.0` and
  `mean_match_score = 1.0` hold by construction rather than by tuning: an ungrounded field
  cannot reach the output. Those are properties of the design, and they are the ones the CI
  gate enforces.
- **ECE 0.225 is a real weakness, shown rather than hidden.** The system is *under*-confident:
  it states ~0.78 on fields it gets right. `--fit-calibration` fixes it on data it has seen;
  reporting a fitted ECE on the same run would be training error, so the default run does
  not do that.

To evaluate against real papers, replace `gold_v1.json` with your own annotations over
literature you have the right to use. The schema is documented in `backend/app/evaluation/runner.py`.

CI enforces the structural gates on every push: hallucination rate ≤ 0.05, grounded ratio
= 1.0, retrieval recall@3 ≥ 0.70.

---

## Configuration that matters

| Variable | Default | Effect |
|---|---|---|
| `LLM_API_KEY` | *(empty)* | Empty → deterministic rule engine. Set → schema-constrained generation. |
| `LLM_BASE_URL` | Groq | Any OpenAI-compatible endpoint: OpenAI, DeepSeek, Together, vLLM, Ollama. |
| `DATABASE_URL` | SQLite | `postgresql+psycopg://…` switches vector search to pgvector's `<=>` operator. |
| `EMBEDDING_PROVIDER` | `hashing` | Deterministic local embedder (no download). `openai_compatible` swaps in a real model — re-index after changing. |
| `ABSTAIN_THRESHOLD` | `0.45` | Calibrated confidence below this → the field is withheld. |
| `GROUNDING_MIN_SIMILARITY` | `0.82` | Fuzzy-match floor for accepting a quote. |
| `REDIS_URL` | *(empty)* | Empty → Celery runs inline. Set → real queueing. |

Full list with commentary: [`.env.example`](.env.example).

### About the default embedder

`hashing` is a signed feature-hashing projection of word unigrams and bigrams with
sub-linear term weighting — TF-IDF-shaped semantics in a fixed-width dense vector. It
captures lexical and light morphological similarity, **not paraphrase**. It is the default
because it makes `git clone && pytest` exercise the real retrieval path with no downloads
and no keys, and because BM25 carries lexical precision on that path. For production
retrieval quality, set `EMBEDDING_PROVIDER=openai_compatible` (and `EMBEDDING_DIM` to the
model's real dimension) and re-index.

---

## Development

```bash
make setup          # install everything, create .env
make test           # pytest
make lint           # ruff
make typecheck      # tsc --noEmit on the frontend
make eval-baseline  # the rule-based floor
make up             # full stack in Docker
```

The API documents itself at <http://localhost:8000/docs>.

Test suite: 92 tests over text handling, retrieval, grounding, calibration, and the HTTP
API — including ownership tests (user A must not be able to read user B's document) and a
round trip through a real generated PDF.

---

## Provenance and scope

This is an independent full-stack rebuild. A seven-person student project I contributed to
(≈half the React/TypeScript frontend, plus the original NLP pipeline) established the
problem framing: turn medical papers into structured PICO output. **No code is carried over.**
The architecture here is different in every layer that matters — section-aware parsing
instead of whole-document prompting, hybrid retrieval with fusion and reranking instead of
a single API call, a schema-constrained engine with a rule-based fallback instead of one
provider, enforced grounding and abstention instead of confidence theatre, and an evaluation
harness instead of spot checks.

**Not a medical device.** Research tooling. Extractions are automated and must be verified
against the source before use in a review or any clinical decision. The bundled dataset is
synthetic and contains no real clinical findings.

## Licence

MIT — see [LICENSE](LICENSE).
