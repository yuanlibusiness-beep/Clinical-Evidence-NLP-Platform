/**
 * Types mirroring the FastAPI response models.
 *
 * These are written by hand rather than generated, and the pairing is checked by
 * `npm run typecheck` against the code that consumes them. If you change a
 * Pydantic schema in `backend/app/schemas.py`, change it here in the same
 * commit — the two files are one contract in two languages.
 */

export interface User {
  id: string;
  email: string;
  full_name: string | null;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in_minutes: number;
  user: User;
}

export interface Section {
  id: string;
  name: string;
  heading: string | null;
  order_index: number;
  char_start: number;
  char_end: number;
}

export interface DocumentSummary {
  id: string;
  title: string;
  authors: string | null;
  journal: string | null;
  year: number | null;
  doi: string | null;
  pmid: string | null;
  source_type: string;
  source_label: string | null;
  source_url: string | null;
  char_count: number;
  page_count: number;
  status: "pending" | "parsing" | "indexing" | "ready" | "failed";
  error: string | null;
  created_at: string;
}

export interface DocumentDetail extends DocumentSummary {
  raw_text: string;
  sections: Section[];
  n_chunks: number;
}

export interface RetrievedChunk {
  chunk_id: string;
  order_index: number;
  section_name: string;
  text: string;
  char_start: number;
  char_end: number;
  page_no: number | null;
  bm25_score: number;
  vector_score: number;
  fused_score: number;
  rerank_score: number | null;
  rank: number;
}

export interface RetrieveResponse {
  query: string;
  document_id: string;
  results: RetrievedChunk[];
  took_ms: number;
}

/** One atomic claim: value, the sentence backing it, and a confidence. */
export interface ExtractedField {
  value: string | null;
  quote: string | null;
  confidence: number;
}

export interface Outcome {
  name: string;
  kind: "primary" | "secondary" | "safety";
  measure: string | null;
  effect_size: string | null;
  confidence_interval: string | null;
  p_value: string | null;
  direction: "favours_intervention" | "favours_comparison" | "no_difference" | null;
  quote: string | null;
  confidence: number;
}

export interface EvidenceReview {
  pico: Record<"population" | "intervention" | "comparison" | "outcome", ExtractedField>;
  design: Record<
    "design" | "randomised" | "blinding" | "setting" | "duration" | "registration_id",
    ExtractedField
  >;
  population: Record<
    | "sample_size"
    | "age"
    | "sex_distribution"
    | "inclusion_criteria"
    | "exclusion_criteria",
    ExtractedField
  >;
  outcomes: Outcome[];
  limitations: ExtractedField;
  conclusion: ExtractedField;
  funding: ExtractedField;
  _meta?: {
    prompt_version?: string;
    engine?: string;
    model?: string;
    rule_sources?: Record<string, string>;
    notes?: string[];
    calibrated?: boolean;
  };
}

export interface EvidenceSpan {
  field_path: string;
  quote: string;
  section_name: string;
  char_start: number;
  char_end: number;
  page_no: number | null;
  match_score: number;
  chunk_id: string | null;
}

export interface Extraction {
  id: string;
  document_id: string;
  provider: string;
  model: string;
  status: "pending" | "running" | "completed" | "failed";
  error: string | null;
  payload: EvidenceReview | null;
  confidence: Record<string, number> | null;
  abstentions: Record<string, string> | null;
  grounded_field_ratio: number;
  latency_ms: number;
  created_at: string;
  spans: EvidenceSpan[];
}

export interface LiteratureHit {
  source: string;
  external_id: string;
  title: string;
  abstract: string | null;
  authors: string | null;
  journal: string | null;
  year: number | null;
  doi: string | null;
  url: string | null;
}

export interface LiteratureSearchResponse {
  query: string;
  total: number;
  hits: LiteratureHit[];
  errors: Record<string, string>;
}

export interface EvalRun {
  id: string;
  name: string;
  provider: string;
  model: string;
  dataset: string;
  n_cases: number;
  created_at: string;
  metrics: {
    extraction: Record<string, number>;
    retrieval: Record<string, number>;
    outcomes: Record<string, number>;
    calibration: {
      ece: number;
      brier: number;
      n_samples: number;
      scaler_fitted: boolean;
      bins: { bin_low: number; bin_high: number; count: number; confidence: number; accuracy: number }[];
    };
    runtime: Record<string, number | boolean>;
  } | null;
  per_case: Record<string, unknown>[] | null;
}

export interface PublicConfig {
  version: string;
  prompt_version: string;
  llm_provider: string;
  llm_model: string;
  embedding_provider: string;
  abstain_threshold: number;
  grounding_min_similarity: number;
  confidence_calibrated: boolean;
  calibration_samples: number;
  external_search_enabled: boolean;
  max_evidence_chunks: number;
}
