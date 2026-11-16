/**
 * Client-side exports of the evidence table.
 *
 * Everything exported is what the reviewer sees: only grounded values, each with
 * its verbatim quote, so a spreadsheet row can still be checked against the
 * paper. Withheld fields export as empty cells with the abstention reason in an
 * adjacent column, never as a guess.
 */

import { FIELD_LABELS, explainAbstention, fieldAt } from "./format";
import type { DocumentSummary, Extraction } from "./types";

export const FIELD_ORDER = Object.keys(FIELD_LABELS);

function csvCell(value: unknown): string {
  const text = value === null || value === undefined ? "" : String(value);
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export function toCsv(rows: Record<string, unknown>[]): string {
  if (rows.length === 0) return "";
  const headers = Array.from(
    rows.reduce((set, row) => {
      Object.keys(row).forEach((key) => set.add(key));
      return set;
    }, new Set<string>()),
  );
  const lines = [headers.map(csvCell).join(",")];
  for (const row of rows) lines.push(headers.map((header) => csvCell(row[header])).join(","));
  // BOM so Excel opens UTF-8 (en dashes, ≤, Greek letters) correctly.
  return `﻿${lines.join("\r\n")}`;
}

/** One row per paper: metadata, every field value, and the primary result. */
export function libraryRow(
  document: DocumentSummary,
  extraction: Extraction | null,
): Record<string, unknown> {
  const review = extraction?.payload ?? null;
  const row: Record<string, unknown> = {
    title: document.title,
    journal: document.journal,
    year: document.year,
    doi: document.doi,
    pmid: document.pmid,
    engine: extraction ? `${extraction.provider} · ${extraction.model}` : "",
  };
  for (const path of FIELD_ORDER) {
    row[FIELD_LABELS[path]] = fieldAt(review, path)?.value ?? "";
  }
  const primary = review?.outcomes.find(
    (outcome) => outcome.kind === "primary" && !outcome.name.startsWith("[withheld]"),
  );
  row["Primary result"] = primary
    ? [primary.measure, primary.effect_size, primary.confidence_interval, primary.p_value]
        .filter(Boolean)
        .join(" · ")
    : "";
  return row;
}

/** One row per field for a single paper, with quote, provenance and reason. */
export function evidenceRows(extraction: Extraction): Record<string, unknown>[] {
  const review = extraction.payload;
  const spans = new Map(extraction.spans.map((span) => [span.field_path, span]));
  const rows: Record<string, unknown>[] = FIELD_ORDER.map((path) => {
    const field = fieldAt(review, path);
    const span = spans.get(path);
    const reason = extraction.abstentions?.[path];
    return {
      field: FIELD_LABELS[path],
      value: field?.value ?? "",
      quote: span?.quote ?? "",
      section: span?.section_name ?? "",
      page: span?.page_no ?? "",
      char_start: span?.char_start ?? "",
      char_end: span?.char_end ?? "",
      confidence: extraction.confidence?.[path] ?? "",
      withheld_reason: field?.value ? "" : reason ? explainAbstention(reason) : "",
    };
  });
  review?.outcomes
    .filter((outcome) => !outcome.name.startsWith("[withheld]"))
    .forEach((outcome) => {
      rows.push({
        field: `Result (${outcome.kind})`,
        value: [outcome.name, outcome.measure, outcome.effect_size, outcome.confidence_interval, outcome.p_value]
          .filter(Boolean)
          .join(" · "),
        quote: outcome.quote ?? "",
        confidence: outcome.confidence,
      });
    });
  return rows;
}

/** RIS record for reference managers (EndNote, Zotero, Covidence imports). */
export function toRis(document: DocumentSummary, extraction: Extraction | null): string {
  const lines = ["TY  - JOUR", `TI  - ${document.title}`];
  (document.authors ?? "")
    .split(/;|,(?=\s*[A-Z][a-z]+\s)/)
    .map((author) => author.trim())
    .filter(Boolean)
    .forEach((author) => lines.push(`AU  - ${author}`));
  if (document.journal) lines.push(`JO  - ${document.journal}`);
  if (document.year) lines.push(`PY  - ${document.year}`);
  if (document.doi) lines.push(`DO  - ${document.doi}`);
  if (document.pmid) lines.push(`AN  - PMID:${document.pmid}`);
  if (document.source_url) lines.push(`UR  - ${document.source_url}`);
  const review = extraction?.payload ?? null;
  for (const path of ["pico.population", "pico.intervention", "pico.comparison", "pico.outcome", "design.design"]) {
    const value = fieldAt(review, path)?.value;
    if (value) lines.push(`N1  - ${FIELD_LABELS[path]}: ${value}`);
  }
  lines.push("ER  - ", "");
  return lines.join("\r\n");
}

export function downloadFile(filename: string, content: string, mime: string): void {
  const blob = new Blob([content], { type: `${mime};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const link = window.document.createElement("a");
  link.href = url;
  link.download = filename;
  window.document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function slug(text: string): string {
  return (
    text
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "")
      .slice(0, 60) || "paper"
  );
}
