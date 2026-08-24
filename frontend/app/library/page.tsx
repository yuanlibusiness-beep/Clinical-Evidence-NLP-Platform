"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { RequireAuth } from "@/components/AuthProvider";
import { Shell } from "@/components/Shell";
import { ErrorBanner } from "@/components/ErrorBanner";
import { api, ApiError } from "@/lib/api";
import { formatDate, truncate } from "@/lib/format";
import type { DocumentSummary } from "@/lib/types";

const STATUS_STYLE: Record<string, string> = {
  ready: "chip-grounded",
  failed: "chip bg-red-50 text-red-700",
  pending: "chip-abstained",
  parsing: "chip-partial",
  indexing: "chip-partial",
};

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
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .listDocuments()
      .then(setDocuments)
      .catch((caught) =>
        setError(caught instanceof ApiError ? caught.message : "Could not load documents."),
      );
  }, []);

  useEffect(load, [load]);

  async function remove(id: string) {
    if (!window.confirm("Delete this document and all its extractions?")) return;
    try {
      await api.deleteDocument(id);
      setDocuments((current) => current?.filter((doc) => doc.id !== id) ?? null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Delete failed.");
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-lg font-semibold tracking-tight text-ink-900">Library</h1>
          <p className="mt-1 text-sm text-ink-500">
            Papers you have ingested, with their index status.
          </p>
        </div>
        <Link href="/ingest" className="btn-primary">
          Add a paper
        </Link>
      </div>

      {error && <ErrorBanner message={error} onDismiss={() => setError(null)} />}

      {documents === null && (
        <div className="space-y-2">
          {[0, 1, 2].map((index) => (
            <div key={index} className="skeleton h-16 w-full" />
          ))}
        </div>
      )}

      {documents?.length === 0 && (
        <div className="card p-10 text-center">
          <p className="text-sm text-ink-500">
            No papers yet. Upload a PDF, paste an abstract, or search the literature.
          </p>
          <div className="mt-4 flex justify-center gap-2">
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
        <div className="card divide-y divide-ink-100">
          {documents.map((document) => (
            <div key={document.id} className="flex items-start gap-4 px-5 py-4">
              <div className="min-w-0 flex-1">
                <Link
                  href={`/documents/${document.id}`}
                  className="block text-sm font-medium text-ink-900 hover:text-accent"
                >
                  {truncate(document.title, 140)}
                </Link>
                <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-500">
                  <span className={STATUS_STYLE[document.status] ?? "chip-abstained"}>
                    {document.status}
                  </span>
                  <span>{document.source_type}</span>
                  {document.journal && <span>{truncate(document.journal, 40)}</span>}
                  {document.year && <span>{document.year}</span>}
                  <span>{document.char_count.toLocaleString()} chars</span>
                  {document.page_count > 0 && <span>{document.page_count} pp</span>}
                  <span>{formatDate(document.created_at)}</span>
                </div>
                {document.error && (
                  <p className="mt-1.5 text-xs text-red-600">{document.error}</p>
                )}
              </div>
              <button onClick={() => remove(document.id)} className="btn-ghost text-xs">
                Delete
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
