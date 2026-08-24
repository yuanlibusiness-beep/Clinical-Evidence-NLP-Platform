# Design decisions

Each entry states the decision, the alternative that was rejected, and the reason. Where a
decision has a real cost, the cost is written down.

---

## 1. Abstention is representable in the schema

**Decision.** `ExtractedField.value` is nullable, `null` is documented in the prompt as a
*correct* answer, and the validator maps "N/A", "not reported", "unknown" and friends onto
`null`.

**Rejected.** Asking the model in prose not to guess, and post-filtering strings that look
like non-answers.

**Why.** A model forced to choose between inventing a sample size and violating the schema
will invent one. Giving "the paper does not say" a legal encoding removes the pressure. The
post-filter is still there, because models write "N/A" instead of emitting `null` no matter
how the schema is phrased — but it is the second line, not the first.

**Cost.** Recall drops. The evaluation harness therefore reports `missed_rate` next to
`hallucination_rate` so the trade is visible rather than hidden behind a single F1.

---

## 2. Grounding is enforced, not requested

**Decision.** Every answered field must carry a quote that can be located in the source.
Anything that cannot be matched is discarded and recorded as `ungrounded`.

**Rejected.** Showing the model's quote next to the value and trusting it.

**Why.** An unverified quote is worse than no quote: it *looks* like provenance, so a reader
stops checking. Verification is cheap — a normalised index over the document plus a bounded
fuzzy match — and it converts a stylistic instruction into a structural guarantee.

**Cost.** A correct extraction whose quote was lightly paraphrased is thrown away. That is
the right direction to fail in, and the three-tier matcher (exact → normalised → fuzzy)
exists to keep the loss small.

---

## 3. Three-tier quote matching, not one

**Decision.** Exact substring (1.00) → unicode/whitespace-normalised substring (0.98) →
`SequenceMatcher` over candidate sentences above 0.82 (returning the *source* sentence).

**Rejected.** Strict `in` matching, or a single fuzzy threshold.

**Why.** Model quotes are *nearly* verbatim: a unicode dash becomes a hyphen, a soft hyphen
the PDF inserted mid-word disappears, a double space collapses. Strict matching rejects all
of those and abstains on correct work. A single loose threshold accepts paraphrases and
defeats the point. The tiers separate "same sentence, different bytes" from "different
sentence".

The fuzzy tier always returns the matched **source** sentence, never the model's wording, so
what the UI displays is what the paper says.

---

## 4. Hybrid retrieval fused by rank, not by score

**Decision.** BM25 and dense retrieval run independently; results are fused with Reciprocal
Rank Fusion (`k = 60`).

**Rejected.** Min-max or z-score normalisation and a weighted sum.

**Why.** BM25 scores are unbounded and corpus-dependent; cosine similarities sit in [-1, 1].
Normalising makes the blend depend on the score *distribution* of whichever query was asked,
which is unstable on a corpus of a few hundred chunks. RRF throws magnitudes away and fuses
on rank, so a chunk ranked well by both retrievers beats one ranked first by only one.

**Cost.** Genuine confidence information in the scores is discarded. Acceptable, because
reranking re-introduces a calibrated ordering over the shortlist.

---

## 5. Per-field retrieval, not one query for the paper

**Decision.** Eighteen targeted queries — one per field — each returning three chunks, unioned
into a single evidence window capped at fourteen chunks in document order.

**Rejected.** One pooled query, or the whole paper in the prompt.

**Why.** "Sample size" and "limitations" live in different sections and share almost no
vocabulary; a pooled query retrieves chunks that are mediocre for both. The queries are
written as clinical-paper *phrasing* rather than as questions ("patients were randomly
assigned", not "was this randomised?") because BM25 matches surface form.

The window is ordered by position in the document, so the model reads Methods before Results
— the order a person would.

**Cost.** Eighteen retrievals per extraction. Against an in-memory BM25 index and a local
vector search, that is milliseconds.

---

## 6. Confidence is calibrated, and says when it is not

**Decision.** Two stages. Stage one blends self-reported confidence (weight 0.30, shrunk
toward 0.5), grounding score (0.34), retrieval rank (0.18), section prior (0.10) and rule
agreement (0.08). Stage two applies a Platt scaler fitted from labelled evaluation outcomes,
if one has been fitted.

**Rejected.** Using the model's self-reported confidence directly.

**Why.** A language model's stated confidence is fluent and systematically too high — useless
as a threshold on its own. Grounding score carries the most weight because a verbatim match
is the strongest single predictor of correctness available without labels.

The stage-one weights are **hand-set priors, not fitted**, and the code says so. Without a
fitted scaler the raw score is returned unchanged and `/config` reports
`confidence_calibrated: false`, so the system is honest about being uncalibrated until it
has been calibrated.

**Cost.** Calibration needs labelled data. Below ~30 labelled fields the fit would be noise,
so `fit_platt` refuses rather than overfitting.

---

## 7. A deterministic engine beside the LLM

**Decision.** `RuleEngine` fills the same schema with regex and cue-phrase extractors. It is
the default when no API key is set, the baseline the LLM is measured against, and a backfill
for high-precision fields the LLM abstains on (registration IDs, sample sizes, blinding).

**Rejected.** Requiring an API key, or mocking the LLM in tests.

**Why.** Three payoffs. The repository runs end to end on a fresh clone. "The model scores
0.71 F1" is meaningless without a floor, and the gap between the two engines is the actual
value the LLM adds. And on fields with a canonical surface form, a regex genuinely beats
generation — `NCT\d{8}` has no ambiguity for a model to resolve.

**Cost.** A second extraction path to maintain, and the risk of tuning the rules to the
evaluation set — which is exactly what happened here, and is disclosed in the README.

---

## 8. Two database backends behind one ORM

**Decision.** PostgreSQL + pgvector in production, SQLite + NumPy for development and CI,
with the difference confined to one `TypeDecorator` and one search function.

**Rejected.** Requiring Postgres, or using SQLite everywhere.

**Why.** Requiring a database to run the tests means the tests get skipped. Using SQLite
everywhere means the production path is never exercised by the same code. Isolating the
difference in two files keeps both honest — and forces the vector-store interface to stay
clean, because it has to serve two implementations.

**Cost.** The SQLite path is brute-force and would not scale past a few thousand chunks per
document. That is fine for what it is for.

---

## 9. Bearer tokens in `localStorage`

**Decision.** JWT in `localStorage`, attached per request.

**Rejected.** httpOnly cookies with CSRF tokens.

**Why.** The frontend and backend are separate origins; cookie auth across them needs
`SameSite=None`, CSRF tokens, and a shared-domain deployment. For a research tool, the
bearer model is simpler and its failure mode is easier to reason about.

**Cost.** A token in `localStorage` is readable by any script that gets injected into the
page. This is written down in `components/AuthProvider.tsx` rather than left implicit: a
clinical deployment should move to httpOnly cookies plus CSRF.

---

## 10. Evaluation runs the whole pipeline

**Decision.** The harness ingests each gold case through the real ingestion path and runs
the real retriever and the real engine.

**Rejected.** Calling the engine directly with pre-selected evidence.

**Why.** A harness that stubs retrieval measures the prompt. This one measures the product,
so a regression in the chunker or the fusion weights shows up as a drop in F1 where it
belongs. It runs in CI on every push with structural gates: hallucination rate ≤ 0.05,
grounded ratio = 1.0, recall@3 ≥ 0.70.

**Cost.** Slower, and the numbers move for reasons outside the extractor. That is the point.

---

## 11. The retrieval inspector ships in the product

**Decision.** `POST /documents/{id}/retrieve` and a UI panel exposing BM25, vector, fused and
rerank scores side by side.

**Rejected.** Keeping it in a notebook.

**Why.** When an extraction is wrong the first question is always "did the right chunk even
reach the model?" A high BM25 score with a low vector score means the wording matched but
the meaning did not; the reverse means the retriever drifted off a rare term. That
distinction is the difference between fixing the query and fixing the chunker, and it should
not require a local checkout to answer.

---

## 12. The synthetic dataset announces itself

**Decision.** `gold_v1.json` carries a `synthetic: true` flag and a `notice` field, the API
returns both, and the evaluation page renders the notice above the metrics.

**Why.** A precision figure means nothing without knowing what it was measured on, and a
number in a UI acquires authority it has not earned. Four invented fixtures cannot support a
claim about clinical extraction quality, so the interface says so at the point where someone
would otherwise read the number and believe it.
