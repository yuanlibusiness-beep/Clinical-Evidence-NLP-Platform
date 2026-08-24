"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { RequireAuth } from "@/components/AuthProvider";
import { ErrorBanner } from "@/components/ErrorBanner";
import { EvidenceTable } from "@/components/EvidenceTable";
import { OutcomeTable } from "@/components/OutcomeTable";
import { RetrievalDebugger } from "@/components/RetrievalDebugger";
import { Shell } from "@/components/Shell";
import { SourceReader } from "@/components/SourceReader";
import { api, ApiError } from "@/lib/api";
import { formatDate, percent } from "@/lib/format";
import type { DocumentDetail, Extraction } from "@/lib/types";

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
  const [tab, setTab] = useState<"review" | "retrieval">("review");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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

  async function extract(force: boolean) {
    setBusy(true);
    setError(null);
    try {
      setExtraction(await api.extract(id, force));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Extraction failed.");
    } finally {
      setBusy(false);
    }
  }

  if (!document) {
    return (
      <div className="space-y-3">
        <div className="skeleton h-8 w-2/3" />
        <div className="skeleton h-64 w-full" />
      </div>
    );
  }

  const answered = extraction?.confidence ? Object.keys(extraction.confidence).length : 0;
  const withheld = extraction?.abstentions ? Object.keys(extraction.abstentions).length : 0;

  return (
    <div className="space-y-6">
      <div>
        <Link href="/library" className="text-xs text-ink-500 hover:text-accent">
          ← Library
        </Link>
        <h1 className="mt-2 text-lg font-semibold leading-snug tracking-tight text-ink-900">
          {document.title}
        </h1>
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-500">
          {document.journal && <span>{document.journal}</span>}
          {document.year && <span>{document.year}</span>}
          <span>{document.n_chunks} chunks</span>
          <span>{document.sections.length} sections</span>
          {document.doi && (
            <a
              href={`https://doi.org/${document.doi}`}
              target="_blank"
              rel="noreferrer"
              className="text-accent hover:underline"
            >
              {document.doi}
            </a>
          )}
          {document.source_url && (
            <a
              href={document.source_url}
              target="_blank"
              rel="noreferrer"
              className="text-accent hover:underline"
            >
              source
            </a>
          )}
        </div>
      </div>

      {error && <ErrorBanner message={error} onDismiss={() => setError(null)} />}

      <div className="card flex flex-wrap items-center gap-4 px-5 py-4">
        <div className="flex-1">
          {extraction ? (
            <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-ink-500">
              <Stat label="fields answered" value={String(answered)} />
              <Stat label="withheld" value={String(withheld)} />
              <Stat label="grounded" value={percent(extraction.grounded_field_ratio)} />
              <Stat label="engine" value={`${extraction.provider} · ${extraction.model}`} />
              <Stat label="latency" value={`${extraction.latency_ms} ms`} />
              <Stat label="run" value={formatDate(extraction.created_at)} />
            </div>
          ) : (
            <p className="text-sm text-ink-500">
              No evidence review yet. Extraction retrieves targeted evidence per field, then
              withholds anything it cannot trace back to this document.
            </p>
          )}
        </div>
        <button onClick={() => void extract(Boolean(extraction))} disabled={busy} className="btn-primary">
          {busy ? "Extracting…" : extraction ? "Re-run extraction" : "Extract evidence"}
        </button>
      </div>

      <div className="flex gap-1 rounded-lg bg-ink-100 p-1 lg:w-96">
        {(
          [
            ["review", "Evidence review"],
            ["retrieval", "Retrieval inspector"],
          ] as const
        ).map(([value, label]) => (
          <button
            key={value}
            onClick={() => setTab(value)}
            className={`flex-1 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
              tab === value ? "bg-white text-ink-900 shadow-sm" : "text-ink-500"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "retrieval" ? (
        <RetrievalDebugger documentId={id} />
      ) : (
        <div className="grid gap-6 lg:grid-cols-2">
          <div className="space-y-4">
            <EvidenceTable
              review={extraction?.payload ?? null}
              confidence={extraction?.confidence ?? null}
              abstentions={extraction?.abstentions ?? null}
              spans={extraction?.spans ?? []}
              activeField={activeField}
              onSelectField={setActiveField}
            />
            {extraction?.payload && <OutcomeTable outcomes={extraction.payload.outcomes} />}
            {extraction?.payload?._meta?.notes?.length ? (
              <div className="card px-5 py-4">
                <h3 className="text-sm font-semibold text-ink-900">Engine notes</h3>
                <ul className="mt-2 space-y-1 text-xs text-ink-500">
                  {extraction.payload._meta.notes.map((note, index) => (
                    <li key={index}>{note}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>

          <div className="lg:sticky lg:top-28 lg:self-start">
            <SourceReader
              text={document.raw_text}
              spans={extraction?.spans ?? []}
              activeField={activeField}
              onSelectField={setActiveField}
            />
          </div>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <span className="flex items-baseline gap-1.5">
      <span className="uppercase tracking-wide text-ink-400">{label}</span>
      <span className="font-medium text-ink-700">{value}</span>
    </span>
  );
}
