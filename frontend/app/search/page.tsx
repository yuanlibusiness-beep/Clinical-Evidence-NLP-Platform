"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { RequireAuth } from "@/components/AuthProvider";
import { ErrorBanner, NoticeBanner } from "@/components/ErrorBanner";
import { ArrowRightIcon, CheckIcon, SearchIcon } from "@/components/Icons";
import { Shell } from "@/components/Shell";
import { api, ApiError } from "@/lib/api";
import { truncate } from "@/lib/format";
import type { LiteratureHit } from "@/lib/types";

const SOURCES = [
  { name: "pubmed", label: "PubMed", dot: "bg-accent" },
  { name: "europepmc", label: "Europe PMC", dot: "bg-grounded" },
  { name: "crossref", label: "Crossref", dot: "bg-partial" },
];

const FILTERS = [
  { id: "trials", label: "Trials only" },
  { id: "abstract", label: "Has abstract" },
  { id: "recent", label: "Since 2020" },
] as const;
type FilterId = (typeof FILTERS)[number]["id"];

/** A design label read off the title. Shown as a hint, never stored. */
function designHint(title: string): string | null {
  if (/meta-?analys|systematic review/i.test(title)) return "Review / meta-analysis";
  if (/cluster[- ]randomi[sz]ed|stepped[- ]wedge/i.test(title)) return "Cluster RCT";
  if (/randomi[sz]ed|\brct\b|placebo-controlled/i.test(title)) return "RCT";
  if (/cohort/i.test(title)) return "Cohort";
  if (/case[- ]control/i.test(title)) return "Case-control";
  if (/cross[- ]sectional/i.test(title)) return "Cross-sectional";
  return null;
}

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
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string[]>(["pubmed", "europepmc"]);
  const [filters, setFilters] = useState<Record<FilterId, boolean>>({
    trials: false,
    abstract: false,
    recent: false,
  });
  const [hits, setHits] = useState<LiteratureHit[] | null>(null);
  const [sourceErrors, setSourceErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [importing, setImporting] = useState<string | null>(null);
  const [imported, setImported] = useState<Record<string, string>>({});

  async function run(event: React.FormEvent) {
    event.preventDefault();
    if (selected.length === 0) {
      setError("Select at least one database.");
      return;
    }
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
    const key = `${hit.source}-${hit.external_id}`;
    setImporting(key);
    setError(null);
    try {
      const document = await api.importHit(hit);
      setImported((current) => ({ ...current, [key]: document.id }));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Import failed.");
    } finally {
      setImporting(null);
    }
  }

  const visible = useMemo(
    () =>
      (hits ?? []).filter((hit) => {
        if (filters.trials && !/trial|randomi[sz]ed/i.test(hit.title)) return false;
        if (filters.abstract && !hit.abstract) return false;
        if (filters.recent && (hit.year ?? 0) < 2020) return false;
        return true;
      }),
    [hits, filters],
  );

  return (
    <div className="space-y-6">
      <section className="flex animate-rise flex-col items-center pt-6 text-center">
        <h1 className="text-[34px] font-bold tracking-[-0.035em] sm:text-[40px]">Search the literature</h1>
        <p className="mb-6 mt-2.5 text-[15px] text-ink-500">
          Every selected database is queried at once; records are merged by DOI.
        </p>

        <form
          onSubmit={run}
          role="search"
          className="flex w-full max-w-[820px] gap-2.5 rounded-2.5xl bg-white p-2 shadow-[0_1px_2px_rgba(17,24,39,.05),0_24px_48px_-28px_rgba(23,32,72,.22)]"
        >
          <label className="flex flex-1 items-center gap-2.5 pl-3.5">
            <SearchIcon className="shrink-0 text-ink-500" />
            <span className="sr-only">Query</span>
            <input
              type="search"
              required
              minLength={2}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="e.g. dexamethasone covid-19 randomised trial"
              className="h-[46px] w-full border-0 bg-transparent text-base text-ink-900 placeholder:text-ink-400 focus:outline-none"
            />
          </label>
          <button type="submit" disabled={busy} className="btn-primary h-[50px] rounded-[14px] px-[26px] text-[14.5px]">
            {busy ? "Searching…" : "Search"}
          </button>
        </form>

        <div className="mt-4 flex flex-wrap justify-center gap-2">
          {SOURCES.map((source) => {
            const on = selected.includes(source.name);
            return (
              <button
                key={source.name}
                type="button"
                aria-pressed={on}
                onClick={() =>
                  setSelected((current) =>
                    on ? current.filter((name) => name !== source.name) : [...current, source.name],
                  )
                }
                className={`flex h-9 items-center gap-2 rounded-full px-3.5 text-[13px] font-semibold transition-[background-color,color,box-shadow] duration-300 ${
                  on ? "bg-ink-900 text-white" : "bg-white text-ink-700 shadow-[0_0_0_1px_#E4E7EE] hover:bg-ink-100"
                }`}
              >
                <span aria-hidden="true" className={`h-2 w-2 rounded-full ${on ? source.dot : "bg-ink-300"}`} />
                {source.label}
              </button>
            );
          })}
          <span aria-hidden="true" className="mx-1.5 my-1 w-px bg-ink-200" />
          {FILTERS.map((filter) => {
            const on = filters[filter.id];
            return (
              <button
                key={filter.id}
                type="button"
                aria-pressed={on}
                onClick={() => setFilters((current) => ({ ...current, [filter.id]: !on }))}
                className={`h-9 rounded-full px-3.5 text-[13px] font-medium transition-[background-color,color,box-shadow] duration-300 ${
                  on ? "bg-ink-900 text-white" : "bg-white text-ink-700 shadow-[0_0_0_1px_#E4E7EE] hover:bg-ink-100"
                }`}
              >
                {filter.label}
              </button>
            );
          })}
        </div>
      </section>

      <div className="mx-auto w-full max-w-[1100px] space-y-3">
        {error && <ErrorBanner message={error} onDismiss={() => setError(null)} />}

        {Object.keys(sourceErrors).length > 0 && (
          <NoticeBanner>
            {Object.entries(sourceErrors).map(([source, message]) => (
              <p key={source}>
                <b>{source}</b> did not answer: {message}
              </p>
            ))}
          </NoticeBanner>
        )}

        {busy && (
          <div className="space-y-3">
            {[0, 1, 2].map((index) => (
              <div key={index} className="skeleton h-[104px]" />
            ))}
          </div>
        )}

        {!busy && hits && (
          <>
            <div className="flex justify-between px-1 text-[13px] text-ink-500">
              <span>
                {visible.length} of {hits.length} records · duplicates merged by DOI
              </span>
              <span>Sorted by relevance</span>
            </div>
            {visible.length === 0 && (
              <p className="surface-flat px-6 py-10 text-center text-sm text-ink-500">
                No records match. Try fewer filters or another database.
              </p>
            )}
            {visible.map((hit, index) => {
              const key = `${hit.source}-${hit.external_id}`;
              const documentId = imported[key];
              const design = designHint(hit.title);
              return (
                <article
                  key={key}
                  className="grid animate-rise items-center gap-6 rounded-2.5xl bg-white px-[22px] py-5 shadow-[0_1px_2px_rgba(17,24,39,.05),0_0_0_1px_#ECEEF3] transition-[transform,box-shadow] duration-500 ease-calm hover:-translate-y-0.5 hover:shadow-lift sm:grid-cols-[minmax(0,1fr)_auto]"
                  style={{ animationDelay: `${index * 60}ms` }}
                >
                  <div className="min-w-0 space-y-2">
                    <div className="flex flex-wrap gap-1.5">
                      {design && <span className="chip-accent">{design}</span>}
                      <span className="chip-abstained">{hit.source}</span>
                      {!hit.abstract && <span className="chip-partial">No abstract</span>}
                    </div>
                    <h2 className="font-sans text-base font-semibold leading-snug tracking-[-0.01em]">{hit.title}</h2>
                    <p className="text-[13px] text-ink-500">
                      {[hit.authors && truncate(hit.authors, 70), hit.journal, hit.year].filter(Boolean).join(" · ")}
                      {hit.doi && (
                        <>
                          {" · "}
                          <a
                            href={`https://doi.org/${hit.doi}`}
                            target="_blank"
                            rel="noreferrer"
                            className="font-medium text-accent hover:text-accent-strong"
                          >
                            {hit.doi}
                          </a>
                        </>
                      )}
                    </p>
                    {hit.abstract && (
                      <p className="line-clamp-2 text-[13px] leading-relaxed text-ink-600">{hit.abstract}</p>
                    )}
                  </div>
                  {documentId ? (
                    <Link
                      href={`/documents/${documentId}`}
                      className="flex h-[42px] animate-pop items-center gap-2 rounded-xl bg-grounded-soft px-4 text-[13.5px] font-semibold text-grounded-ink"
                    >
                      <CheckIcon /> In library <ArrowRightIcon size={13} />
                    </Link>
                  ) : (
                    <button
                      type="button"
                      onClick={() => void importHit(hit)}
                      disabled={!hit.abstract || importing === key}
                      title={hit.abstract ? undefined : "No abstract to import — upload the PDF instead"}
                      className="btn-dark h-[42px] rounded-xl px-[18px]"
                    >
                      {importing === key ? "Importing…" : "Import abstract"}
                    </button>
                  )}
                </article>
              );
            })}
          </>
        )}
      </div>
    </div>
  );
}
