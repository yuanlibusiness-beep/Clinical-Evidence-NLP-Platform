"use client";

/**
 * The source document with every cited sentence highlighted in place.
 *
 * Highlights are built from character offsets, so the two things that can go
 * wrong are overlapping spans (two fields citing the same sentence) and
 * out-of-order spans. Both are handled here rather than trusted from the API:
 * spans are sorted, overlaps are merged, and each merged region remembers every
 * field that cites it — which is why one sentence can light up for several rows.
 */

import { useEffect, useMemo, useRef } from "react";

import { FIELD_LABELS } from "@/lib/format";
import type { EvidenceSpan } from "@/lib/types";

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

export function SourceReader({
  text,
  spans,
  activeField,
  onSelectField,
}: {
  text: string;
  spans: EvidenceSpan[];
  activeField: string | null;
  onSelectField: (path: string | null) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const segments = useMemo(() => buildSegments(spans, text.length), [spans, text.length]);

  useEffect(() => {
    if (!activeField || !containerRef.current) return;
    const target = containerRef.current.querySelector<HTMLElement>(
      `[data-fields~="${CSS.escape(activeField)}"]`,
    );
    target?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [activeField]);

  const nodes: React.ReactNode[] = [];
  let cursor = 0;

  segments.forEach((segment, index) => {
    if (segment.start > cursor) {
      nodes.push(<span key={`plain-${index}`}>{text.slice(cursor, segment.start)}</span>);
    }
    const isActive = activeField !== null && segment.fields.includes(activeField);
    nodes.push(
      <mark
        key={`mark-${index}`}
        data-fields={segment.fields.join(" ")}
        onClick={() => onSelectField(segment.fields[0] ?? null)}
        title={segment.fields.map((path) => FIELD_LABELS[path] ?? path).join(" · ")}
        className={`cursor-pointer ${isActive ? "evidence-highlight-active" : "evidence-highlight"}`}
      >
        {text.slice(segment.start, segment.end)}
      </mark>,
    );
    cursor = segment.end;
  });

  if (cursor < text.length) {
    nodes.push(<span key="plain-tail">{text.slice(cursor)}</span>);
  }

  return (
    <div className="card flex h-[calc(100vh-14rem)] flex-col">
      <div className="card-header">
        <h3 className="text-sm font-semibold text-ink-900">Source</h3>
        <p className="text-[11px] text-ink-400">
          {segments.length} cited {segments.length === 1 ? "passage" : "passages"}
        </p>
      </div>
      <div
        ref={containerRef}
        className="flex-1 overflow-y-auto whitespace-pre-wrap px-5 py-4 font-mono text-[12.5px] leading-6 text-ink-700"
      >
        {nodes}
      </div>
    </div>
  );
}
