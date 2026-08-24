"use client";

/**
 * Reported results, one row per outcome.
 *
 * `direction` is shown as a word, never as a colour alone — "favours
 * intervention" on a green pill would let a reader take the finding at a glance
 * without seeing the confidence interval next to it, which is exactly the
 * mistake an evidence table should make harder, not easier.
 */

import { percent } from "@/lib/format";
import type { Outcome } from "@/lib/types";

const KIND_STYLE: Record<string, string> = {
  primary: "chip bg-accent-soft text-accent",
  secondary: "chip-abstained",
  safety: "chip-partial",
};

const DIRECTION_LABEL: Record<string, string> = {
  favours_intervention: "favours intervention",
  favours_comparison: "favours comparator",
  no_difference: "no difference",
};

export function OutcomeTable({ outcomes }: { outcomes: Outcome[] }) {
  const reported = outcomes.filter((outcome) => !outcome.name.startsWith("[withheld]"));

  if (reported.length === 0) {
    return (
      <div className="card p-6">
        <h3 className="text-sm font-semibold text-ink-900">Reported results</h3>
        <p className="mt-2 text-sm italic text-ink-400">
          No result met the evidence bar. A row is only shown when its statistics can be
          traced to a sentence in the source.
        </p>
      </div>
    );
  }

  return (
    <div className="card overflow-hidden">
      <div className="card-header">
        <h3 className="text-sm font-semibold text-ink-900">Reported results</h3>
        <p className="text-[11px] text-ink-400">{reported.length} extracted</p>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-ink-100 text-[11px] uppercase tracking-wide text-ink-400">
              <th className="px-5 py-2 font-medium">Outcome</th>
              <th className="px-3 py-2 font-medium">Measure</th>
              <th className="px-3 py-2 font-medium">Effect</th>
              <th className="px-3 py-2 font-medium">95% CI</th>
              <th className="px-3 py-2 font-medium">p</th>
              <th className="px-5 py-2 text-right font-medium">Confidence</th>
            </tr>
          </thead>
          <tbody>
            {reported.map((outcome, index) => (
              <tr key={index} className="table-row align-top">
                <td className="px-5 py-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={KIND_STYLE[outcome.kind] ?? "chip-abstained"}>
                      {outcome.kind}
                    </span>
                    <span className="text-ink-900">{outcome.name}</span>
                  </div>
                  {outcome.direction && (
                    <p className="mt-1 text-[11px] text-ink-500">
                      {DIRECTION_LABEL[outcome.direction] ?? outcome.direction}
                    </p>
                  )}
                  {outcome.quote && (
                    <blockquote className="quote mt-2">“{outcome.quote}”</blockquote>
                  )}
                </td>
                <td className="px-3 py-3 text-ink-600">{outcome.measure ?? "—"}</td>
                <td className="px-3 py-3 font-mono text-[13px] text-ink-900">
                  {outcome.effect_size ?? "—"}
                </td>
                <td className="px-3 py-3 font-mono text-[13px] text-ink-600">
                  {outcome.confidence_interval ?? "—"}
                </td>
                <td className="px-3 py-3 font-mono text-[13px] text-ink-600">
                  {outcome.p_value ?? "—"}
                </td>
                <td className="px-5 py-3 text-right">
                  <span
                    className={outcome.confidence >= 0.7 ? "chip-grounded" : "chip-partial"}
                  >
                    {percent(outcome.confidence)}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
