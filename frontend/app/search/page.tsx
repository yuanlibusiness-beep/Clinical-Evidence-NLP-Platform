"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { RequireAuth } from "@/components/AuthProvider";
import { ErrorBanner } from "@/components/ErrorBanner";
import { Shell } from "@/components/Shell";
import { api, ApiError } from "@/lib/api";
import { truncate } from "@/lib/format";
import type { LiteratureHit } from "@/lib/types";

const SOURCES = [
  { name: "pubmed", label: "PubMed" },
  { name: "europepmc", label: "Europe PMC" },
  { name: "crossref", label: "Crossref" },
];

export default function SearchPage() {
  return (
    <RequireAuth>
      <Shell>
        <Search />
      </Shell>
    </RequireAuth>
  );
}

function Search() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string[]>(["pubmed", "europepmc"]);
  const [hits, setHits] = useState<LiteratureHit[] | null>(null);
  const [sourceErrors, setSourceErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [importing, setImporting] = useState<string | null>(null);

  async function run(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const response = await api.searchLiterature(query, selected, 12);
      setHits(response.hits);
      setSourceErrors(response.errors);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Search failed.");
    } finally {
      setBusy(false);
    }
  }

  async function importHit(hit: LiteratureHit) {
    setImporting(hit.external_id);
    setError(null);
    try {
      const document = await api.importHit(hit);
      router.push(`/documents/${document.id}`);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Import failed.");
    } finally {
      setImporting(null);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-semibold tracking-tight text-ink-900">Literature search</h1>
        <p className="mt-1 text-sm text-ink-500">
          Queries every selected database at once and merges duplicates by DOI. A source
          that fails is reported rather than silently dropped.
        </p>
      </div>

      {error && <ErrorBanner message={error} onDismiss={() => setError(null)} />}

      <form onSubmit={run} className="card space-y-3 p-5">
        <div className="flex gap-2">
          <input
            className="input"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="e.g. melatonin delayed sleep phase randomised trial"
            required
            minLength={2}
          />
          <button type="submit" disabled={busy} className="btn-primary shrink-0">
            {busy ? "Searching…" : "Search"}
          </button>
        </div>
        <div className="flex flex-wrap gap-3">
          {SOURCES.map((source) => (
            <label key={source.name} className="flex items-center gap-1.5 text-xs text-ink-600">
              <input
                type="checkbox"
                checked={selected.includes(source.name)}
                onChange={(event) =>
                  setSelected((current) =>
                    event.target.checked
                      ? [...current, source.name]
                      : current.filter((name) => name !== source.name),
                  )
                }
              />
              {source.label}
            </label>
          ))}
        </div>
      </form>

      {Object.keys(sourceErrors).length > 0 && (
        <div className="rounded-lg border border-partial-ring bg-partial-soft px-4 py-3 text-xs text-amber-800">
          {Object.entries(sourceErrors).map(([source, message]) => (
            <p key={source}>
              <span className="font-medium">{source}</span>: {message}
            </p>
          ))}
        </div>
      )}

      {hits && hits.length === 0 && (
        <p className="text-sm text-ink-400">No records matched.</p>
      )}

      {hits && hits.length > 0 && (
        <div className="card divide-y divide-ink-100">
          {hits.map((hit) => (
            <article key={`${hit.source}-${hit.external_id}`} className="px-5 py-4">
              <div className="flex items-start gap-4">
                <div className="min-w-0 flex-1">
                  <h3 className="text-sm font-medium leading-snug text-ink-900">{hit.title}</h3>
                  <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-ink-500">
                    <span className="chip-abstained">{hit.source}</span>
                    {hit.journal && <span>{truncate(hit.journal, 46)}</span>}
                    {hit.year && <span>{hit.year}</span>}
                    {hit.authors && <span>{truncate(hit.authors, 60)}</span>}
                    {hit.url && (
                      <a href={hit.url} target="_blank" rel="noreferrer" className="text-accent hover:underline">
                        open
                      </a>
                    )}
                  </div>
                  {hit.abstract ? (
                    <p className="mt-2 text-[13px] leading-relaxed text-ink-600">
                      {truncate(hit.abstract, 340)}
                    </p>
                  ) : (
                    <p className="mt-2 text-[13px] italic text-ink-400">
                      No abstract available — import will fail; upload the PDF instead.
                    </p>
                  )}
                </div>
                <button
                  onClick={() => void importHit(hit)}
                  disabled={!hit.abstract || importing === hit.external_id}
                  className="btn-secondary shrink-0 text-xs"
                >
                  {importing === hit.external_id ? "Importing…" : "Import"}
                </button>
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
