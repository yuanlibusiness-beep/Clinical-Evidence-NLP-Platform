"use client";

/**
 * The quality dashboard.
 *
 * Putting the evaluation numbers inside the product is the point of this page:
 * a reviewer can see what the system currently scores, on which dataset, with
 * which engine, without being asked to take a README's word for it. The
 * synthetic-dataset notice leads the page rather than sitting in a footnote,
 * because a precision figure means nothing without knowing what it was
 * measured on.
 */

import { useCallback, useEffect, useState } from "react";

import { RequireAuth } from "@/components/AuthProvider";
import { ErrorBanner, NoticeBanner } from "@/components/ErrorBanner";
import { CheckIcon } from "@/components/Icons";
import { Segmented } from "@/components/Segmented";
import { Shell } from "@/components/Shell";
import { api, ApiError } from "@/lib/api";
import { shortDate } from "@/lib/format";
import type { EvalRun } from "@/lib/types";

type Tab = "extraction" | "retrieval" | "calibration";
type Metrics = NonNullable<EvalRun["metrics"]>;

/** The same structural gates CI enforces on every push. */
const GATES = [
  { label: "Hallucination rate ≤ 0.05", read: (m: Metrics) => m.extraction.hallucination_rate, pass: (v: number) => v <= 0.05 },
  { label: "Grounded ratio = 1.0", read: (m: Metrics) => m.extraction.grounded_ratio, pass: (v: number) => v >= 0.9999 },
  { label: "Retrieval recall@3 ≥ 0.70", read: (m: Metrics) => m.retrieval["recall@3"], pass: (v: number) => v >= 0.7 },
];

export default function EvaluationPage() {
  return (
    <RequireAuth>
      <Shell>
        <Evaluation />
      </Shell>
    </RequireAuth>
  );
}

function Evaluation() {
  const [runs, setRuns] = useState<EvalRun[] | null>(null);
  const [active, setActive] = useState<EvalRun | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [caseCount, setCaseCount] = useState<number | null>(null);
  const [tab, setTab] = useState<Tab>("extraction");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [list, dataset] = await Promise.all([api.listEvalRuns(), api.describeDataset("gold_v1")]);
      setRuns(list);
      if (list.length > 0) setActive(await api.getEvalRun(list[0].id));
      setCaseCount(dataset.n_cases);
      if (dataset.synthetic) setNotice(dataset.notice);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not load evaluation runs.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function run(kind: "baseline" | "current" | "fit") {
    setBusy(kind);
    setError(null);
    try {
      const result =
        kind === "baseline"
          ? await api.runEval("rule-based baseline", true)
          : kind === "fit"
            ? await api.runEval("calibration fit", false, true)
            : await api.runEval("current engine", false);
      setActive(result);
      setRuns(await api.listEvalRuns());
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Evaluation failed.");
    } finally {
      setBusy(null);
    }
  }

  const metrics = active?.metrics ?? null;

  return (
    <div className="space-y-5">
      <section className="flex animate-rise flex-wrap items-end justify-between gap-4 pt-2">
        <div>
          <h1 className="text-[34px] font-bold tracking-[-0.035em] sm:text-[40px]">Evaluation</h1>
          <p className="mt-2 max-w-2xl text-[15px] text-ink-500">
            The full pipeline, scored against an annotated set. Wrong answers and missing answers are
            counted separately.
          </p>
        </div>
        <div className="flex flex-wrap gap-2.5">
          <button onClick={() => void run("fit")} disabled={busy !== null} className="btn-secondary">
            {busy === "fit" ? "Fitting…" : "Fit calibration"}
          </button>
          <button onClick={() => void run("baseline")} disabled={busy !== null} className="btn-secondary">
            {busy === "baseline" ? "Running…" : "Run baseline"}
          </button>
          <button onClick={() => void run("current")} disabled={busy !== null} className="btn-primary">
            {busy === "current" ? "Running…" : "Run current engine"}
          </button>
        </div>
      </section>

      {error && <ErrorBanner message={error} onDismiss={() => setError(null)} />}

      {notice && (
        <NoticeBanner>
          <b>Synthetic dataset{caseCount ? ` · ${caseCount} cases` : ""}.</b> {notice} Treat these numbers
          as a regression guard, not a benchmark.
        </NoticeBanner>
      )}

      {runs?.length === 0 && !metrics && (
        <div className="surface px-6 py-14 text-center">
          <h2 className="text-xl font-bold tracking-[-0.02em]">No runs yet</h2>
          <p className="mx-auto mt-2 max-w-md text-sm text-ink-500">
            Start with the baseline, so later numbers have a floor to beat.
          </p>
          <button onClick={() => void run("baseline")} disabled={busy !== null} className="btn-primary mt-6">
            Run baseline
          </button>
        </div>
      )}

      {runs === null && !error && (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {[0, 1, 2, 3].map((index) => (
            <div key={index} className="skeleton h-[104px]" />
          ))}
        </div>
      )}

      {metrics && (
        <>
          <section key={active?.id} className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <KpiCard label="Precision" value={metrics.extraction.precision} fill={metrics.extraction.precision} hint="Answered fields that were right" delay={100} />
            <KpiCard label="Recall" value={metrics.extraction.recall} fill={metrics.extraction.recall} hint="Gold fields the engine found" delay={190} />
            <KpiCard
              label="Hallucination rate"
              value={metrics.extraction.hallucination_rate}
              fill={1 - metrics.extraction.hallucination_rate}
              hint="Filled in, though the paper is silent · lower is better"
              tone="green"
              delay={280}
            />
            <KpiCard
              label="Grounded ratio"
              value={metrics.extraction.grounded_ratio}
              fill={metrics.extraction.grounded_ratio}
              hint="Answers matched back to source text"
              tone="green"
              delay={370}
            />
          </section>

          <div className="grid gap-5 xl:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
            <section className="surface min-w-0 animate-rise px-6 py-5" style={{ animationDelay: "200ms" }}>
              <Segmented
                label="Metric group"
                value={tab}
                onChange={setTab}
                className="mb-5"
                options={[
                  { value: "extraction", label: "Extraction" },
                  { value: "retrieval", label: "Retrieval" },
                  { value: "calibration", label: "Calibration" },
                ]}
              />
              <div key={tab} className="animate-fade-in">
                {tab === "extraction" && (
                  <Bars
                    rows={[
                      { label: "F1", hint: "Harmonic mean of precision and recall", value: metrics.extraction.f1 },
                      { label: "Coverage", hint: "Gold fields answered at all", value: metrics.extraction.coverage },
                      { label: "Missed rate", hint: "In the paper, left blank", value: metrics.extraction.missed_rate, tone: "amber" },
                      { label: "Hallucination rate", hint: "Not in the paper, filled in", value: metrics.extraction.hallucination_rate, tone: "green" },
                      { label: "Mean quote match", hint: "Grounding similarity", value: metrics.extraction.mean_match_score },
                    ]}
                  />
                )}
                {tab === "retrieval" && (
                  <Bars
                    rows={[
                      { label: "Recall@3", hint: "Gold evidence in the top three", value: metrics.retrieval["recall@3"] },
                      { label: "nDCG@3", hint: "…and ranked near the top", value: metrics.retrieval["ndcg@3"] },
                      { label: "Effect recall", hint: "Reported estimates recovered", value: metrics.outcomes.effect_recall },
                      { label: "p-value recall", hint: "Reported p-values recovered", value: metrics.outcomes.p_value_recall },
                    ]}
                  />
                )}
                {tab === "calibration" && <Calibration calibration={metrics.calibration} />}
              </div>
            </section>

            <div className="flex min-w-0 flex-col gap-5">
              <section className="surface-flat animate-rise px-[22px] py-5" style={{ animationDelay: "260ms" }}>
                <h2 className="mb-3.5 text-base font-bold">CI quality gates</h2>
                {GATES.map((gate) => {
                  const value = gate.read(metrics);
                  const pass = gate.pass(value);
                  return (
                    <div key={gate.label} className="flex items-center justify-between border-t border-ink-100 py-2.5">
                      <span className="flex items-center gap-2.5 text-[13.5px]">
                        <span
                          aria-hidden="true"
                          className={`flex h-[22px] w-[22px] items-center justify-center rounded-full ${
                            pass ? "bg-grounded-soft text-grounded-ink" : "bg-[#FEF2F2] text-[#B42318]"
                          }`}
                        >
                          {pass ? <CheckIcon size={11} /> : <span className="text-xs font-bold">!</span>}
                        </span>
                        {gate.label}
                      </span>
                      <span className={`text-[13px] font-semibold ${pass ? "text-grounded-ink" : "text-[#B42318]"}`}>
                        {value.toFixed(3)}
                        <span className="sr-only">{pass ? " passes" : " fails"}</span>
                      </span>
                    </div>
                  );
                })}
              </section>

              <section className="surface-flat animate-rise px-[22px] py-5" style={{ animationDelay: "320ms" }}>
                <div className="mb-1.5 flex items-center justify-between">
                  <h2 className="text-base font-bold">Misattribution rate</h2>
                  <span className="chip-accent">Not yet measured</span>
                </div>
                <p className="text-[13px] leading-relaxed text-ink-700">
                  Answers whose quote is real but answers a different question — the error grounding
                  cannot catch. Measuring it needs annotations on real papers; the synthetic set cannot
                  show it.
                </p>
              </section>

              <section className="surface-flat animate-rise px-[22px] py-5" style={{ animationDelay: "380ms" }}>
                <h2 className="mb-2.5 text-base font-bold">Run history</h2>
                <div className="flex max-h-72 flex-col gap-1 overflow-y-auto">
                  {(runs ?? []).map((item) => {
                    const selected = active?.id === item.id;
                    const f1 = item.metrics?.extraction?.f1;
                    return (
                      <button
                        key={item.id}
                        type="button"
                        onClick={() => api.getEvalRun(item.id).then(setActive).catch(() => undefined)}
                        className={`flex items-center justify-between gap-3 rounded-[14px] px-3.5 py-3 text-left transition-colors duration-300 ${
                          selected ? "bg-accent-soft" : "hover:bg-ink-100"
                        }`}
                      >
                        <span className="flex min-w-0 flex-col gap-0.5">
                          <span className="truncate text-[13.5px] font-semibold">
                            {item.name} · {item.model}
                          </span>
                          <span className="text-xs text-ink-500">
                            {item.dataset} · {item.n_cases} cases · {shortDate(item.created_at)}
                          </span>
                        </span>
                        {typeof f1 === "number" && (
                          <span className="shrink-0 font-display text-[15px] font-bold">F1 {f1.toFixed(3)}</span>
                        )}
                      </button>
                    );
                  })}
                </div>
              </section>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function KpiCard({
  label,
  value,
  fill,
  hint,
  tone = "blue",
  delay,
}: {
  label: string;
  value: number;
  fill: number;
  hint: string;
  tone?: "blue" | "green";
  delay: number;
}) {
  const circumference = 2 * Math.PI * 28;
  const clamped = Math.max(0, Math.min(1, fill));
  return (
    <article
      className="flex animate-rise items-center gap-4 rounded-[22px] bg-white px-[22px] py-5 shadow-[0_1px_2px_rgba(17,24,39,.05),0_0_0_1px_#ECEEF3] transition-[transform,box-shadow] duration-500 ease-calm hover:-translate-y-[3px] hover:shadow-lift"
      style={{ animationDelay: `${delay}ms` }}
    >
      <svg width="64" height="64" viewBox="0 0 64 64" aria-hidden="true" className="shrink-0 -rotate-90">
        <circle cx="32" cy="32" r="28" fill="none" stroke="#EEF0F5" strokeWidth="6" />
        <circle
          cx="32"
          cy="32"
          r="28"
          fill="none"
          stroke={tone === "green" ? "#2F9E66" : "#3554D1"}
          strokeWidth="6"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - clamped)}
          style={{ animation: `ring-in 1.6s cubic-bezier(.16,1,.3,1) ${delay}ms both` }}
        />
      </svg>
      <div className="flex min-w-0 flex-col gap-0.5">
        <span className="text-[12.5px] font-semibold text-ink-500">{label}</span>
        <span className="font-display text-[30px] font-bold tracking-[-0.03em]">{value.toFixed(3)}</span>
        <span className="text-xs leading-snug text-ink-500">{hint}</span>
      </div>
    </article>
  );
}

function Bars({
  rows,
}: {
  rows: { label: string; hint: string; value: number; tone?: "amber" | "green" }[];
}) {
  return (
    <div className="flex flex-col gap-4">
      {rows.map((row, index) => (
        <div key={row.label} className="grid grid-cols-[minmax(0,180px)_minmax(0,1fr)_64px] items-center gap-4 sm:grid-cols-[200px_minmax(0,1fr)_64px]">
          <span className="flex flex-col gap-0.5">
            <span className="text-sm font-semibold">{row.label}</span>
            <span className="text-xs text-ink-500">{row.hint}</span>
          </span>
          <span aria-hidden="true" className="h-2.5 overflow-hidden rounded-full bg-ink-150">
            <span
              className={`block h-full origin-left animate-grow rounded-full ${
                row.tone === "amber" ? "bg-partial" : row.tone === "green" ? "bg-grounded" : "bg-accent"
              }`}
              style={{ width: `${Math.max(row.value * 100, 1.5)}%`, animationDelay: `${index * 90}ms` }}
            />
          </span>
          <span className="text-right font-display text-[17px] font-bold">{row.value.toFixed(3)}</span>
        </div>
      ))}
    </div>
  );
}

/**
 * Reliability diagram: stated confidence (x) against observed accuracy (y).
 * Points above the diagonal are under-confident, below it over-confident; the
 * dot area is proportional to how many fields fell in that bin.
 */
function Calibration({ calibration }: { calibration: Metrics["calibration"] }) {
  const bins = calibration.bins.filter((bin) => bin.count > 0);
  const total = bins.reduce((sum, bin) => sum + bin.count, 0) || 1;
  const meanConfidence = bins.reduce((sum, bin) => sum + bin.confidence * bin.count, 0) / total;
  const meanAccuracy = bins.reduce((sum, bin) => sum + bin.accuracy * bin.count, 0) / total;
  const maxCount = Math.max(1, ...bins.map((bin) => bin.count));
  const gap = meanAccuracy - meanConfidence;
  const verdict =
    Math.abs(gap) < 0.05 ? "Well calibrated" : gap > 0 ? "Under-confident" : "Over-confident";

  const size = 280;
  const pad = 30;
  const plot = size - pad * 2;
  const px = (value: number) => pad + value * plot;
  const py = (value: number) => size - pad - value * plot;

  return (
    <div className="grid items-center gap-7 md:grid-cols-[280px_minmax(0,1fr)]">
      <svg
        viewBox={`0 0 ${size} ${size}`}
        className="w-full max-w-[280px] rounded-2xl bg-[#F8F9FC]"
        role="img"
        aria-label={`Reliability diagram: mean stated confidence ${meanConfidence.toFixed(2)}, observed accuracy ${meanAccuracy.toFixed(2)}`}
      >
        <path d={`M${pad} ${size - pad}H${size - pad}M${pad} ${size - pad}V${pad}`} stroke="#DDE1E8" strokeWidth="1.5" />
        <path d={`M${pad} ${size - pad}L${size - pad} ${pad}`} stroke="#C3C8D2" strokeWidth="1.5" strokeDasharray="5 5" />
        {[0, 0.5, 1].map((tick) => (
          <g key={tick} fontSize="10" fill="#5B6472">
            {tick !== 0.5 && (
              <text x={px(tick)} y={size - 14} textAnchor="middle">
                {tick}
              </text>
            )}
            <text x={14} y={py(tick) + 3} textAnchor="middle">
              {tick}
            </text>
          </g>
        ))}
        <text x={pad + 6} y={pad - 12} fontSize="10" fill="#5B6472">
          observed accuracy ↑
        </text>
        {bins.map((bin, index) => (
          <circle
            key={bin.bin_low}
            cx={px(bin.confidence)}
            cy={py(bin.accuracy)}
            r={5 + 7 * Math.sqrt(bin.count / maxCount)}
            fill="#3554D1"
            fillOpacity=".85"
            stroke="#fff"
            strokeWidth="3"
            className="origin-center animate-pop [transform-box:fill-box]"
            style={{ animationDelay: `${300 + index * 90}ms` }}
          >
            <title>
              {`${bin.bin_low.toFixed(1)}–${bin.bin_high.toFixed(1)}: stated ${bin.confidence.toFixed(2)}, observed ${bin.accuracy.toFixed(2)}, ${bin.count} fields`}
            </title>
          </circle>
        ))}
        <text x={size / 2} y={size - 14} textAnchor="middle" fontSize="10" fill="#5B6472">
          stated confidence →
        </text>
      </svg>
      <div className="flex flex-col gap-3.5">
        <h3 className="text-xl font-bold tracking-[-0.02em]">{verdict}</h3>
        <p className="text-sm leading-relaxed text-ink-700">
          Across {calibration.n_samples} answered fields the engine states{" "}
          <b>{meanConfidence.toFixed(2)}</b> on average and is right <b>{meanAccuracy.toFixed(2)}</b> of the
          time. Points above the dashed line are under-confident; below it, over-confident.
          {!calibration.scaler_fitted &&
            " A fitted scaler corrects this on data it has seen — reporting that fitted error on the same run would be training error, so it is not shown here."}
        </p>
        <div className="flex flex-wrap gap-2">
          <span className={calibration.ece > 0.1 ? "chip-partial" : "chip-grounded"}>ECE {calibration.ece.toFixed(3)}</span>
          <span className="chip-abstained">Brier {calibration.brier.toFixed(3)}</span>
          <span className="chip-abstained">{calibration.scaler_fitted ? "Scaler fitted" : "Scaler not fitted"}</span>
        </div>
      </div>
    </div>
  );
}
