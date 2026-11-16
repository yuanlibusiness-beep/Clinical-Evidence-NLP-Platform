"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { useAuth } from "@/components/AuthProvider";
import { LogoMark } from "@/components/Icons";
import { Segmented } from "@/components/Segmented";
import { ApiError } from "@/lib/api";

type Mode = "login" | "register";

export default function LoginPage() {
  const { user, ready, signIn, signUp } = useAuth();
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (ready && user) router.replace("/library");
  }, [ready, user, router]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (mode === "login") await signIn(email, password);
      else await signUp(email, password, fullName || undefined);
      router.replace("/library");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  const signingIn = mode === "login";

  return (
    <div className="grid min-h-screen bg-canvas lg:grid-cols-[1.1fr_1fr]">
      <section className="flex flex-col justify-between gap-12 px-6 py-10 sm:px-12 lg:px-[72px] lg:py-14">
        <div className="flex items-center gap-2.5">
          <LogoMark />
          <span className="font-display text-[17px] font-bold tracking-[-0.02em]">
            Clinical Evidence
          </span>
        </div>

        <div className="max-w-[560px] animate-rise">
          <h1 className="text-[40px] font-bold leading-[1.05] tracking-[-0.04em] sm:text-[52px]">
            Every answer, traced to the sentence it came from.
          </h1>
          <p className="mt-5 text-[17px] leading-relaxed text-ink-600">
            Structured evidence tables from clinical papers. Each field carries its verbatim
            source — and stays blank when the paper does not say.
          </p>

          <figure
            className="mt-10 animate-rise rounded-2.5xl bg-white px-[22px] py-5 shadow-card"
            style={{ animationDelay: "300ms" }}
          >
            <div className="mb-2.5 flex items-center justify-between">
              <span className="text-[12.5px] font-semibold text-ink-500">Sample size</span>
              <span className="chip-grounded">Grounded · verbatim</span>
            </div>
            <div className="font-display text-[26px] font-bold tracking-[-0.02em]">6,425</div>
            <blockquote className="mt-3 text-sm leading-[1.7] text-ink-700">
              “
              <span className="marker" style={{ animationDelay: "900ms" }}>
                A total of 2104 patients were assigned to receive dexamethasone and 4321 to
                receive usual care.
              </span>
              ”
            </blockquote>
            <figcaption className="mt-2 text-xs text-ink-500">
              Example · RECOVERY trial, abstract results
            </figcaption>
          </figure>
        </div>

        <p className="text-[12.5px] text-ink-500">
          Research tooling, not a medical device. Verify every extraction against the source.
        </p>
      </section>

      <section className="flex items-center justify-center px-6 pb-14 lg:p-12">
        <form
          onSubmit={submit}
          className="w-full max-w-[420px] animate-rise rounded-4xl bg-white p-8 shadow-[0_1px_2px_rgba(17,24,39,.05),0_32px_64px_-32px_rgba(23,32,72,.28)] sm:p-9"
          style={{ animationDelay: "120ms" }}
        >
          <Segmented
            label="Account"
            size="lg"
            className="mb-7 flex w-full"
            value={mode}
            onChange={(next) => {
              setMode(next);
              setError(null);
            }}
            options={[
              { value: "login", label: "Sign in" },
              { value: "register", label: "Create account" },
            ]}
          />

          <h2 className="text-2xl font-bold tracking-[-0.02em]">
            {signingIn ? "Welcome back" : "Create your account"}
          </h2>
          <p className="mb-6 mt-1.5 text-sm text-ink-500">
            {signingIn
              ? "Sign in to your evidence library."
              : "Your papers and reviews stay private to you."}
          </p>

          <div className="flex flex-col gap-4">
            {!signingIn && (
              <label className="label animate-rise">
                Name <span className="sr-only">(optional)</span>
                <input
                  className="input"
                  value={fullName}
                  onChange={(event) => setFullName(event.target.value)}
                  autoComplete="name"
                  placeholder="Optional"
                />
              </label>
            )}
            <label className="label">
              Email
              <input
                type="email"
                required
                className="input"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                autoComplete="email"
                placeholder="you@university.ac.uk"
              />
            </label>
            <label className="label">
              Password
              <input
                type="password"
                required
                minLength={8}
                className="input"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete={signingIn ? "current-password" : "new-password"}
                placeholder="At least 8 characters"
              />
            </label>
          </div>

          {error && (
            <p
              role="alert"
              className="mt-4 animate-rise rounded-xl bg-[#FEF2F2] px-4 py-3 text-[13.5px] text-[#7A1D14]"
            >
              {error}
            </p>
          )}

          <button type="submit" disabled={busy} className="btn-primary mt-6 h-[50px] w-full rounded-[14px] text-[15px]">
            {busy ? "Working…" : signingIn ? "Sign in" : "Create account"}
          </button>
          <p className="mt-4 text-center text-[12.5px] leading-relaxed text-ink-500">
            Runs fully offline with the rule engine. No API key needed.
          </p>
        </form>
      </section>
    </div>
  );
}
