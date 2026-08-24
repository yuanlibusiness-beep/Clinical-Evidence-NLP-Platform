"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { RequireAuth } from "@/components/AuthProvider";
import { ErrorBanner } from "@/components/ErrorBanner";
import { Shell } from "@/components/Shell";
import { api, ApiError } from "@/lib/api";

export default function IngestPage() {
  return (
    <RequireAuth>
      <Shell>
        <Ingest />
      </Shell>
    </RequireAuth>
  );
}

function Ingest() {
  const router = useRouter();
  const [tab, setTab] = useState<"pdf" | "text">("pdf");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [dragging, setDragging] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  async function uploadPdf(file: File) {
    setError(null);
    setBusy(true);
    try {
      const document = await api.uploadPdf(file);
      router.push(`/documents/${document.id}`);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Upload failed.");
    } finally {
      setBusy(false);
    }
  }

  async function submitText(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const document = await api.ingestText({ title: title || "Pasted document", text });
      router.push(`/documents/${document.id}`);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Ingestion failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="text-lg font-semibold tracking-tight text-ink-900">Add a paper</h1>
        <p className="mt-1 text-sm text-ink-500">
          The text is parsed into IMRaD sections, chunked on sentence boundaries and
          embedded. Nothing is extracted until you ask for it.
        </p>
      </div>

      {error && <ErrorBanner message={error} onDismiss={() => setError(null)} />}

      <div className="flex gap-1 rounded-lg bg-ink-100 p-1">
        {(
          [
            ["pdf", "Upload PDF"],
            ["text", "Paste text"],
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

      {tab === "pdf" ? (
        <div className="card p-6">
          <div
            onDragOver={(event) => {
              event.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(event) => {
              event.preventDefault();
              setDragging(false);
              const file = event.dataTransfer.files?.[0];
              if (file) void uploadPdf(file);
            }}
            className={`flex flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-14 text-center transition-colors ${
              dragging ? "border-accent bg-accent-soft" : "border-ink-300 bg-ink-50"
            }`}
          >
            <p className="text-sm font-medium text-ink-700">
              {busy ? "Parsing and indexing…" : "Drop a PDF here"}
            </p>
            <p className="mt-1 text-xs text-ink-500">
              Text-layer PDFs only — a scanned paper needs OCR first (e.g. ocrmypdf).
            </p>
            <button
              type="button"
              disabled={busy}
              onClick={() => fileInput.current?.click()}
              className="btn-secondary mt-4"
            >
              Choose a file
            </button>
            <input
              ref={fileInput}
              type="file"
              accept="application/pdf,.pdf"
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void uploadPdf(file);
              }}
            />
          </div>
        </div>
      ) : (
        <form onSubmit={submitText} className="card space-y-4 p-6">
          <div>
            <label className="label" htmlFor="title">
              Title
            </label>
            <input
              id="title"
              className="input"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="Effect of … : a randomised controlled trial"
            />
          </div>
          <div>
            <label className="label" htmlFor="text">
              Full text or abstract
            </label>
            <textarea
              id="text"
              required
              minLength={40}
              rows={16}
              className="input font-mono text-[13px] leading-relaxed"
              value={text}
              onChange={(event) => setText(event.target.value)}
              placeholder={
                "Paste the paper here.\n\nKeeping the section headings (Methods, Results, Discussion) on their own lines gives the sectioniser something to work with and measurably improves retrieval."
              }
            />
            <p className="mt-1 text-[11px] text-ink-400">
              {text.length.toLocaleString()} characters
            </p>
          </div>
          <button type="submit" disabled={busy || text.length < 40} className="btn-primary">
            {busy ? "Indexing…" : "Ingest and index"}
          </button>
        </form>
      )}
    </div>
  );
}
