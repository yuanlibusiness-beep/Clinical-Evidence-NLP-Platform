"use client";

/**
 * The quality dashboard.
 *
 * Putting the evaluation numbers inside the product is the point of this page:
 * a reviewer can see what the system currently scores, on which dataset, with
 * which engine, without being asked to take a README's word for it. The
 * synthetic-dataset notice is shown prominently rather than buried, because a
 * precision figure means nothing without knowing what it was measured on.
 */

import { useCallback, useEffect, useState } from "react";

import { RequireAuth } from "@/components/AuthProvider";
import { ErrorBanner } from "@/components/ErrorBanner";
import { Shell } from "@/components/Shell";
import { api, ApiError } from "@/lib/api";
import { formatDate, percent } from "@/lib/format";
import type { EvalRun } from "@/lib/types";

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
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [list, dataset] = await Promise.all([
        api.listEvalRuns(),
        api.describeDataset("gold_v1"),
      ]);
      setRuns(list);
      if (list.length > 0) setActive(await api.getEvalRun(list[0].id));
      if (dataset.synthetic) setNotice(dataset.notice);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not load evaluation runs.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function run(ruleEngine: boolean) {
    setBusy(true);
    setError(null);
    try {
      const result = await api.runEval(
        ruleEngine ? "rule-based baseline" : "LLM engine",
        ruleEngine,
      );
      setActive(result);
      setRuns(await api.listEvalRuns());
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Evaluation failed.");
    } finally {
      setBusy(false);
    }
  }

  const metrics = active?.metrics;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-lg font-semibold tracking-tight text-ink-900">Evaluation</h1>
          <p className="mt-1 max-w-2xl text-sm text-ink-500">
            The harness runs the full pipeline — sectioning, chunking, retrieval, extraction,
            grounding, calibration — over an annotated set, so a regression anywhere shows up
            here rather than in a user&apos;s review.
          </p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => void run(true)} disabled={busy} className="btn-secondary">
            Run baseline
          </button>
          <button onClick={() => void run(false)} disabled={busy} className="btn-primary">
            {busy ? "Running…" : "Run current engine"}
          </button>
        </div>
      </div>

      {error && <ErrorBanner message={error} onDismiss={() => setError(null)} />}

      {notice && (
        <div className="rounded-lg border border-partial-ring bg-partial-soft px-4 py-3 text-xs leading-relaxed text-amber-900">
          <span className="font-semibold">Synthetic dataset. </span>
          {notice}
        </div>
      )}

      {metrics && (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <MetricCard
              label="Precision"
              value={percent(metrics.extraction.precision, 1)}
              hint="of the fields it answered, how many were right"
            />
            <MetricCard
              label="Recall"
              value={percent(metrics.extraction.recall, 1)}
              hint="of the fields the paper reports, how many it found"
            />
            <MetricCard
              label="Hallucination rate"
              value={percent(metrics.extraction.hallucination_rate, 1)}
              hint="answered a field the paper does not report"
              invert
            />
            <MetricCard
              label="Calibration error"
              value={metrics.calibration.ece.toFixed(3)}
              hint="gap between stated confidence and observed accuracy"
              invert
            />
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            <Panel title="Extraction" rows={[
              ["F1", metrics.extraction.f1.toFixed(3)],
              ["Coverage", percent(metrics.extraction.coverage, 1)],
              ["Missed rate", percent(metrics.extraction.missed_rate, 1)],
              ["Grounded ratio", percent(metrics.extraction.grounded_ratio, 1)],
              ["Mean quote match", metrics.extraction.mean_match_score.toFixed(3)],
            ]} />
            <Panel title="Retrieval" rows={[
              ["Recall@3", metrics.retrieval["recall@3"].toFixed(3)],
              ["nDCG@3", metrics.retrieval["ndcg@3"].toFixed(3)],
              ["Outcome effect recall", metrics.outcomes.effect_recall.toFixed(3)],
              ["Outcome p-value recall", metrics.outcomes.p_value_recall.toFixed(3)],
            ]} />
            <Panel title="Run" rows={[
              ["Engine", `${active?.provider} · ${active?.model}`],
              ["Dataset", active?.dataset ?? "—"],
              ["Cases", String(active?.n_cases ?? 0)],
              ["Brier score", metrics.calibration.brier.toFixed(3)],
              ["Scaler fitted", metrics.calibration.scaler_fitted ? "yes" : "no"],
            ]} />
          </div>

          <ReliabilityDiagram bins={metrics.calibration.bins} />
        </>
      )}

      {runs && runs.length > 0 && (
        <div className="card overflow-hidden">
          <div className="card-header">
            <h3 className="text-sm font-semibold text-ink-900">Run history</h3>
          </div>
          <div className="divide-y divide-ink-100">
            {runs.map((item) => (
              <button
                key={item.id}
                onClick={() => api.getEvalRun(item.id).then(setActive).catch(() => undefined)}
                className={`flex w-full items-center gap-4 px-5 py-3 text-left text-xs hover:bg-ink-50 ${
                  active?.id === item.id ? "bg-accent-soft" : ""
                }`}
              >
                <span className="flex-1 font-medium text-ink-800">{item.name}</span>
                <span className="text-ink-500">{item.provider}</span>
                <span className="text-ink-500">{item.n_cases} cases</span>
                <span className="text-ink-400">{formatDate(item.created_at)}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {runs?.length === 0 && (
        <div className="card p-10 text-center text-sm text-ink-500">
          No runs yet. Start with the baseline so later numbers have a floor to beat.
        </div>
      )}
    </div>
  );
}

function MetricCard({
  label,
  value,
  hint,
  invert,
}: {
  label: string;
  value: string;
  hint: string;
  invert?: boolean;
}) {
  return (
    <div className="card p-5">
      <p className="text-[11px] uppercase tracking-wide text-ink-400">{label}</p>
      <p className={`mt-1 text-2xl font-semibold ${invert ? "text-partial" : "text-ink-900"}`}>
        {value}
      </p>
      <p className="mt-1 text-[11px] leading-relaxed text-ink-500">{hint}</p>
    </div>
  );
}

function Panel({ title, rows }: { title: string; rows: [string, string][] }) {
  return (
    <div className="card">
      <div className="card-header">
        <h3 className="text-sm font-semibold text-ink-900">{title}</h3>
      </div>
      <dl className="px-5 py-3 text-xs">
        {rows.map(([label, value]) => (
          <div key={label} className="flex justify-between border-b border-ink-100 py-2 last:border-0">
            <dt className="text-ink-500">{label}</dt>
            <dd className="font-medium text-ink-800">{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

/**
 * Reliability diagram: stated confidence (x) against observed accuracy (y).
 * A well-calibrated system sits on the diagonal; bars below it are
 * over-confident, bars above it are under-confident.
 */
function ReliabilityDiagram({
  bins,
}: {
  bins: { bin_low: number; bin_high: number; count: number; confidence: number; accuracy: number }[];
}) {
  const populated = bins.filter((bin) => bin.count > 0);
  if (populated.length === 0) return null;

  return (
    <div className="card">
      <div className="card-header">
        <h3 className="text-sm font-semibold text-ink-900">Reliability</h3>
        <p className="text-[11px] text-ink-400">stated confidence vs observed accuracy</p>
      </div>
      <div className="px-5 py-5">
        <div className="flex h-44 items-end gap-1.5">
          {bins.map((bin, index) => (
            <div key={index} className="flex flex-1 flex-col items-center gap-1">
              <div className="relative flex h-full w-full items-end">
                <div
                  className="w-full rounded-t bg-accent/80"
                  style={{ height: `${Math.max(bin.accuracy * 100, bin.count ? 2 : 0)}%` }}
                  title={`accuracy ${(bin.accuracy * 100).toFixed(0)}% over ${bin.count} fields`}
                />
                <div
                  className="absolute w-full border-t-2 border-dashed border-partial"
                  style={{ bottom: `${bin.confidence * 100}%` }}
                  title={`mean stated confidence ${(bin.confidence * 100).toFixed(0)}%`}
                />
              </div>
              <span className="text-[9px] text-ink-400">{bin.bin_low.toFixed(1)}</span>
            </div>
          ))}
        </div>
        <div className="mt-3 flex gap-4 text-[11px] text-ink-500">
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-2 w-4 rounded-sm bg-accent/80" /> observed accuracy
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-0 w-4 border-t-2 border-dashed border-partial" /> stated
            confidence
          </span>
        </div>
      </div>
    </div>
  );
}
