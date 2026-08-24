"use client";

/**
 * Application shell: navigation plus the configuration strip.
 *
 * The strip is not decoration. A reader looking at an evidence table needs to
 * know whether it came from a language model or the rule-based baseline, and
 * whether the confidence numbers beside it have actually been calibrated. Both
 * facts come from `GET /config` and are shown on every page.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { useAuth } from "@/components/AuthProvider";
import { api } from "@/lib/api";
import type { PublicConfig } from "@/lib/types";

const NAV = [
  { href: "/library", label: "Library" },
  { href: "/ingest", label: "Add paper" },
  { href: "/search", label: "Literature search" },
  { href: "/evaluation", label: "Evaluation" },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { user, signOut } = useAuth();
  const [config, setConfig] = useState<PublicConfig | null>(null);

  useEffect(() => {
    api.config().then(setConfig).catch(() => setConfig(null));
  }, []);

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 border-b border-ink-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center gap-6 px-4 py-3">
          <Link href="/library" className="flex items-baseline gap-2">
            <span className="text-sm font-semibold tracking-tight text-ink-900">
              Clinical Evidence NLP
            </span>
            <span className="hidden text-[11px] text-ink-400 sm:inline">
              source-grounded evidence review
            </span>
          </Link>

          <nav className="flex flex-1 items-center gap-1">
            {NAV.map((item) => {
              const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`rounded-lg px-3 py-1.5 text-sm transition-colors ${
                    active
                      ? "bg-accent-soft font-medium text-accent"
                      : "text-ink-600 hover:bg-ink-100"
                  }`}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>

          <div className="flex items-center gap-3">
            <span className="hidden text-xs text-ink-500 md:inline">{user?.email}</span>
            <button onClick={signOut} className="btn-ghost text-xs">
              Sign out
            </button>
          </div>
        </div>

        {config && (
          <div className="border-t border-ink-100 bg-ink-50">
            <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-5 gap-y-1 px-4 py-1.5 text-[11px] text-ink-500">
              <ConfigItem
                label="engine"
                value={
                  config.llm_provider === "offline"
                    ? "rule-based (no API key)"
                    : `${config.llm_model}`
                }
                warn={config.llm_provider === "offline"}
              />
              <ConfigItem label="embeddings" value={config.embedding_provider} />
              <ConfigItem label="prompt" value={config.prompt_version} />
              <ConfigItem
                label="confidence"
                value={
                  config.confidence_calibrated
                    ? `calibrated (n=${config.calibration_samples})`
                    : "uncalibrated"
                }
                warn={!config.confidence_calibrated}
              />
              <ConfigItem label="abstain below" value={config.abstain_threshold.toFixed(2)} />
            </div>
          </div>
        )}
      </header>

      <main className="mx-auto max-w-7xl px-4 py-8">{children}</main>

      <footer className="mx-auto max-w-7xl px-4 pb-10 text-[11px] leading-relaxed text-ink-400">
        Research tooling, not a medical device. Extractions are automated and must be
        verified against the source before use in a review or any clinical decision.
      </footer>
    </div>
  );
}

function ConfigItem({ label, value, warn }: { label: string; value: string; warn?: boolean }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className="uppercase tracking-wide text-ink-400">{label}</span>
      <span className={warn ? "font-medium text-partial" : "font-medium text-ink-600"}>
        {value}
      </span>
    </span>
  );
}
