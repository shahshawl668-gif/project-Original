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
        glow: "0 0 0 1px rgb(99 102 241 / 0.1), 0 16px 56px -12px rgb(99 102 241 / 0.45)",
        ring: "0 0 0 1px rgb(15 23 42 / 0.06)",
      },
      backgroundImage: {
        "hero-mesh":
          "radial-gradient(at 22% 18%, rgba(124,58,237,0.55) 0px, transparent 50%), radial-gradient(at 82% 12%, rgba(59,130,246,0.45) 0px, transparent 50%), radial-gradient(at 60% 80%, rgba(236,72,153,0.38) 0px, transparent 60%)",
        "premium-gradient":
          "linear-gradient(135deg, #4f46e5 0%, #7c3aed 40%, #ec4899 100%)",
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
        brand: {
          50: "#eef2ff",
          100: "#e0e7ff",
          200: "#c7d2fe",
          300: "#a5b4fc",
          400: "#818cf8",
          500: "#6366f1",
          600: "#4f46e5",
          700: "#4338ca",
          800: "#3730a3",
          900: "#312e81",
          950: "#1e1b4b",
        },
        accent: {
          50: "#fdf4ff",
          100: "#fae8ff",
          400: "#c084fc",
          500: "#a855f7",
          600: "#9333ea",
          700: "#7e22ce",
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
