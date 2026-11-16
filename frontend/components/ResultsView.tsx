"use client";

/**
 * Reported results.
 *
 * Ratio estimates with a parseable interval are drawn as a forest plot — log
 * axis, a reference line at 1, the interval as a bar and the estimate as a dot —
 * because that is how a clinical reader compares results, and an interval that
 * crosses 1 is visible before any number is read. Everything else (differences,
 * percentages, results without an interval) is listed with its numbers. Direction
 * is written in words and intervals crossing the null are greyed, never colour
 * alone.
 */

import { isRatioMeasure, parseEstimate, parseInterval } from "@/lib/format";
import type { Outcome } from "@/lib/types";

const DIRECTION_LABEL: Record<string, string> = {
  favours_intervention: "favours intervention",
  favours_comparison: "favours comparator",
  no_difference: "no difference",
};

interface Plotted {
  index: number;
  outcome: Outcome;
  estimate: number;
  low: number;
  high: number;
}

export function ResultsView({
  outcomes,
  activeField,
  onSelectField,
}: {
  outcomes: Outcome[];
  activeField: string | null;
  onSelectField: (path: string | null) => void;
}) {
  const reported = outcomes
    .map((outcome, index) => ({ outcome, index }))
    .filter(({ outcome }) => !outcome.name.startsWith("[withheld]"));

  if (reported.length === 0) {
    return (
      <p className="px-3.5 py-10 text-center text-sm text-ink-500">
        No result met the evidence bar. A row is only shown when its statistics can be traced to a
        sentence in the source.
      </p>
    );
  }

  const plotted: Plotted[] = [];
  const listed: { outcome: Outcome; index: number }[] = [];
  for (const item of reported) {
    const estimate = parseEstimate(item.outcome.effect_size);
    const interval = parseInterval(item.outcome.confidence_interval);
    if (isRatioMeasure(item.outcome.measure) && estimate !== null && estimate > 0 && interval && interval[0] > 0) {
      plotted.push({ ...item, estimate, low: interval[0], high: interval[1] });
    } else {
      listed.push(item);
    }
  }

  return (
    <div className="flex flex-col gap-5">
      {plotted.length > 0 && (
        <ForestPlot rows={plotted} activeField={activeField} onSelectField={onSelectField} />
      )}
      {listed.length > 0 && (
        <div className="flex flex-col gap-1">
          {plotted.length > 0 && <p className="eyebrow px-3.5 pb-1">Other reported results</p>}
          {listed.map(({ outcome, index }, position) => {
            const path = `outcomes[${index}]`;
            return (
              <button
                key={path}
                type="button"
                data-active={activeField === path}
                onClick={() => onSelectField(activeField === path ? null : path)}
                className="select-row grid animate-rise grid-cols-[minmax(0,1fr)_auto] items-center gap-4 px-3.5 py-3 text-left"
                style={{ animationDelay: `${position * 70}ms` }}
              >
                <span className="flex min-w-0 flex-col gap-0.5">
                  <KindLabel kind={outcome.kind} />
                  <span className="text-[13.5px] font-medium">{outcome.name}</span>
                  {outcome.direction && (
                    <span className="text-xs text-ink-500">{DIRECTION_LABEL[outcome.direction]}</span>
                  )}
                </span>
                <span className="text-right text-[13px] text-ink-700">
                  {outcome.measure && <span className="block text-xs text-ink-500">{outcome.measure}</span>}
                  <b className="font-display text-base text-ink-900">{outcome.effect_size ?? "—"}</b>
                  {outcome.confidence_interval && <> ({outcome.confidence_interval.replace(/^95%\s*CI\s*/i, "")})</>}
                  {outcome.p_value && <span className="ml-1.5 text-ink-500">{outcome.p_value}</span>}
                </span>
              </button>
            );
          })}
        </div>
      )}
      <p className="px-3.5 text-[12.5px] leading-relaxed text-ink-500">
        Estimates as reported by the authors. The platform does not pool, adjust or re-analyse.
      </p>
    </div>
  );
}

function KindLabel({ kind }: { kind: Outcome["kind"] }) {
  return (
    <span
      className={`text-[11px] font-semibold uppercase tracking-[0.06em] ${
        kind === "primary" ? "text-accent" : kind === "safety" ? "text-partial-ink" : "text-ink-500"
      }`}
    >
      {kind}
    </span>
  );
}

const CANDIDATE_TICKS = [0.1, 0.25, 0.5, 0.75, 1, 1.5, 2, 3, 5, 10];

function ForestPlot({
  rows,
  activeField,
  onSelectField,
}: {
  rows: Plotted[];
  activeField: string | null;
  onSelectField: (path: string | null) => void;
}) {
  const min = Math.min(1, ...rows.map((row) => row.low)) / 1.2;
  const max = Math.max(1, ...rows.map((row) => row.high)) * 1.2;
  const logMin = Math.log(min);
  const span = Math.log(max) - logMin;
  const x = (value: number) => ((Math.log(value) - logMin) / span) * 100;
  const ticks = CANDIDATE_TICKS.filter((tick) => tick > min && tick < max);

  return (
    <div>
      <div className="flex flex-wrap justify-between gap-2 px-3.5 pb-3 text-xs text-ink-500">
        <span>Ratio with 95% CI · log scale</span>
        <span>← favours intervention · favours comparator →</span>
      </div>
      <div className="relative">
        {rows.map((row, position) => {
          const path = `outcomes[${row.index}]`;
          const crossesNull = row.low <= 1 && row.high >= 1;
          const color = crossesNull ? "bg-abstained" : "bg-accent";
          return (
            <button
              key={path}
              type="button"
              data-active={activeField === path}
              onClick={() => onSelectField(activeField === path ? null : path)}
              className="select-row grid w-full data-[active=true]:translate-x-0 grid-cols-[132px_minmax(0,1fr)_118px] items-center gap-3 py-3 text-left sm:grid-cols-[200px_minmax(0,1fr)_170px]"
            >
              <span className="flex min-w-0 flex-col gap-0.5 pl-3.5">
                <KindLabel kind={row.outcome.kind} />
                <span className="text-[13.5px] font-medium leading-snug">{row.outcome.name}</span>
              </span>
              <span aria-hidden="true" className="relative h-[30px]">
                <span className="absolute inset-y-0 w-px bg-ink-300" style={{ left: `${x(1)}%` }} />
                <span
                  className={`absolute top-[14px] h-0.5 origin-center animate-grow rounded-sm ${color}`}
                  style={{
                    left: `${x(row.low)}%`,
                    width: `${x(row.high) - x(row.low)}%`,
                    animationDelay: `${position * 110}ms`,
                  }}
                />
                <span
                  className={`absolute top-[9px] h-3 w-3 -translate-x-1/2 animate-pop rounded-full shadow-[0_0_0_4px_#fff] ${color}`}
                  style={{ left: `${x(row.estimate)}%`, animationDelay: `${350 + position * 110}ms` }}
                />
              </span>
              <span className="whitespace-nowrap pr-3.5 text-right text-[13px] text-ink-700">
                <b className="font-display text-base text-ink-900">{row.estimate.toFixed(2)}</b> (
                {row.low.toFixed(2)}–{row.high.toFixed(2)})
                {row.outcome.p_value && (
                  <span className="block text-xs text-ink-500">{row.outcome.p_value}</span>
                )}
                <span className="sr-only">
                  {crossesNull ? " — interval crosses 1, no clear difference" : ""}
                </span>
              </span>
            </button>
          );
        })}
        <div
          aria-hidden="true"
          className="grid h-7 grid-cols-[132px_minmax(0,1fr)_118px] gap-3 sm:grid-cols-[200px_minmax(0,1fr)_170px]"
        >
          <span />
          <span className="relative text-[11px] text-ink-500">
            {ticks.map((tick) => (
              <span key={tick} className="absolute top-1.5 -translate-x-1/2" style={{ left: `${x(tick)}%` }}>
                {tick}
              </span>
            ))}
          </span>
          <span />
        </div>
      </div>
    </div>
  );
}
