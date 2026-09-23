import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  darkMode: "class",
  theme: {
    extend: {
      fontFamily: {
        sans: ["var(--font-sans)", "Inter", "system-ui", "sans-serif"],
        display: ["var(--font-display)", "Inter", "system-ui", "sans-serif"],
      },
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem" }],
      },
      letterSpacing: {
        tightest: "-0.04em",
      },
      borderRadius: {
        xl2: "1.25rem",
        "3xl": "1.5rem",
      },
      boxShadow: {
        soft: "0 1px 2px rgb(15 23 42 / 0.04), 0 4px 16px rgb(15 23 42 / 0.06)",
        card: "0 1px 0 rgb(15 23 42 / 0.05), 0 12px 32px rgb(15 23 42 / 0.06)",
        elevated:
          "0 1px 0 rgb(15 23 42 / 0.04), 0 18px 48px rgb(15 23 42 / 0.08), 0 1px 2px rgb(15 23 42 / 0.05)",
        glow: "0 0 0 1px rgb(14 165 233 / 0.12), 0 16px 56px -12px rgb(14 165 233 / 0.35)",
        ring: "0 0 0 1px rgb(15 23 42 / 0.06)",
      },
      backgroundImage: {
        "hero-mesh":
          "radial-gradient(at 20% 15%, rgba(14,165,233,0.30) 0px, transparent 55%), radial-gradient(at 80% 10%, rgba(56,189,248,0.24) 0px, transparent 55%), radial-gradient(at 60% 85%, rgba(2,132,199,0.18) 0px, transparent 60%)",
        "premium-gradient":
          "linear-gradient(135deg, #0284c7 0%, #0ea5e9 45%, #38bdf8 100%)",
        "noise":
          "url(\"data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.5'/%3E%3C/svg%3E\")",
      },
      colors: {
        ink: {
          50: "#f7f8fa",
          100: "#eceef3",
          200: "#d6dae3",
          300: "#aab1c1",
          400: "#7c8597",
          500: "#5b6478",
          600: "#3f475a",
          700: "#2c3242",
          800: "#1b2030",
          900: "#0e1220",
          950: "#070912",
        },
        // Sky blue on white. 600 is the action colour: it clears 4.5:1 against
        // white for button text, which 500 does not, so the darker step is the
        // one that gets used for anything a person has to read.
        brand: {
          50: "#f0f9ff",
          100: "#e0f2fe",
          200: "#bae6fd",
          300: "#7dd3fc",
          400: "#38bdf8",
          500: "#0ea5e9",
          600: "#0284c7",
          700: "#0369a1",
          800: "#075985",
          900: "#0c4a6e",
          950: "#082f49",
        },
        // A cooler neighbour rather than a contrast. Used sparingly — on white,
        // two loud colours read as two priorities.
        accent: {
          50: "#ecfeff",
          100: "#cffafe",
          400: "#22d3ee",
          500: "#06b6d4",
          600: "#0891b2",
          700: "#0e7490",
        },
        success: {
          50: "#f0fdf4",
          400: "#4ade80",
          500: "#22c55e",
          600: "#16a34a",
          700: "#15803d",
        },
        danger: {
          50: "#fef2f2",
          400: "#f87171",
          500: "#ef4444",
          600: "#dc2626",
          700: "#b91c1c",
        },
        warning: {
          50: "#fffbeb",
          400: "#fbbf24",
          500: "#f59e0b",
          600: "#d97706",
          700: "#b45309",
        },
      },
      keyframes: {
        "fade-in": {
          "0%": { opacity: "0", transform: "translateY(4px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(12px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
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
          "0%": { opacity: "0", transform: "translateX(-8px)" },
          "100%": { opacity: "1", transform: "translateX(0)" },
        },
        marquee: {
          "0%": { transform: "translateX(0%)" },
          "100%": { transform: "translateX(-50%)" },
        },
      },
      animation: {
        "fade-in": "fade-in 0.32s ease-out both",
        "fade-up": "fade-up 0.42s cubic-bezier(0.4, 0, 0.2, 1) both",
        shimmer: "shimmer 2s linear infinite",
        "pulse-soft": "pulse-soft 2.4s ease-in-out infinite",
        "slide-in": "slide-in 0.3s ease-out both",
        marquee: "marquee 40s linear infinite",
      },
    },
  },
  plugins: [],
};

export default config;
