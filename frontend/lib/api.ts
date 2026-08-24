/**
 * The single place the frontend talks to the backend.
 *
 * Two rules make the rest of the app simple:
 *
 * 1. Every request goes through `request()`, so the bearer token, the JSON
 *    headers, and error handling are defined once. A 401 clears the stored
 *    session and redirects to /login rather than leaving the UI in a state where
 *    every panel shows its own auth error.
 * 2. Errors are thrown as `ApiError` carrying the backend's `detail` string.
 *    FastAPI puts a human-readable reason there ("Index incomplete: 3/8 chunks
 *    embedded"), and surfacing it beats a generic "something went wrong".
 */

import type {
  DocumentDetail,
  DocumentSummary,
  EvalRun,
  Extraction,
  LiteratureSearchResponse,
  PublicConfig,
  RetrieveResponse,
  TokenResponse,
  User,
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const PREFIX = "/api/v1";
const TOKEN_KEY = "cenp.token";
const USER_KEY = "cenp.user";

export class ApiError extends Error {
  status: number;
  requestId?: string;

  constructor(message: string, status: number, requestId?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.requestId = requestId;
  }
}

// ------------------------------------------------------------------ session
export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function getStoredUser(): User | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as User) : null;
  } catch {
    return null;
  }
}

export function storeSession(token: string, user: User): void {
  try {
    window.localStorage.setItem(TOKEN_KEY, token);
    window.localStorage.setItem(USER_KEY, JSON.stringify(user));
  } catch {
    /* private mode: the session simply does not survive a reload */
  }
}

export function clearSession(): void {
  try {
    window.localStorage.removeItem(TOKEN_KEY);
    window.localStorage.removeItem(USER_KEY);
  } catch {
    /* ignore */
  }
}

// ------------------------------------------------------------------ request
async function request<T>(
  path: string,
  options: RequestInit & { auth?: boolean; raw?: boolean } = {},
): Promise<T> {
  const { auth = true, raw = false, headers, ...rest } = options;

  const finalHeaders: Record<string, string> = {
    ...(raw ? {} : { "Content-Type": "application/json" }),
    ...((headers as Record<string, string>) ?? {}),
  };

  if (auth) {
    const token = getToken();
    if (token) finalHeaders.Authorization = `Bearer ${token}`;
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${PREFIX}${path}`, { ...rest, headers: finalHeaders });
  } catch (error) {
    throw new ApiError(
      `Cannot reach the API at ${API_BASE}. Is the backend running?`,
      0,
    );
  }

  if (response.status === 401 && auth) {
    clearSession();
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
      window.location.href = "/login";
    }
    throw new ApiError("Your session expired. Please sign in again.", 401);
  }

  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    let requestId: string | undefined;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") detail = body.detail;
      else if (Array.isArray(body?.errors) && body.errors.length) {
        detail = body.errors.map((e: { msg?: string }) => e.msg).filter(Boolean).join("; ");
      }
      requestId = body?.request_id;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(detail, response.status, requestId);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

// --------------------------------------------------------------------- api
export const api = {
  // system
  config: () => request<PublicConfig>("/config", { auth: false }),
  health: () => request<Record<string, string | number>>("/health", { auth: false }),

  // auth
  register: (email: string, password: string, fullName?: string) =>
    request<TokenResponse>("/auth/register", {
      auth: false,
      method: "POST",
      body: JSON.stringify({ email, password, full_name: fullName || null }),
    }),
  login: (email: string, password: string) =>
    request<TokenResponse>("/auth/login", {
      auth: false,
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  me: () => request<User>("/auth/me"),

  // documents
  listDocuments: () => request<DocumentSummary[]>("/documents"),
  getDocument: (id: string) => request<DocumentDetail>(`/documents/${id}`),
  deleteDocument: (id: string) => request<void>(`/documents/${id}`, { method: "DELETE" }),
  ingestText: (payload: { title: string; text: string; year?: number | null }) =>
    request<DocumentDetail>("/documents/text", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  uploadPdf: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<DocumentDetail>("/documents/upload", {
      method: "POST",
      body: form,
      raw: true,
    });
  },
  reindex: (id: string) => request<DocumentDetail>(`/documents/${id}/reindex`, { method: "POST" }),
  retrieve: (id: string, query: string, topK = 8, rerank = true) =>
    request<RetrieveResponse>(`/documents/${id}/retrieve`, {
      method: "POST",
      body: JSON.stringify({ query, top_k: topK, rerank }),
    }),

  // extraction
  extract: (id: string, force = false) =>
    request<Extraction>(`/documents/${id}/extract`, {
      method: "POST",
      body: JSON.stringify({ force, async_mode: false }),
    }),
  listExtractions: (id: string) => request<Extraction[]>(`/documents/${id}/extractions`),

  // literature
  searchLiterature: (query: string, sources: string[], limit = 10) =>
    request<LiteratureSearchResponse>("/literature/search", {
      method: "POST",
      body: JSON.stringify({ query, sources, limit }),
    }),
  importHit: (hit: unknown) =>
    request<DocumentSummary>("/literature/import", {
      method: "POST",
      body: JSON.stringify({ hit }),
    }),

  // evaluation
  listEvalRuns: () => request<EvalRun[]>("/eval/runs"),
  getEvalRun: (id: string) => request<EvalRun>(`/eval/runs/${id}`),
  runEval: (name: string, ruleEngine: boolean) =>
    request<EvalRun>(`/eval/run?rule_engine=${ruleEngine}`, {
      method: "POST",
      body: JSON.stringify({ name, dataset: "gold_v1" }),
    }),
  describeDataset: (name = "gold_v1") =>
    request<{ synthetic: boolean; notice: string; n_cases: number }>(`/eval/datasets/${name}`),
};

export { API_BASE };
