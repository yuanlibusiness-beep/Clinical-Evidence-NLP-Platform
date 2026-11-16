"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { RequireAuth } from "@/components/AuthProvider";
import { ErrorBanner } from "@/components/ErrorBanner";
import { DownloadIcon, TrashIcon } from "@/components/Icons";
import { Segmented } from "@/components/Segmented";
import { Shell } from "@/components/Shell";
import { api, ApiError } from "@/lib/api";
import { downloadFile, libraryRow, toCsv } from "@/lib/export";
import { fieldAt, shortDate } from "@/lib/format";
import type { DocumentSummary, Extraction } from "@/lib/types";

type Filter = "all" | "indexed" | "reviewed" | "pending";

export default function LibraryPage() {
  return (
    <RequireAuth>
      <Shell>
        <Library />
      </Shell>
    </RequireAuth>
  );
}

function Library() {
  const [documents, setDocuments] = useState<DocumentSummary[] | null>(null);
  const [reviews, setReviews] = useState<Record<string, Extraction | null>>({});
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const list = await api.listDocuments();
      setDocuments(list);
      // The latest completed review per paper drives the Design and Evidence
      // columns. One request per paper is fine at library scale.
      const entries = await Promise.all(
        list
          .filter((doc) => doc.status === "ready")
          .map(async (doc) => {
            try {
              const runs = await api.listExtractions(doc.id);
              return [doc.id, runs.find((run) => run.status === "completed") ?? null] as const;
            } catch {
              return [doc.id, null] as const;
            }
          }),
      );
      setReviews(Object.fromEntries(entries));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not load documents.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Keep polling while anything is still being indexed.
  const busy = documents?.some((doc) => ["pending", "parsing", "indexing"].includes(doc.status));
  useEffect(() => {
    if (!busy) return;
    const timer = window.setInterval(() => void load(), 3000);
    return () => window.clearInterval(timer);
  }, [busy, load]);

  async function remove(document: DocumentSummary) {
    if (!window.confirm(`Delete “${document.title}” and all its extractions?`)) return;
    try {
      await api.deleteDocument(document.id);
      setDocuments((current) => current?.filter((doc) => doc.id !== document.id) ?? null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Delete failed.");
    }
  }

  const counts = useMemo(() => {
    const list = documents ?? [];
    return {
      total: list.length,
      indexed: list.filter((doc) => doc.status === "ready").length,
      indexing: list.filter((doc) => ["pending", "parsing", "indexing"].includes(doc.status)).length,
      reviewed: list.filter((doc) => reviews[doc.id]).length,
    };
  }, [documents, reviews]);

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (documents ?? []).filter((doc) => {
      if (filter === "indexed" && doc.status !== "ready") return false;
      if (filter === "reviewed" && !reviews[doc.id]) return false;
      if (filter === "pending" && (doc.status !== "ready" || reviews[doc.id])) return false;
      if (!needle) return true;
      return [doc.title, doc.journal, doc.doi, doc.pmid, doc.authors]
        .filter(Boolean)
        .some((text) => String(text).toLowerCase().includes(needle));
    });
  }, [documents, reviews, filter, query]);

  function exportCsv() {
    const rows = (documents ?? []).map((doc) => libraryRow(doc, reviews[doc.id] ?? null));
    downloadFile("evidence-library.csv", toCsv(rows), "text/csv");
  }

  return (
    <div className="space-y-6">
      <section className="flex animate-rise flex-wrap items-end justify-between gap-4 pt-4">
        <div>
          <h1 className="text-[34px] font-bold tracking-[-0.035em] sm:text-[40px]">Library</h1>
          <p className="mt-2 text-[15px] text-ink-500">
            {documents === null
              ? "Loading…"
              : `${counts.total} ${counts.total === 1 ? "paper" : "papers"} · ${counts.indexed} indexed${
                  counts.indexing ? ` · ${counts.indexing} indexing` : ""
                } · ${counts.reviewed} reviewed`}
          </p>
        </div>
        <div className="flex gap-2.5">
          <button
            type="button"
            onClick={exportCsv}
            disabled={!documents?.length}
            className="btn-secondary h-[46px] rounded-[14px] text-sm"
          >
            <DownloadIcon /> Export table (CSV)
          </button>
          <Link href="/ingest" className="btn-primary h-[46px] rounded-[14px] px-5 text-sm">
            Add a paper
          </Link>
        </div>
      </section>

      {error && <ErrorBanner message={error} onDismiss={() => setError(null)} />}

      <section
        className="flex animate-rise flex-wrap items-center justify-between gap-3"
        style={{ animationDelay: "80ms" }}
      >
        <Segmented
          label="Filter papers"
          value={filter}
          onChange={setFilter}
          options={[
            { value: "all", label: "All" },
            { value: "indexed", label: "Indexed" },
            { value: "reviewed", label: "Reviewed" },
            { value: "pending", label: "Needs review" },
          ]}
        />
        <label className="relative block w-full sm:w-80">
          <span className="sr-only">Search library</span>
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search title, journal, DOI…"
            className="h-[42px] w-full rounded-xl border-0 bg-white px-4 text-sm shadow-[0_0_0_1px_#E4E7EE] placeholder:text-ink-400 focus:shadow-focus focus:outline-none"
          />
        </label>
      </section>

      {documents === null && (
        <div className="space-y-2">
          {[0, 1, 2].map((index) => (
            <div key={index} className="skeleton h-[84px] w-full" />
          ))}
        </div>
      )}

      {documents?.length === 0 && (
        <div className="surface animate-rise px-6 py-16 text-center">
          <h2 className="text-xl font-bold tracking-[-0.02em]">Your library is empty</h2>
          <p className="mx-auto mt-2 max-w-md text-sm text-ink-500">
            Upload a PDF, paste an abstract, or import a record from PubMed, Europe PMC or
            Crossref.
          </p>
          <div className="mt-6 flex justify-center gap-2.5">
            <Link href="/ingest" className="btn-primary">
              Add a paper
            </Link>
            <Link href="/search" className="btn-secondary">
              Search literature
            </Link>
          </div>
        </div>
      )}

      {documents && documents.length > 0 && (
        <section className="space-y-1.5">
          <div className="hidden grid-cols-[minmax(0,1fr)_200px_120px_180px_76px_40px] gap-5 px-[22px] pb-1.5 lg:grid">
            <span className="eyebrow">Paper</span>
            <span className="eyebrow">Design</span>
            <span className="eyebrow">Status</span>
            <span className="eyebrow">Evidence review</span>
            <span className="eyebrow text-right">Added</span>
            <span />
          </div>

          {visible.length === 0 && (
            <p className="px-[22px] py-8 text-sm text-ink-500">No papers match this view.</p>
          )}

          {visible.map((document, index) => (
            <LibraryRow
              key={document.id}
              document={document}
              review={reviews[document.id] ?? null}
              delay={120 + index * 60}
              onDelete={() => void remove(document)}
            />
          ))}
        </section>
      )}
    </div>
  );
}

function LibraryRow({
  document,
  review,
  delay,
  onDelete,
}: {
  document: DocumentSummary;
  review: Extraction | null;
  delay: number;
  onDelete: () => void;
}) {
  const design = fieldAt(review?.payload ?? null, "design.design")?.value;
  const blinding = fieldAt(review?.payload ?? null, "design.blinding")?.value;
  const answered = review?.confidence ? Object.keys(review.confidence).length : 0;
  const withheld = review?.abstentions ? Object.keys(review.abstentions).length : 0;
  const meta = [
    document.journal,
    document.year,
    document.source_type === "pdf" ? "PDF" : document.source_label ?? document.source_type,
    document.page_count > 0 ? `${document.page_count} pp` : null,
    document.doi ? `DOI ${document.doi}` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div
      className="group relative grid animate-rise items-center gap-x-5 gap-y-2 rounded-[18px] bg-[#FBFBFD] px-[22px] py-[18px] shadow-hairline transition-[transform,box-shadow,background-color] duration-300 ease-calm hover:-translate-y-0.5 hover:bg-white hover:shadow-[0_14px_30px_-20px_rgba(23,32,72,.35),0_0_0_1px_#ECEEF3] lg:grid-cols-[minmax(0,1fr)_200px_120px_180px_76px_40px]"
      style={{ animationDelay: `${delay}ms` }}
    >
      <div className="min-w-0">
        <Link
          href={`/documents/${document.id}`}
          className="text-[15px] font-semibold leading-snug tracking-[-0.01em] text-ink-900 after:absolute after:inset-0 after:rounded-[18px] after:content-['']"
        >
          {document.title}
        </Link>
        <p className="mt-1 truncate text-[12.5px] text-ink-500">{meta}</p>
        {document.error && <p className="mt-1 text-[12.5px] text-[#B42318]">{document.error}</p>}
      </div>

      <span className="text-[13px] text-ink-700">
        {design ? [design, blinding].filter(Boolean).join(" · ") : <span className="text-ink-400">—</span>}
      </span>

      <StatusBadge status={document.status} />

      <span>
        {review ? (
          <span className="chip-grounded">
            {answered} answered · {withheld} withheld
          </span>
        ) : document.status === "ready" ? (
          <span className="chip-abstained">Not extracted</span>
        ) : (
          <span className="chip-abstained">Waiting for index</span>
        )}
      </span>

      <span className="text-[12.5px] text-ink-500 lg:text-right">{shortDate(document.created_at)}</span>

      <button
        type="button"
        onClick={onDelete}
        aria-label={`Delete ${document.title}`}
        className="relative z-10 hidden h-9 w-9 items-center justify-center rounded-xl text-ink-400 opacity-0 transition-[opacity,background-color,color] duration-300 hover:bg-[#FEF2F2] hover:text-[#B42318] focus:opacity-100 group-hover:opacity-100 lg:flex"
      >
        <TrashIcon />
      </button>
    </div>
  );
}

function StatusBadge({ status }: { status: DocumentSummary["status"] }) {
  if (status === "ready") {
    return (
      <span className="inline-flex items-center gap-[7px] text-[12.5px] font-semibold text-grounded-ink">
        <span aria-hidden="true" className="h-[7px] w-[7px] rounded-full bg-grounded" />
        Indexed
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span className="inline-flex items-center gap-[7px] text-[12.5px] font-semibold text-[#B42318]">
        <span aria-hidden="true" className="h-[7px] w-[7px] rounded-full bg-[#D92D20]" />
        Failed
      </span>
    );
  }
  return (
    <span className="flex flex-col gap-1.5">
      <span className="inline-flex items-center gap-[7px] text-[12.5px] font-semibold capitalize text-accent-strong">
        <span aria-hidden="true" className="h-[7px] w-[7px] animate-breathe rounded-full bg-accent" />
        {status}
      </span>
      <span aria-hidden="true" className="relative block h-1 w-24 overflow-hidden rounded-sm bg-[#E4E9FB]">
        <span className="absolute inset-y-0 w-2/5 animate-shimmer rounded-sm bg-accent" />
      </span>
    </span>
  );
}
