"use client";

/**
 * The evidence table — the product's main surface.
 *
 * Design rules:
 * 1. A blank cell must look *deliberate*. Every row without a value says why,
 *    in the same visual weight as a value, so the reader learns to trust the
 *    blanks rather than suspect them.
 * 2. No number without its evidence. Selecting a row focuses the source reader
 *    on the exact sentence, so verifying a cell is one click.
 * 3. A machine answer is a draft until a person has checked it. Each answered
 *    row carries a verification toggle; the page header counts them.
 */

import { CheckIcon } from "@/components/Icons";
import { FIELD_GROUPS, FIELD_LABELS, explainAbstention, fieldAt } from "@/lib/format";
import type { EvidenceReview } from "@/lib/types";

interface Props {
  review: EvidenceReview | null;
  confidence: Record<string, number> | null;
  abstentions: Record<string, string> | null;
  activeField: string | null;
  onSelectField: (path: string | null) => void;
  verified: Set<string>;
  onToggleVerified: (path: string) => void;
}

export function EvidenceTable({
  review,
  confidence,
  abstentions,
  activeField,
  onSelectField,
  verified,
  onToggleVerified,
}: Props) {
  let index = 0;
  return (
    <div className="flex flex-col">
      {FIELD_GROUPS.map((group) => (
        <section key={group.title} aria-label={group.title}>
          <div className="flex items-baseline justify-between px-3.5 pb-1 pt-3">
            <h3 className="eyebrow font-sans">{group.title}</h3>
            <span className="hidden text-[11.5px] text-ink-400 sm:inline">{group.hint}</span>
          </div>
          {group.paths.map((path) => {
            index += 1;
            return (
              <Row
                key={path}
                path={path}
                review={review}
                score={confidence?.[path]}
                reason={abstentions?.[path]}
                active={activeField === path}
                verified={verified.has(path)}
                delay={120 + index * 35}
                onSelect={onSelectField}
                onToggleVerified={onToggleVerified}
              />
            );
          })}
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
  active,
  verified,
  delay,
  onSelect,
  onToggleVerified,
}: {
  path: string;
  review: EvidenceReview | null;
  score?: number;
  reason?: string;
  active: boolean;
  verified: boolean;
  delay: number;
  onSelect: (path: string | null) => void;
  onToggleVerified: (path: string) => void;
}) {
  const value = fieldAt(review, path)?.value ?? null;
  const label = FIELD_LABELS[path] ?? path;

  let chip: React.ReactNode = null;
  if (review && value) {
    const strong = (score ?? 0) >= 0.7;
    chip = (
      <span className={strong ? "chip-grounded" : "chip-partial"}>
        {score !== undefined ? `${Math.round(score * 100)}%` : "—"}
      </span>
    );
  } else if (review) {
    chip = <span className="chip-abstained">Withheld</span>;
  }

  return (
    <div
      data-active={active}
      className="select-row grid animate-rise grid-cols-[minmax(0,1fr)_auto_32px] items-center gap-3 py-[3px] pr-1.5"
      style={{ animationDelay: `${delay}ms` }}
    >
      <button
        type="button"
        onClick={() => onSelect(active ? null : path)}
        aria-pressed={active}
        className="grid grid-cols-1 items-center gap-1 rounded-[14px] py-2 pl-3.5 text-left sm:grid-cols-[136px_minmax(0,1fr)] sm:gap-3.5"
      >
        <span className="text-[12.5px] font-medium text-ink-500">{label}</span>
        {value ? (
          <span className="text-sm leading-[1.45] text-ink-900">{value}</span>
        ) : (
          <span className="text-[13.5px] leading-[1.45] text-ink-400">
            {review === null ? "Not run yet." : reason ? explainAbstention(reason) : "Not extracted."}
          </span>
        )}
      </button>
      <span>{chip}</span>
      {review && value ? (
        <button
          type="button"
          onClick={() => onToggleVerified(path)}
          aria-pressed={verified}
          aria-label={`${verified ? "Unmark" : "Mark"} ${label} as verified`}
          title={verified ? "Verified by you" : "Mark as verified against the source"}
          className={`flex h-7 w-7 items-center justify-center rounded-[9px] transition-[background-color,box-shadow,transform] duration-300 ease-calm active:scale-90 ${
            verified
              ? "bg-grounded text-white"
              : "bg-white text-ink-300 shadow-[inset_0_0_0_1.5px_#D5DAE3] hover:text-grounded"
          }`}
        >
          <CheckIcon size={13} />
        </button>
      ) : (
        <span />
      )}
    </div>
  );
}
