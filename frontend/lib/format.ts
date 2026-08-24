/** Small presentation helpers shared across components. */

import type { EvidenceReview, ExtractedField } from "./types";

/** Human labels for the dotted field paths the backend uses. */
export const FIELD_LABELS: Record<string, string> = {
  "pico.population": "Population",
  "pico.intervention": "Intervention",
  "pico.comparison": "Comparison",
  "pico.outcome": "Outcome",
  "design.design": "Study design",
  "design.randomised": "Randomised",
  "design.blinding": "Blinding",
  "design.setting": "Setting",
  "design.duration": "Duration / follow-up",
  "design.registration_id": "Registration",
  "population.sample_size": "Sample size",
  "population.age": "Age",
  "population.sex_distribution": "Sex distribution",
  "population.inclusion_criteria": "Inclusion criteria",
  "population.exclusion_criteria": "Exclusion criteria",
  limitations: "Limitations",
  conclusion: "Conclusion",
  funding: "Funding",
};

export const FIELD_GROUPS: { title: string; hint: string; paths: string[] }[] = [
  {
    title: "PICO",
    hint: "The question the study answers.",
    paths: ["pico.population", "pico.intervention", "pico.comparison", "pico.outcome"],
  },
  {
    title: "Design",
    hint: "How much weight the evidence can carry.",
    paths: [
      "design.design",
      "design.randomised",
      "design.blinding",
      "design.setting",
      "design.duration",
      "design.registration_id",
    ],
  },
  {
    title: "Population detail",
    hint: "Who the finding applies to.",
    paths: [
      "population.sample_size",
      "population.age",
      "population.sex_distribution",
      "population.inclusion_criteria",
      "population.exclusion_criteria",
    ],
  },
  {
    title: "Interpretation",
    hint: "What the authors themselves claim.",
    paths: ["limitations", "conclusion", "funding"],
  },
];

/** Resolve a dotted path such as `pico.population` against a review payload. */
export function fieldAt(review: EvidenceReview | null, path: string): ExtractedField | null {
  if (!review) return null;
  const parts = path.split(".");
  let current: unknown = review;
  for (const part of parts) {
    if (current === null || typeof current !== "object") return null;
    current = (current as Record<string, unknown>)[part];
  }
  if (current && typeof current === "object" && "value" in (current as object)) {
    return current as ExtractedField;
  }
  return null;
}

export type ConfidenceTier = "grounded" | "partial" | "abstained";

export function tierFor(confidence: number | undefined, hasValue: boolean): ConfidenceTier {
  if (!hasValue) return "abstained";
  if ((confidence ?? 0) >= 0.7) return "grounded";
  return "partial";
}

export function percent(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

/** Turn an abstention reason code into something a reviewer can act on. */
export function explainAbstention(reason: string): string {
  if (reason.startsWith("low_confidence")) {
    const score = reason.match(/\(([\d.]+)\)/)?.[1];
    return score
      ? `Withheld — confidence ${(Number(score) * 100).toFixed(0)}% is below the threshold.`
      : "Withheld — below the confidence threshold.";
  }
  switch (reason) {
    case "not_reported":
      return "The paper does not report this.";
    case "no_quote":
      return "Withheld — the engine gave no supporting quote.";
    case "ungrounded":
      return "Withheld — the quote could not be matched in the source text.";
    default:
      return reason;
  }
}

export function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export function truncate(text: string, limit: number): string {
  return text.length <= limit ? text : `${text.slice(0, limit).trimEnd()}…`;
}
