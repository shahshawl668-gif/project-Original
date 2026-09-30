import type { Config } from "tailwindcss";

/**
 * Design tokens.
 *
 * One typeface, one action colour, a neutral canvas, hairline borders, and
 * status colours that mean exactly one thing each. Everything a page draws
 * should come from here; a page that needs a colour this file does not have is
 * usually saying something the design has not decided yet.
 *
 * Radii are tightened in place (`rounded-xl`, `rounded-2xl`) rather than
 * renamed, so the whole product moves together instead of page by page.
 */
const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["var(--font-sans)", "Inter", "system-ui", "sans-serif"],
        // One family. Headings differ by weight and size, not by typeface.
        display: ["var(--font-sans)", "Inter", "system-ui", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem" }],
      },
      letterSpacing: {
        tightest: "-0.03em",
      },
      borderRadius: {
        md: "0.375rem",
        lg: "0.5rem",
        xl: "0.625rem",
        "2xl": "0.75rem",
        "3xl": "1rem",
        xl2: "0.75rem",
      },
      boxShadow: {
        // Surfaces sit on the canvas with a border and the faintest lift.
        soft: "0 1px 2px rgb(16 24 40 / 0.04)",
        card: "0 1px 2px rgb(16 24 40 / 0.04)",
        // Only things that float above the page — menus, drawers, dialogs.
        elevated: "0 12px 32px -8px rgb(16 24 40 / 0.16), 0 2px 6px rgb(16 24 40 / 0.06)",
        glow: "0 1px 2px rgb(16 24 40 / 0.04)",
        ring: "0 0 0 1px rgb(16 24 40 / 0.06)",
      },
      colors: {
        ink: {
          50: "#f7f8fa",
          100: "#eef0f3",
          200: "#dfe2e8",
          300: "#b7bdc9",
          // 400 is for borders, placeholders, disabled states and icons —
          // never text a person must read (3.1:1 on white). Text starts at 500.
          400: "#8a93a4",
          500: "#636c7e",
          600: "#474f61",
          700: "#323949",
          800: "#1f2533",
          900: "#111522",
          950: "#080a12",
        },
        // Sky blue on white. 600 is the action colour and is set so that white
        // button text on it, and it as text on white, the canvas or brand-50,
        // all clear 4.5:1 (5.0, 4.67, 4.69). The stock sky-600 (#0284c7) only
        // reached 4.1 — an axe pass caught it — so this step is darker.
        brand: {
          50: "#f0f9ff",
          100: "#e0f2fe",
          200: "#bae6fd",
          300: "#7dd3fc",
          400: "#38bdf8",
          500: "#0ea5e9",
          600: "#0275b3",
          700: "#0369a1",
          800: "#075985",
          900: "#0c4a6e",
          950: "#082f49",
        },
        accent: {
          50: "#ecfeff",
          100: "#cffafe",
          200: "#a5f3fc",
          300: "#67e8f9",
          400: "#22d3ee",
          500: "#06b6d4",
          600: "#0891b2",
          700: "#0e7490",
        },
        // Status colours carry meaning and nothing else: passed, failed,
        // needs attention. Full scales so a tinted border or a dark label
        // always exists (several pages asked for 200s that were not defined).
        success: {
          50: "#f0fdf4",
          100: "#dcfce7",
          200: "#bbf7d0",
          300: "#86efac",
          400: "#4ade80",
          500: "#22c55e",
          600: "#16a34a",
          700: "#15803d",
          800: "#166534",
          900: "#14532d",
          950: "#052e16",
        },
        danger: {
          50: "#fef2f2",
          100: "#fee2e2",
          200: "#fecaca",
          300: "#fca5a5",
          400: "#f87171",
          500: "#ef4444",
          600: "#dc2626",
          700: "#b91c1c",
          800: "#991b1b",
          900: "#7f1d1d",
          950: "#450a0a",
        },
        warning: {
          50: "#fffbeb",
          100: "#fef3c7",
          200: "#fde68a",
          300: "#fcd34d",
          400: "#fbbf24",
          500: "#f59e0b",
          600: "#d97706",
          700: "#b45309",
          800: "#92400e",
          900: "#78350f",
          950: "#451a03",
        },
      },
      transitionDuration: {
        DEFAULT: "160ms",
        fast: "120ms",
        base: "160ms",
        slow: "220ms",
      },
      transitionTimingFunction: {
        DEFAULT: "cubic-bezier(0.2, 0, 0, 1)",
        out: "cubic-bezier(0.2, 0, 0, 1)",
      },
      keyframes: {
        "fade-in": {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(4px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "slide-in-right": {
          "0%": { transform: "translateX(16px)", opacity: "0" },
          "100%": { transform: "translateX(0)", opacity: "1" },
        },
        shimmer: {
          "0%": { backgroundPosition: "-1000px 0" },
          "100%": { backgroundPosition: "1000px 0" },
        },
        "pulse-soft": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.6" },
        },
        "slide-in": {
          "0%": { opacity: "0", transform: "translateX(-4px)" },
          "100%": { opacity: "1", transform: "translateX(0)" },
        },
        indeterminate: {
          "0%": { transform: "translateX(-100%)" },
          "100%": { transform: "translateX(250%)" },
        },
        marquee: {
          "0%": { transform: "translateX(0%)" },
          "100%": { transform: "translateX(-50%)" },
        },
      },
      animation: {
        "fade-in": "fade-in 160ms cubic-bezier(0.2, 0, 0, 1) both",
        "fade-up": "fade-up 180ms cubic-bezier(0.2, 0, 0, 1) both",
        "slide-in-right": "slide-in-right 220ms cubic-bezier(0.2, 0, 0, 1) both",
        shimmer: "shimmer 2s linear infinite",
        "pulse-soft": "pulse-soft 2.4s ease-in-out infinite",
        "slide-in": "slide-in 160ms cubic-bezier(0.2, 0, 0, 1) both",
        indeterminate: "indeterminate 1.4s cubic-bezier(0.4, 0, 0.2, 1) infinite",
        marquee: "marquee 40s linear infinite",
      },
    },
  },
  plugins: [],
};

export default config;
