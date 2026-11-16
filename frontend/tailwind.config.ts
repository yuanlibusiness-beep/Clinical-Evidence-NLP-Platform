import type { Config } from "tailwindcss";

/**
 * Design tokens — "Calm".
 *
 * Neutral canvas, white surfaces, one blue accent. Colour is still spent almost
 * entirely on epistemic status: `grounded` (a verified quote, green), `partial`
 * (grounded but low confidence, amber) and `abstained` (deliberately withheld,
 * neutral). The accent marks what the reader is acting on — the selected tab,
 * the active field, the primary action — and nothing else.
 *
 * Motion has one curve, `ease-calm` (a fast-out, long-settle cubic), used for
 * every transform; colour and opacity changes use a plain ease. That single
 * curve is what makes the interface feel coherent rather than busy.
 */
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "#F6F7FA",
        ink: {
          50: "#F6F7FA",
          100: "#F1F3F8",
          150: "#ECEEF3",
          200: "#E4E7EE",
          300: "#C3C8D2",
          400: "#6B7280",
          500: "#5B6472",
          600: "#4B5563",
          700: "#374151",
          800: "#1F2937",
          900: "#111827",
        },
        accent: {
          DEFAULT: "#3554D1",
          strong: "#2541B2",
          soft: "#EEF2FF",
          mark: "#E8EDFF",
          ring: "#DCE3FF",
          ink: "#16205A",
        },
        grounded: { DEFAULT: "#2F9E66", ink: "#1F6B45", soft: "#E7F6EE" },
        partial: { DEFAULT: "#E0912F", ink: "#8A4B0F", soft: "#FDF1E2" },
        abstained: { DEFAULT: "#9AA1AD", ink: "#5B6472", soft: "#F1F3F8" },
        notice: { DEFAULT: "#FFF7EB", line: "#F6DFBC", ink: "#6B4210", icon: "#9A5B13" },
      },
      fontFamily: {
        sans: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "PingFang SC",
          "Microsoft YaHei",
          "sans-serif",
        ],
        display: ["Manrope", "Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      borderRadius: {
        "2.5xl": "20px",
        "4xl": "28px",
      },
      boxShadow: {
        hairline: "0 0 0 1px #ECEEF3",
        card: "0 1px 2px rgba(17,24,39,.05), 0 24px 48px -28px rgba(23,32,72,.18)",
        lift: "0 1px 2px rgba(17,24,39,.05), 0 22px 44px -24px rgba(23,32,72,.32)",
        pill: "0 8px 18px -8px rgba(53,84,209,.75), 0 1px 2px rgba(17,24,39,.15)",
        cta: "0 12px 24px -10px rgba(53,84,209,.6)",
        focus: "0 0 0 2px #3554D1, 0 0 0 6px rgba(53,84,209,.15)",
      },
      transitionTimingFunction: {
        calm: "cubic-bezier(.16,1,.3,1)",
      },
      keyframes: {
        rise: {
          from: { opacity: "0", transform: "translateY(14px) scale(.985)" },
          to: { opacity: "1", transform: "none" },
        },
        "fade-in": { from: { opacity: "0" }, to: { opacity: "1" } },
        pop: {
          "0%": { opacity: "0", transform: "scale(.6)" },
          "60%": { opacity: "1", transform: "scale(1.08)" },
          "100%": { transform: "scale(1)" },
        },
        grow: { from: { transform: "scaleX(0)" }, to: { transform: "scaleX(1)" } },
        shimmer: { from: { transform: "translateX(-100%)" }, to: { transform: "translateX(250%)" } },
        breathe: { "0%, 100%": { opacity: ".45" }, "50%": { opacity: "1" } },
        float: { "0%, 100%": { transform: "translateY(0)" }, "50%": { transform: "translateY(-6px)" } },
        mark: { from: { backgroundSize: "0% 100%" }, to: { backgroundSize: "100% 100%" } },
      },
      animation: {
        rise: "rise .9s cubic-bezier(.16,1,.3,1) both",
        "fade-in": "fade-in .4s ease both",
        pop: "pop .5s cubic-bezier(.16,1,.3,1) both",
        grow: "grow 1.1s cubic-bezier(.16,1,.3,1) both",
        shimmer: "shimmer 1.6s cubic-bezier(.45,0,.55,1) infinite",
        breathe: "breathe 1.8s ease-in-out infinite",
        float: "float 3.2s ease-in-out infinite",
        mark: "mark 1.2s cubic-bezier(.16,1,.3,1) both",
      },
    },
  },
  plugins: [],
};

export default config;
