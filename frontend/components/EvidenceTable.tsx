"use client";

/**
 * The evidence table — the product's main surface.
 *
 * Design rule: a blank cell must look *deliberate*. Most extraction UIs render
 * a missing field as an empty string, which reads as a bug and quietly trains
 * the user to distrust the blanks rather than the answers. Here every row that
 * has no value shows why it has no value, in the same visual weight as a value.
 *
 * Second rule: no number without its evidence. Clicking a row scrolls the
 * source reader to the exact sentence, so verifying a cell is one click, not a
 * search through the PDF.
 */

import { useState } from "react";

import { FIELD_GROUPS, FIELD_LABELS, explainAbstention, fieldAt, percent, tierFor } from "@/lib/format";
import type { EvidenceReview, EvidenceSpan } from "@/lib/types";

interface Props {
  review: EvidenceReview | null;
  confidence: Record<string, number> | null;
  abstentions: Record<string, string> | null;
  spans: EvidenceSpan[];
  activeField: string | null;
  onSelectField: (path: string | null) => void;
}

export function EvidenceTable({
  review,
  confidence,
  abstentions,
  spans,
  activeField,
  onSelectField,
}: Props) {
  const spanByField = new Map(spans.map((span) => [span.field_path, span]));

  return (
    <div className="space-y-4">
      {FIELD_GROUPS.map((group) => (
        <section key={group.title} className="card overflow-hidden">
          <div className="card-header">
            <h3 className="text-sm font-semibold text-ink-900">{group.title}</h3>
            <p className="text-[11px] text-ink-400">{group.hint}</p>
          </div>
          <div>
            {group.paths.map((path) => (
              <Row
                key={path}
                path={path}
                review={review}
                score={confidence?.[path]}
                reason={abstentions?.[path]}
                span={spanByField.get(path)}
                active={activeField === path}
                onSelect={onSelectField}
              />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function Row({
  path,
  review,
  score,
  reason,
  span,
  active,
  onSelect,
}: {
  path: string;
  review: EvidenceReview | null;
  score?: number;
  reason?: string;
  span?: EvidenceSpan;
  active: boolean;
  onSelect: (path: string | null) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const field = fieldAt(review, path);
  const value = field?.value ?? null;
  const tier = tierFor(score, Boolean(value));

  return (
    <div
      className={`table-row px-5 py-3 transition-colors ${
        active ? "bg-accent-soft" : "hover:bg-ink-50"
      }`}
    >
      <div className="flex items-start gap-4">
        <div className="w-40 shrink-0 pt-0.5 text-xs font-medium text-ink-500">
          {FIELD_LABELS[path] ?? path}
        </div>

        <div className="min-w-0 flex-1">
          {value ? (
            <button
              type="button"
              onClick={() => {
                onSelect(active ? null : path);
                setExpanded((current) => !current);
              }}
              className="block w-full text-left text-sm leading-relaxed text-ink-900"
              title="Show the supporting sentence in the source"
            >
              {value}
            </button>
          ) : (
            <p className="text-sm italic text-ink-400">
              {reason ? explainAbstention(reason) : "Not extracted."}
            </p>
          )}

          {expanded && span && (
            <figure className="mt-2 animate-fade-in">
              <blockquote className="quote">“{span.quote}”</blockquote>
              <figcaption className="mt-1 flex flex-wrap gap-x-3 text-[11px] text-ink-400">
                <span>section: {span.section_name}</span>
                {span.page_no && <span>page {span.page_no}</span>}
                <span>
                  chars {span.char_start.toLocaleString()}–{span.char_end.toLocaleString()}
                </span>
                <span>
                  quote match {percent(span.match_score, 1)}
                  {span.match_score === 1 ? " (verbatim)" : ""}
                </span>
              </figcaption>
            </figure>
          )}
        </div>

        <div className="w-24 shrink-0 text-right">
          {value ? (
            <span className={tier === "grounded" ? "chip-grounded" : "chip-partial"}>
              {percent(score)}
            </span>
          ) : (
            <span className="chip-abstained">withheld</span>
          )}
        </div>
      </div>
    </div>
  );
}
