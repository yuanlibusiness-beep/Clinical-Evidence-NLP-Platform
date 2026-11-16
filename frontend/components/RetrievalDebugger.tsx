"use client";

/**
 * A window into the retrieval stack.
 *
 * Shipping this in the product, rather than keeping it in a notebook, is a
 * deliberate choice: when an extraction is wrong, the first question is always
 * "did the right chunk even reach the model?" — and the scores side by side
 * answer it. A high BM25 score with a low vector score means the wording matched
 * but the meaning did not; the reverse means the retriever drifted off a rare
 * term. That distinction is the difference between fixing the query and fixing
 * the chunker.
 */

import { useState } from "react";

import { SearchIcon } from "@/components/Icons";
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

  const topFused = results?.reduce((max, chunk) => Math.max(max, chunk.fused_score), 0) || 1;

  return (
    <div className="space-y-4 px-1.5 pt-1">
      <p className="text-[13px] leading-relaxed text-ink-500">
        Ask the retriever what the extractor would see. BM25 catches wording, vectors catch meaning,
        reciprocal-rank fusion combines them.
      </p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void run(query);
        }}
        className="flex gap-2 rounded-2xl bg-[#F4F6FA] p-1.5"
      >
        <label className="flex flex-1 items-center gap-2 pl-2.5">
          <SearchIcon size={16} className="shrink-0 text-ink-500" />
          <span className="sr-only">Retrieval query</span>
          <input
            className="h-10 w-full border-0 bg-transparent text-sm placeholder:text-ink-400 focus:outline-none"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Ask the retriever something…"
          />
        </label>
        <button type="submit" disabled={busy} className="btn-primary h-10 rounded-xl px-4">
          {busy ? "…" : "Retrieve"}
        </button>
      </form>

      <div className="flex flex-wrap items-center gap-2">
        {EXAMPLES.map((example) => (
          <button
            key={example}
            type="button"
            onClick={() => {
              setQuery(example);
              void run(example);
            }}
            className="rounded-full bg-white px-3 py-1.5 text-xs text-ink-600 shadow-[0_0_0_1px_#E4E7EE] transition-colors hover:bg-ink-100 hover:text-ink-900"
          >
            {example}
          </button>
        ))}
        <label className="ml-auto flex cursor-pointer items-center gap-2 text-xs font-medium text-ink-600">
          <input
            type="checkbox"
            checked={rerank}
            onChange={(event) => setRerank(event.target.checked)}
            className="h-4 w-4 accent-[#3554D1]"
          />
          Rerank
        </label>
      </div>

      {error && <p className="text-sm text-[#B42318]">{error}</p>}
      {results && results.length === 0 && <p className="text-sm text-ink-500">Nothing matched.</p>}

      {results && results.length > 0 && (
        <ol className="space-y-2">
          {tookMs !== null && (
            <li className="px-1 text-xs text-ink-500">
              {results.length} chunks in {tookMs} ms
            </li>
          )}
          {results.map((chunk, index) => (
            <li
              key={chunk.chunk_id}
              className="animate-rise rounded-2xl bg-[#F8F9FC] p-4"
              style={{ animationDelay: `${index * 50}ms` }}
            >
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[11.5px] text-ink-500">
                <span className="font-display text-sm font-bold text-ink-900">#{chunk.rank}</span>
                <span className="chip-outline">{chunk.section_name}</span>
                {chunk.page_no && <span>p. {chunk.page_no}</span>}
                <span>bm25 {chunk.bm25_score.toFixed(2)}</span>
                <span>vector {chunk.vector_score.toFixed(3)}</span>
                <span>fused {chunk.fused_score.toFixed(4)}</span>
                {chunk.rerank_score !== null && (
                  <span className="font-semibold text-accent">rerank {chunk.rerank_score.toFixed(3)}</span>
                )}
              </div>
              <span aria-hidden="true" className="mt-2 block h-1 overflow-hidden rounded-full bg-ink-150">
                <span
                  className="block h-full origin-left animate-grow rounded-full bg-accent"
                  style={{ width: `${(chunk.fused_score / topFused) * 100}%`, animationDelay: `${index * 50}ms` }}
                />
              </span>
              <p className="mt-2.5 text-[13.5px] leading-relaxed text-ink-700">{truncate(chunk.text, 320)}</p>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
