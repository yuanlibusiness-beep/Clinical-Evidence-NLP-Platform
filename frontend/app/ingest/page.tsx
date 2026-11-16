"use client";

/**
 * Ingestion: three ways in, one visible pipeline.
 *
 * The backend parses, cleans, sections, chunks and indexes inside one request,
 * so the panel advances through the stages on a timer while that request is in
 * flight and then settles on the real outcome: every stage ticked with the
 * document's actual page, section and chunk counts, or the failing stage marked
 * with the backend's own error message. It never claims a stage finished that
 * the response did not confirm.
 */

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { RequireAuth } from "@/components/AuthProvider";
import { ErrorBanner } from "@/components/ErrorBanner";
import { ArrowRightIcon, CheckIcon, UploadIcon } from "@/components/Icons";
import { Segmented } from "@/components/Segmented";
import { Shell } from "@/components/Shell";
import { api, ApiError } from "@/lib/api";
import type { DocumentDetail, LiteratureHit } from "@/lib/types";

type Tab = "pdf" | "text" | "id";
type RunState = "idle" | "running" | "done" | "failed";

const STAGES = [
  { title: "Parse", detail: "Text blocks in two-column reading order, with a page map for every character." },
  { title: "Clean", detail: "Running heads, footers and figure panels removed; hyphenation repaired." },
  { title: "Section", detail: "IMRaD detection, aware of structured abstracts." },
  { title: "Chunk", detail: "Sentence-aligned, section-bounded windows." },
  { title: "Index", detail: "BM25 and dense vectors, fused by reciprocal rank at query time." },
];

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
  const [tab, setTab] = useState<Tab>("pdf");
  const [error, setError] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [identifier, setIdentifier] = useState("");
  const [dragging, setDragging] = useState(false);
  const [fileName, setFileName] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const [run, setRun] = useState<RunState>("idle");
  const [stage, setStage] = useState(0);
  const [result, setResult] = useState<DocumentDetail | null>(null);
  const timer = useRef<number | null>(null);

  useEffect(() => () => stopTimer(), []);

  function stopTimer() {
    if (timer.current !== null) window.clearInterval(timer.current);
    timer.current = null;
  }

  async function ingest(work: () => Promise<DocumentDetail>) {
    setError(null);
    setResult(null);
    setRun("running");
    setStage(0);
    stopTimer();
    // Walk the first four stages while the request runs; "Index" waits for the
    // response because it is the one that can take a while.
    timer.current = window.setInterval(() => {
      setStage((current) => Math.min(current + 1, STAGES.length - 1));
    }, 700);
    try {
      const document = await work();
      stopTimer();
      setStage(STAGES.length);
      setResult(document);
      setRun(document.status === "failed" ? "failed" : "done");
      if (document.status === "failed") setError(document.error ?? "Indexing failed.");
    } catch (caught) {
      stopTimer();
      setRun("failed");
      setError(caught instanceof ApiError ? caught.message : "Ingestion failed.");
    }
  }

  function uploadPdf(file: File) {
    setFileName(file.name);
    void ingest(() => api.uploadPdf(file));
  }

  function submitText(event: React.FormEvent) {
    event.preventDefault();
    void ingest(() => api.ingestText({ title: title || "Pasted document", text }));
  }

  function submitIdentifier(event: React.FormEvent) {
    event.preventDefault();
    void ingest(async () => {
      const hit = await findByIdentifier(identifier);
      const summary = await api.importHit(hit);
      return api.getDocument(summary.id);
    });
  }

  const busy = run === "running";

  return (
    <div className="space-y-6">
      <section className="animate-rise pt-4">
        <h1 className="text-[34px] font-bold tracking-[-0.035em] sm:text-[40px]">Add a paper</h1>
        <p className="mt-2 text-[15px] text-ink-500">
          Parsed, cleaned, sectioned and indexed on this machine. Nothing leaves it unless an LLM
          key is set.
        </p>
      </section>

      {error && <ErrorBanner message={error} onDismiss={() => setError(null)} />}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
        <section className="surface flex animate-rise flex-col gap-5 p-6" style={{ animationDelay: "80ms" }}>
          <Segmented
            label="Source"
            value={tab}
            onChange={setTab}
            className="self-start"
            options={[
              { value: "pdf", label: "Upload PDF" },
              { value: "text", label: "Paste text" },
              { value: "id", label: "DOI / PMID" },
            ]}
          />

          {tab === "pdf" && (
            <div
              key="pdf"
              onDragOver={(event) => {
                event.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(event) => {
                event.preventDefault();
                setDragging(false);
                const file = event.dataTransfer.files?.[0];
                if (file && !busy) uploadPdf(file);
              }}
              className={`flex min-h-[320px] flex-1 animate-fade-in flex-col items-center justify-center gap-3.5 rounded-2.5xl px-6 py-10 text-center transition-[background-color,box-shadow,transform] duration-500 ease-calm ${
                dragging
                  ? "scale-[1.01] bg-[#F3F6FF] shadow-[inset_0_0_0_2px_#3554D1]"
                  : "bg-[#F8F9FC] shadow-[inset_0_0_0_1.5px_#DDE2EC]"
              }`}
            >
              <span className="flex h-16 w-16 animate-float items-center justify-center rounded-[20px] bg-white text-accent shadow-[0_12px_28px_-14px_rgba(23,32,72,.35)]">
                <UploadIcon />
              </span>
              <p className="font-display text-xl font-bold tracking-[-0.02em]">
                {busy && fileName ? fileName : "Drop a PDF here"}
              </p>
              <p className="text-[13.5px] text-ink-500">
                Text-layer PDFs up to 40 MB · scanned papers need OCR first (e.g. ocrmypdf)
              </p>
              <button
                type="button"
                disabled={busy}
                onClick={() => fileInput.current?.click()}
                className="btn-secondary mt-2"
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
                  if (file) uploadPdf(file);
                  event.target.value = "";
                }}
              />
            </div>
          )}

          {tab === "text" && (
            <form key="text" onSubmit={submitText} className="flex flex-1 animate-fade-in flex-col gap-4">
              <label className="label">
                Title
                <input
                  className="input"
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                  placeholder="Effect of … : a randomised controlled trial"
                />
              </label>
              <label className="label flex-1">
                Full text or abstract
                <textarea
                  required
                  minLength={40}
                  rows={12}
                  className="input h-auto min-h-[240px] flex-1 resize-y py-3.5 text-sm leading-relaxed"
                  value={text}
                  onChange={(event) => setText(event.target.value)}
                  placeholder="Keep Methods / Results / Discussion headings on their own lines — the sectioniser uses them."
                />
              </label>
              <div className="flex items-center justify-between">
                <span className="text-xs text-ink-500">{text.length.toLocaleString()} characters</span>
                <button type="submit" disabled={busy || text.length < 40} className="btn-primary">
                  {busy ? "Indexing…" : "Ingest and index"}
                </button>
              </div>
            </form>
          )}

          {tab === "id" && (
            <form key="id" onSubmit={submitIdentifier} className="flex animate-fade-in flex-col gap-4">
              <label className="label">
                DOI or PMID
                <input
                  className="input"
                  required
                  value={identifier}
                  onChange={(event) => setIdentifier(event.target.value)}
                  placeholder="10.1056/NEJMoa2021436 or 32678530"
                />
              </label>
              <p className="text-[13px] leading-relaxed text-ink-500">
                Looks the identifier up in PubMed, Europe PMC and Crossref and imports the matching
                record&apos;s abstract. Full text still needs the PDF.
              </p>
              <button type="submit" disabled={busy || identifier.trim().length < 4} className="btn-primary self-start">
                {busy ? "Fetching…" : "Fetch and index"}
              </button>
            </form>
          )}
        </section>

        <PipelinePanel run={run} stage={stage} result={result} />
      </div>
    </div>
  );
}

function PipelinePanel({
  run,
  stage,
  result,
}: {
  run: RunState;
  stage: number;
  result: DocumentDetail | null;
}) {
  const status =
    run === "idle"
      ? { text: "Idle", className: "chip-abstained" }
      : run === "running"
        ? { text: `Running · step ${Math.min(stage + 1, STAGES.length)} of ${STAGES.length}`, className: "chip-accent" }
        : run === "done"
          ? { text: "Ready", className: "chip-grounded" }
          : { text: "Failed", className: "chip bg-[#FEF2F2] text-[#B42318]" };

  const outcome: Record<number, string> = {};
  if (result && run === "done") {
    if (result.page_count > 0) outcome[0] = `${result.page_count} pages · ${result.char_count.toLocaleString()} characters`;
    else outcome[0] = `${result.char_count.toLocaleString()} characters`;
    outcome[2] = `${result.sections.length} sections: ${Array.from(new Set(result.sections.map((s) => s.name))).join(", ")}`;
    outcome[3] = `${result.n_chunks} chunks`;
    outcome[4] = "Ready for retrieval and extraction";
  }

  const filled = run === "idle" ? 0 : Math.min(stage, STAGES.length - 1) / (STAGES.length - 1);

  return (
    <section className="surface animate-rise px-7 py-6" style={{ animationDelay: "160ms" }}>
      <div className="mb-5 flex items-center justify-between">
        <h2 className="text-[17px] font-bold">Ingestion pipeline</h2>
        <span className={status.className}>{status.text}</span>
      </div>

      <ol className="relative">
        <span aria-hidden="true" className="absolute bottom-10 left-[15px] top-4 w-0.5 rounded bg-ink-150" />
        <span
          aria-hidden="true"
          className="absolute left-[15px] top-4 w-0.5 rounded bg-accent transition-[height] duration-700 ease-calm"
          style={{ height: `calc((100% - 56px) * ${filled})` }}
        />
        {STAGES.map((item, index) => {
          const done = run !== "idle" && (stage > index || run === "done");
          const failedHere = run === "failed" && index === Math.min(stage, STAGES.length - 1);
          const running = run === "running" && stage === index;
          const dim = run !== "idle" && !done && !running && !failedHere;
          return (
            <li
              key={item.title}
              className={`relative grid grid-cols-[32px_minmax(0,1fr)] gap-4 pb-[22px] transition-opacity duration-500 ${
                dim ? "opacity-50" : ""
              }`}
            >
              <span
                className={`flex h-8 w-8 items-center justify-center rounded-full transition-[background-color,box-shadow] duration-500 ${
                  failedHere
                    ? "bg-[#D92D20] text-white"
                    : done
                      ? "bg-accent text-white"
                      : running
                        ? "bg-white shadow-[0_0_0_2px_#3554D1,0_0_0_7px_rgba(53,84,209,.14)]"
                        : "bg-ink-100 text-ink-500"
                }`}
              >
                {failedHere ? (
                  <span className="text-sm font-bold">!</span>
                ) : done ? (
                  <CheckIcon size={14} className="animate-pop" />
                ) : running ? (
                  <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-[#C9D3FA] border-t-accent" />
                ) : (
                  <span className="text-xs font-semibold">{index + 1}</span>
                )}
              </span>
              <span className="flex flex-col gap-[3px] pt-[5px]">
                <span className="text-[14.5px] font-semibold">{item.title}</span>
                <span className="text-[13px] leading-normal text-ink-500">{item.detail}</span>
                {outcome[index] && (
                  <span className="mt-0.5 animate-fade-in text-[12.5px] font-medium text-grounded-ink">
                    {outcome[index]}
                  </span>
                )}
              </span>
            </li>
          );
        })}
      </ol>

      {run === "done" && result && (
        <Link href={`/documents/${result.id}`} className="btn-dark h-[46px] animate-rise rounded-[14px] px-5 text-sm">
          Open and extract evidence <ArrowRightIcon />
        </Link>
      )}
    </section>
  );
}

/** Resolve a DOI or PMID to exactly one literature record with an abstract. */
async function findByIdentifier(raw: string): Promise<LiteratureHit> {
  const identifier = raw.trim().replace(/^https?:\/\/(dx\.)?doi\.org\//i, "").replace(/^doi:\s*/i, "");
  const isPmid = /^\d{5,9}$/.test(identifier);
  const response = await api.searchLiterature(identifier, ["pubmed", "europepmc", "crossref"], 10);
  const wanted = identifier.toLowerCase();
  const match = response.hits.find((hit) =>
    isPmid ? hit.external_id === identifier || hit.external_id === `PMID:${identifier}` : hit.doi?.toLowerCase() === wanted,
  );
  if (!match) {
    throw new ApiError(
      `No record with ${isPmid ? "PMID" : "DOI"} ${identifier} was found in PubMed, Europe PMC or Crossref.`,
      404,
    );
  }
  if (!match.abstract) {
    throw new ApiError(
      `Found “${match.title}”, but ${match.source} has no abstract for it. Upload the PDF instead.`,
      422,
    );
  }
  return match;
}
