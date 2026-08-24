"use client";

/**
 * A window into the retrieval stack.
 *
 * Shipping this in the product, rather than keeping it in a notebook, is a
 * deliberate choice: when an extraction is wrong, the first question is always
 * "did the right chunk even reach the model?" — and the four scores side by side
 * answer it. A high BM25 score with a low vector score means the wording matched
 * but the meaning did not; the reverse means the retriever drifted off a rare
 * term. That distinction is the difference between fixing the query and fixing
 * the chunker.
 */

import { useState } from "react";

import { api, ApiError } from "@/lib/api";
import { truncate } from "@/lib/format";
import type { RetrievedChunk } from "@/lib/types";

const EXAMPLES = [
  "how many patients were randomised",
  "primary outcome hazard ratio 95% CI",
  "inclusion and exclusion criteria",
  "limitations of the study",
];

export function RetrievalDebugger({ documentId }: { documentId: string }) {
  const [query, setQuery] = useState("");
  const [rerank, setRerank] = useState(true);
  const [results, setResults] = useState<RetrievedChunk[] | null>(null);
  const [tookMs, setTookMs] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(value: string) {
    if (value.trim().length < 2) return;
    setBusy(true);
    setError(null);
    try {
      const response = await api.retrieve(documentId, value, 8, rerank);
      setResults(response.results);
      setTookMs(response.took_ms);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Retrieval failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <div className="card-header">
        <h3 className="text-sm font-semibold text-ink-900">Retrieval inspector</h3>
        {tookMs !== null && <p className="text-[11px] text-ink-400">{tookMs} ms</p>}
      </div>

      <div className="space-y-3 px-5 py-4">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void run(query);
          }}
          className="flex gap-2"
        >
          <input
            className="input"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Ask the retriever something…"
          />
          <button type="submit" disabled={busy} className="btn-secondary shrink-0">
            {busy ? "…" : "Retrieve"}
          </button>
        </form>

        <div className="flex flex-wrap items-center gap-2">
          {EXAMPLES.map((example) => (
            <button
              key={example}
              onClick={() => {
                setQuery(example);
                void run(example);
              }}
              className="rounded-full border border-ink-200 px-2.5 py-1 text-[11px] text-ink-500 hover:bg-ink-100"
            >
              {example}
            </button>
          ))}
          <label className="ml-auto flex items-center gap-1.5 text-[11px] text-ink-500">
            <input
              type="checkbox"
              checked={rerank}
              onChange={(event) => setRerank(event.target.checked)}
            />
            rerank
          </label>
        </div>

        {error && <p className="text-sm text-red-700">{error}</p>}

        {results && results.length === 0 && (
          <p className="text-sm text-ink-400">Nothing matched.</p>
        )}

        {results && results.length > 0 && (
          <ol className="space-y-2">
            {results.map((chunk) => (
              <li key={chunk.chunk_id} className="rounded-lg border border-ink-200 p-3">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-ink-400">
                  <span className="font-medium text-ink-600">#{chunk.rank}</span>
                  <span className="chip-abstained">{chunk.section_name}</span>
                  {chunk.page_no && <span>p. {chunk.page_no}</span>}
                  <span>bm25 {chunk.bm25_score.toFixed(2)}</span>
                  <span>vector {chunk.vector_score.toFixed(3)}</span>
                  <span>fused {chunk.fused_score.toFixed(4)}</span>
                  {chunk.rerank_score !== null && (
                    <span className="font-medium text-accent">
                      rerank {chunk.rerank_score.toFixed(3)}
                    </span>
                  )}
                </div>
                <p className="mt-2 text-[13px] leading-relaxed text-ink-700">
                  {truncate(chunk.text, 320)}
                </p>
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}
