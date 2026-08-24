import type { Config } from "tailwindcss";

/**
 * Palette notes
 *
 * The product's job is to make a reader trust — or distrust — a specific cell in
 * an evidence table. So colour is spent almost entirely on epistemic status:
 * `grounded` (a verified quote), `partial` (grounded but low confidence), and
 * `abstained` (deliberately withheld). Everything else stays neutral slate so
 * those three read instantly.
 */
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        ink: {
          50: "#f8fafc",
          100: "#f1f5f9",
          200: "#e2e8f0",
          300: "#cbd5e1",
          400: "#94a3b8",
          500: "#64748b",
          600: "#475569",
          700: "#334155",
          800: "#1e293b",
          900: "#0f172a",
          950: "#020617",
        },
        grounded: { DEFAULT: "#0d9488", soft: "#ccfbf1", ring: "#5eead4" },
        partial: { DEFAULT: "#b45309", soft: "#fef3c7", ring: "#fcd34d" },
        abstained: { DEFAULT: "#64748b", soft: "#f1f5f9", ring: "#cbd5e1" },
        accent: { DEFAULT: "#4f46e5", soft: "#eef2ff" },
      },
      fontFamily: {
        sans: ["ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      keyframes: {
        "fade-in": {
          from: { opacity: "0", transform: "translateY(4px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        "pulse-soft": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.55" },
        },
      },
      animation: {
        "fade-in": "fade-in 180ms ease-out",
        "pulse-soft": "pulse-soft 1.4s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};

export default config;
