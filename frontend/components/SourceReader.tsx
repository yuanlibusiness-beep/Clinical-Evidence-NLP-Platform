"use client";

/**
 * The source document with every cited passage marked in place.
 *
 * Highlights are built from character offsets, so the two things that can go
 * wrong are overlapping spans (two fields citing the same sentence) and
 * out-of-order spans. Both are handled here rather than trusted from the API:
 * spans are sorted, overlaps are merged, and each merged region remembers every
 * field that cites it — which is why one sentence can light up for several rows.
 *
 * When a field is selected the reader goes into focus mode: everything except
 * the passage that field cites fades back, and the passage scrolls to centre.
 */

import { useEffect, useMemo, useRef } from "react";

import { FIELD_LABELS, explainAbstention } from "@/lib/format";
import type { EvidenceReview, EvidenceSpan } from "@/lib/types";

interface Segment {
  start: number;
  end: number;
  fields: string[];
}

function buildSegments(spans: EvidenceSpan[], length: number): Segment[] {
  const valid = spans
    .filter((span) => span.char_end > span.char_start && span.char_start >= 0 && span.char_end <= length)
    .sort((a, b) => a.char_start - b.char_start);

  const merged: Segment[] = [];
  for (const span of valid) {
    const last = merged[merged.length - 1];
    if (last && span.char_start <= last.end) {
      last.end = Math.max(last.end, span.char_end);
      if (!last.fields.includes(span.field_path)) last.fields.push(span.field_path);
    } else {
      merged.push({ start: span.char_start, end: span.char_end, fields: [span.field_path] });
    }
  }
  return merged;
}

export function labelFor(path: string, review: EvidenceReview | null): string {
  const outcome = path.match(/^outcomes\[(\d+)\]$/);
  if (outcome && review) {
    const item = review.outcomes[Number(outcome[1])];
    return item ? `${item.kind} · ${item.name}` : "Result";
  }
  return FIELD_LABELS[path] ?? path;
}

export function SourceReader({
  text,
  spans,
  review,
  activeField,
  onSelectField,
}: {
  text: string;
  spans: EvidenceSpan[];
  review: EvidenceReview | null;
  activeField: string | null;
  onSelectField: (path: string | null) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const segments = useMemo(() => buildSegments(spans, text.length), [spans, text.length]);
  const focused = activeField !== null && segments.some((segment) => segment.fields.includes(activeField));

  useEffect(() => {
    if (!activeField || !containerRef.current) return;
    const target = containerRef.current.querySelector<HTMLElement>(
      `[data-fields~="${CSS.escape(activeField)}"]`,
    );
    if (!target) return;
    const container = containerRef.current;
    const offset = target.offsetTop - container.offsetTop - container.clientHeight / 2 + target.offsetHeight / 2;
    container.scrollTo({ top: Math.max(offset, 0), behavior: "smooth" });
  }, [activeField]);

  const nodes: React.ReactNode[] = [];
  let cursor = 0;
  segments.forEach((segment, index) => {
    if (segment.start > cursor) {
      nodes.push(
        <span key={`plain-${index}`} className="plain">
          {text.slice(cursor, segment.start)}
        </span>,
      );
    }
    const isActive = activeField !== null && segment.fields.includes(activeField);
    nodes.push(
      <mark
        key={`mark-${index}`}
        data-fields={segment.fields.join(" ")}
        data-active={isActive}
        onClick={() => onSelectField(segment.fields[0] ?? null)}
        title={segment.fields.map((path) => labelFor(path, review)).join(" · ")}
        className="cite text-inherit"
      >
        {text.slice(segment.start, segment.end)}
      </mark>,
    );
    cursor = segment.end;
  });
  if (cursor < text.length) {
    nodes.push(
      <span key="plain-tail" className="plain">
        {text.slice(cursor)}
      </span>,
    );
  }

  const badge = activeField
    ? focused
      ? `Cited · ${labelFor(activeField, review)}`
      : `${labelFor(activeField, review)} · nothing cited`
    : `${segments.length} cited ${segments.length === 1 ? "passage" : "passages"}`;

  return (
    <div className="surface flex h-[calc(100vh-15rem)] min-h-[420px] flex-col overflow-hidden">
      <div className="flex items-center justify-between gap-3 px-7 pb-2 pt-6">
        <h2 className="text-[17px] font-bold">Source</h2>
        <span className="chip-accent max-w-[70%] truncate text-[12.5px] font-medium normal-case">{badge}</span>
      </div>
      <div
        ref={containerRef}
        data-focus={focused}
        className="reader relative flex-1 overflow-y-auto whitespace-pre-wrap px-7 pb-8 pt-2 text-[15px] leading-[1.78] text-ink-800"
      >
        {nodes}
      </div>
    </div>
  );
}

/** Where the selected answer came from, and how far to trust it. */
export function ProvenanceCard({
  activeField,
  spans,
  review,
  confidence,
  abstentions,
  calibrated,
}: {
  activeField: string | null;
  spans: EvidenceSpan[];
  review: EvidenceReview | null;
  confidence: Record<string, number> | null;
  abstentions: Record<string, string> | null;
  calibrated: boolean;
}) {
  if (!review || !activeField) {
    return (
      <div className="surface-flat px-[22px] py-4 text-[13px] text-ink-500">
        Select a field or result to see where its answer came from.
      </div>
    );
  }

  const span = spans.find((item) => item.field_path === activeField);
  const rule = review._meta?.rule_sources?.[activeField];
  const outcome = activeField.match(/^outcomes\[(\d+)\]$/);
  const score = outcome ? review.outcomes[Number(outcome[1])]?.confidence : confidence?.[activeField];

  const items: [string, string][] = span
    ? [
        ["Section", span.section_name + (span.page_no ? ` · p. ${span.page_no}` : "")],
        [
          "Quote match",
          span.match_score >= 0.999 ? "Verbatim · 1.000" : `Fuzzy · ${span.match_score.toFixed(3)}`,
        ],
        ["Extractor", rule ? `rule · ${rule}` : review._meta?.engine === "offline" ? "rule engine" : "language model"],
        [
          "Confidence",
          score !== undefined ? `${Math.round(score * 100)}% · ${calibrated ? "calibrated" : "uncalibrated"}` : "—",
        ],
      ]
    : [
        ["Status", "Withheld"],
        ["Reason", abstentions?.[activeField] ? explainAbstention(abstentions[activeField]) : "No supporting quote"],
        ["Next step", "Check the tables and full text manually"],
      ];

  return (
    <div
      key={activeField}
      className="surface-flat grid animate-fade-in gap-4 px-[22px] py-4 sm:grid-cols-2 xl:grid-cols-4"
    >
      {items.map(([label, value]) => (
        <div key={label} className="flex min-w-0 flex-col gap-1">
          <span className="eyebrow">{label}</span>
          <span className="text-[13.5px] font-medium text-ink-900">{value}</span>
        </div>
      ))}
      {span && (
        <p className="text-xs text-ink-500 sm:col-span-2 xl:col-span-4">
          Characters {span.char_start.toLocaleString()}–{span.char_end.toLocaleString()} of the stored text
        </p>
      )}
    </div>
  );
}
