"use client";

/**
 * Application shell: navigation, the engine status, and the account menu.
 *
 * The engine chip is not decoration. A reader looking at an evidence table needs
 * to know whether it came from a language model or the rule-based baseline, and
 * whether the confidence numbers beside it have actually been calibrated. The
 * chip states both at a glance; its panel carries the full configuration from
 * `GET /config`.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { useAuth } from "@/components/AuthProvider";
import { ChevronIcon, LogoMark } from "@/components/Icons";
import { api } from "@/lib/api";
import type { PublicConfig } from "@/lib/types";

const NAV = [
  { href: "/library", label: "Library", match: ["/library", "/documents"] },
  { href: "/ingest", label: "Add paper", match: ["/ingest"] },
  { href: "/search", label: "Literature search", match: ["/search"] },
  { href: "/evaluation", label: "Evaluation", match: ["/evaluation"] },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { user, signOut } = useAuth();
  const [config, setConfig] = useState<PublicConfig | null>(null);

  useEffect(() => {
    api.config().then(setConfig).catch(() => setConfig(null));
  }, []);

  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-30 bg-canvas/80 backdrop-blur-xl">
        <div className="mx-auto flex max-w-[1440px] flex-wrap items-center justify-between gap-x-6 gap-y-3 px-5 py-4 lg:px-14 lg:py-[22px]">
          <Link href="/library" className="flex items-center gap-2.5">
            <LogoMark />
            <span className="font-display text-[17px] font-bold tracking-[-0.02em]">
              Clinical Evidence
            </span>
          </Link>

          <nav
            aria-label="Primary"
            className="order-3 -mx-1 flex w-full gap-1.5 overflow-x-auto rounded-full bg-white p-[5px] text-[13.5px] font-medium shadow-[0_1px_2px_rgba(17,24,39,.06),0_0_0_1px_#ECEEF3] md:order-none md:mx-0 md:w-auto"
          >
            {NAV.map((item) => {
              const active = item.match.some(
                (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
              );
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={`whitespace-nowrap rounded-full px-4 py-2 transition-colors duration-300 ${
                    active ? "bg-ink-900 text-white" : "text-ink-500 hover:bg-ink-100 hover:text-ink-900"
                  }`}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>

          <div className="flex items-center gap-3">
            {config && <EngineChip config={config} />}
            <AccountMenu email={user?.email ?? ""} onSignOut={signOut} />
          </div>
        </div>
      </header>

      <main
        key={pathname}
        className="mx-auto w-full max-w-[1440px] flex-1 animate-fade-in px-5 pb-10 pt-4 lg:px-14"
      >
        {children}
      </main>

      <footer className="mx-auto w-full max-w-[1440px] px-5 pb-8 text-xs leading-relaxed text-ink-500 lg:px-14">
        Research tooling, not a medical device. Extractions are automated and must be verified
        against the source before use in a review or any clinical decision.
      </footer>
    </div>
  );
}

/** Closes a popover on outside click or Escape. */
function usePopover() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onPointer(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false);
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return { open, setOpen, ref };
}

function EngineChip({ config }: { config: PublicConfig }) {
  const { open, setOpen, ref } = usePopover();
  const offline = config.llm_provider === "offline";
  const engine = offline ? "Rule engine · offline" : config.llm_model;

  const rows: [string, string, boolean?][] = [
    ["Engine", offline ? "rule-based (no API key)" : `${config.llm_provider} · ${config.llm_model}`, offline],
    ["Embeddings", config.embedding_provider],
    ["Prompt", config.prompt_version],
    [
      "Confidence",
      config.confidence_calibrated ? `calibrated (n=${config.calibration_samples})` : "uncalibrated",
      !config.confidence_calibrated,
    ],
    ["Abstain below", config.abstain_threshold.toFixed(2)],
    ["Grounding floor", config.grounding_min_similarity.toFixed(2)],
    ["Evidence window", `${config.max_evidence_chunks} chunks`],
  ];

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="flex items-center gap-2 rounded-full bg-white px-3 py-[7px] text-[12.5px] text-ink-500 shadow-hairline transition-colors hover:text-ink-900"
      >
        <span
          aria-hidden="true"
          className={`h-1.5 w-1.5 rounded-full ${offline ? "bg-partial" : "bg-grounded"}`}
        />
        <span className="hidden sm:inline">{engine}</span>
        {!config.confidence_calibrated && (
          <span className="hidden text-partial-ink lg:inline">· uncalibrated</span>
        )}
        <ChevronIcon size={12} />
      </button>
      {open && (
        <div className="absolute right-0 top-[calc(100%+8px)] z-40 w-72 animate-rise rounded-2xl bg-white p-4 shadow-lift">
          <p className="eyebrow mb-2">Runtime configuration</p>
          <dl className="text-[13px]">
            {rows.map(([label, value, warn]) => (
              <div key={label} className="flex justify-between gap-4 border-t border-ink-100 py-2 first:border-0">
                <dt className="text-ink-500">{label}</dt>
                <dd className={`text-right font-medium ${warn ? "text-partial-ink" : "text-ink-900"}`}>
                  {value}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </div>
  );
}

function AccountMenu({ email, onSignOut }: { email: string; onSignOut: () => void }) {
  const { open, setOpen, ref } = usePopover();
  const initial = (email.trim()[0] ?? "?").toUpperCase();

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        aria-label="Account menu"
        className="flex h-[34px] w-[34px] items-center justify-center rounded-full bg-accent-ring text-[13px] font-semibold text-accent-strong transition-transform duration-300 ease-calm hover:scale-105"
      >
        {initial}
      </button>
      {open && (
        <div className="absolute right-0 top-[calc(100%+8px)] z-40 w-64 animate-rise rounded-2xl bg-white p-2 shadow-lift">
          <p className="truncate px-3 pb-2 pt-2 text-[13px] text-ink-500">{email}</p>
          <button
            type="button"
            onClick={onSignOut}
            className="w-full rounded-xl px-3 py-2.5 text-left text-[13.5px] font-medium text-ink-900 transition-colors hover:bg-ink-100"
          >
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}
