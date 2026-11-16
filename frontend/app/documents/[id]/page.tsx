"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { RequireAuth } from "@/components/AuthProvider";
import { ErrorBanner } from "@/components/ErrorBanner";
import { EvidenceTable } from "@/components/EvidenceTable";
import { ArrowLeftIcon, ChevronIcon, DownloadIcon } from "@/components/Icons";
import { ResultsView } from "@/components/ResultsView";
import { RetrievalDebugger } from "@/components/RetrievalDebugger";
import { Segmented } from "@/components/Segmented";
import { Shell } from "@/components/Shell";
import { ProvenanceCard, SourceReader } from "@/components/SourceReader";
import { api, ApiError } from "@/lib/api";
import { downloadFile, evidenceRows, slug, toCsv, toRis } from "@/lib/export";
import { fieldAt, formatDate, percent } from "@/lib/format";
import type { DocumentDetail, Extraction } from "@/lib/types";
import { useVerification } from "@/lib/verification";

type Tab = "evidence" | "results" | "retrieval";

export default function DocumentPage({ params }: { params: { id: string } }) {
  return (
    <RequireAuth>
      <Shell>
        <DocumentView id={params.id} />
      </Shell>
    </RequireAuth>
  );
}

function DocumentView({ id }: { id: string }) {
  const [document, setDocument] = useState<DocumentDetail | null>(null);
  const [extraction, setExtraction] = useState<Extraction | null>(null);
  const [activeField, setActiveField] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("evidence");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const { verified, toggle } = useVerification(extraction?.id ?? null);

  const load = useCallback(async () => {
    try {
      const detail = await api.getDocument(id);
      setDocument(detail);
      const existing = await api.listExtractions(id);
      const completed = existing.find((item) => item.status === "completed");
      if (completed) setExtraction(completed);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not load the document.");
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  // Open on the first cited field, so the reader starts in focus mode.
  useEffect(() => {
    if (!extraction) return;
    const first = extraction.spans.find((span) => !span.field_path.startsWith("outcomes["));
    setActiveField(first?.field_path ?? null);
  }, [extraction]);

  async function extract(force: boolean) {
    setBusy(true);
    setError(null);
    try {
      const result = await api.extract(id, force);
      if (result.status === "failed") setError(result.error ?? "Extraction failed.");
      setExtraction(result);
      setTab("evidence");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Extraction failed.");
    } finally {
      setBusy(false);
    }
  }

  function changeTab(next: Tab) {
    setTab(next);
    if (next === "results" && extraction?.payload) {
      const index = extraction.payload.outcomes.findIndex((outcome) => !outcome.name.startsWith("[withheld]"));
      setActiveField(index >= 0 ? `outcomes[${index}]` : null);
    }
    if (next === "evidence" && activeField?.startsWith("outcomes[")) {
      const first = extraction?.spans.find((span) => !span.field_path.startsWith("outcomes["));
      setActiveField(first?.field_path ?? null);
    }
  }

  if (!document) {
    return (
      <div className="space-y-4 pt-4">
        {error ? (
          <ErrorBanner message={error} />
        ) : (
          <>
            <div className="skeleton h-10 w-2/3" />
            <div className="grid gap-6 lg:grid-cols-2">
              <div className="skeleton h-[520px]" />
              <div className="skeleton h-[520px]" />
            </div>
          </>
        )}
      </div>
    );
  }

  const review = extraction?.status === "completed" ? extraction.payload : null;
  const answeredPaths = extraction?.confidence ? Object.keys(extraction.confidence) : [];
  const answered = answeredPaths.length;
  const withheld = extraction?.abstentions ? Object.keys(extraction.abstentions).length : 0;
  const verifiedCount = answeredPaths.filter((path) => verified.has(path)).length;
  const registration = fieldAt(review, "design.registration_id")?.value;
  const meta = review?._meta;

  const chips = [
    [document.journal, document.year].filter(Boolean).join(" · "),
    registration,
    `${document.n_chunks} chunks · ${document.sections.length} sections`,
    extraction ? `${extraction.model}${meta?.prompt_version ? ` · prompt ${meta.prompt_version}` : ""} · ${extraction.latency_ms} ms` : null,
  ].filter(Boolean) as string[];

  return (
    <div className="space-y-6">
      <section className="flex animate-rise flex-wrap items-end justify-between gap-6 pt-2">
        <div className="max-w-[780px]">
          <Link
            href="/library"
            className="inline-flex items-center gap-1.5 text-[13px] font-medium text-accent hover:text-accent-strong"
          >
            <ArrowLeftIcon size={13} /> Library
          </Link>
          <h1 className="mb-3 mt-2.5 text-[28px] font-bold leading-[1.12] tracking-[-0.035em] sm:text-[36px]">
            {document.title}
          </h1>
          <div className="flex flex-wrap gap-2">
            {chips.map((chip) => (
              <span key={chip} className="chip-outline px-2.5 py-1 text-[12.5px]">
                {chip}
              </span>
            ))}
            {document.doi && (
              <a
                href={`https://doi.org/${document.doi}`}
                target="_blank"
                rel="noreferrer"
                className="chip-outline px-2.5 py-1 text-[12.5px] text-accent hover:text-accent-strong"
              >
                DOI {document.doi}
              </a>
            )}
          </div>
        </div>

        <div className="flex flex-col items-start gap-3 sm:items-end">
          {review && answered > 0 && (
            <div className="flex items-center gap-3 text-[13px] text-ink-700">
              <span>
                {verifiedCount} of {answered} fields verified by you
              </span>
              <span aria-hidden="true" className="h-1.5 w-36 overflow-hidden rounded-full bg-ink-200">
                <span
                  className="block h-full rounded-full bg-grounded transition-[width] duration-700 ease-calm"
                  style={{ width: `${(verifiedCount / answered) * 100}%` }}
                />
              </span>
            </div>
          )}
          <div className="flex gap-2.5">
            {review && extraction && <ExportMenu document={document} extraction={extraction} />}
            <button onClick={() => void extract(Boolean(extraction))} disabled={busy} className="btn-primary">
              {busy ? "Extracting…" : extraction ? "Re-run extraction" : "Extract evidence"}
            </button>
          </div>
        </div>
      </section>

      {error && <ErrorBanner message={error} onDismiss={() => setError(null)} />}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.08fr)_minmax(0,1fr)]">
        <section className="surface min-w-0 animate-rise p-5" style={{ animationDelay: "90ms" }}>
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <Segmented
              label="View"
              value={tab}
              onChange={changeTab}
              options={[
                { value: "evidence", label: "Evidence" },
                { value: "results", label: "Results" },
                { value: "retrieval", label: "Retrieval" },
              ]}
            />
            {extraction && review && (
              <span className="text-[12.5px] text-ink-500">
                {answered} answered · {withheld} withheld · {percent(extraction.grounded_field_ratio)} grounded
              </span>
            )}
          </div>

          {!review && tab !== "retrieval" && (
            <div className="mb-2 animate-rise rounded-2xl bg-accent-soft px-5 py-4">
              <p className="text-[14px] font-semibold text-accent-ink">No evidence review yet</p>
              <p className="mt-1 text-[13px] leading-relaxed text-ink-600">
                Extraction retrieves targeted evidence per field, then withholds anything it cannot
                trace back to this document.
              </p>
            </div>
          )}

          <div key={tab} className="animate-fade-in">
            {tab === "evidence" && (
              <EvidenceTable
                review={review}
                confidence={extraction?.confidence ?? null}
                abstentions={extraction?.abstentions ?? null}
                activeField={activeField}
                onSelectField={setActiveField}
                verified={verified}
                onToggleVerified={toggle}
              />
            )}
            {tab === "results" &&
              (review ? (
                <ResultsView outcomes={review.outcomes} activeField={activeField} onSelectField={setActiveField} />
              ) : (
                <p className="px-3.5 py-10 text-center text-sm text-ink-500">Run an extraction to see results.</p>
              ))}
            {tab === "retrieval" && <RetrievalDebugger documentId={id} />}
          </div>

          {meta?.notes && meta.notes.length > 0 && tab === "evidence" && (
            <div className="mt-4 rounded-2xl bg-[#F8F9FC] px-4 py-3">
              <p className="eyebrow mb-1">Engine notes</p>
              <ul className="space-y-1 text-[12.5px] text-ink-600">
                {meta.notes.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            </div>
          )}
          {extraction && (
            <p className="mt-4 px-1 text-xs text-ink-400">Run {formatDate(extraction.created_at)}</p>
          )}
        </section>

        <aside
          className="flex min-w-0 animate-rise flex-col gap-3.5 lg:sticky lg:top-24 lg:self-start"
          style={{ animationDelay: "180ms" }}
          aria-label="Source document"
        >
          <SourceReader
            text={document.raw_text}
            spans={extraction?.spans ?? []}
            review={review}
            activeField={activeField}
            onSelectField={setActiveField}
          />
          <ProvenanceCard
            activeField={activeField}
            spans={extraction?.spans ?? []}
            review={review}
            confidence={extraction?.confidence ?? null}
            abstentions={extraction?.abstentions ?? null}
            calibrated={Boolean(meta?.calibrated)}
          />
        </aside>
      </div>
    </div>
  );
}

function ExportMenu({ document, extraction }: { document: DocumentDetail; extraction: Extraction }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => event.key === "Escape" && setOpen(false);
    window.document.addEventListener("mousedown", close);
    window.document.addEventListener("keydown", escape);
    return () => {
      window.document.removeEventListener("mousedown", close);
      window.document.removeEventListener("keydown", escape);
    };
  }, [open]);

  const base = slug(document.title);
  const options = [
    {
      label: "Evidence table · CSV",
      hint: "One row per field, with quote and provenance",
      run: () => downloadFile(`${base}-evidence.csv`, toCsv(evidenceRows(extraction)), "text/csv"),
    },
    {
      label: "Full review · JSON",
      hint: "Payload, confidences, abstentions and spans",
      run: () =>
        downloadFile(
          `${base}-review.json`,
          JSON.stringify({ document: { ...document, raw_text: undefined }, extraction }, null, 2),
          "application/json",
        ),
    },
    {
      label: "Citation · RIS",
      hint: "For EndNote, Zotero or Covidence",
      run: () => downloadFile(`${base}.ris`, toRis(document, extraction), "application/x-research-info-systems"),
    },
  ];

  return (
    <div ref={ref} className="relative">
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className="btn-secondary">
        <DownloadIcon /> Export <ChevronIcon size={12} />
      </button>
      {open && (
        <div className="absolute right-0 top-[calc(100%+8px)] z-20 w-72 animate-rise rounded-2xl bg-white p-2 shadow-lift">
          {options.map((option) => (
            <button
              key={option.label}
              type="button"
              onClick={() => {
                option.run();
                setOpen(false);
              }}
              className="flex w-full flex-col rounded-xl px-3 py-2.5 text-left transition-colors hover:bg-ink-100"
            >
              <span className="text-[13.5px] font-semibold text-ink-900">{option.label}</span>
              <span className="text-xs text-ink-500">{option.hint}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
