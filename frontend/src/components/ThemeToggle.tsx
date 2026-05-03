"use client";

import { motion, AnimatePresence } from "framer-motion";
import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "@/providers/ThemeProvider";

export function ThemeToggle({ className = "" }: { className?: string }) {
  const { theme, toggle } = useTheme();
  const Icon = theme === "light" ? Sun : theme === "dark" ? Moon : Monitor;
  const label =
    theme === "light" ? "Light mode" : theme === "dark" ? "Dark mode" : "System mode";

  return (
    <button
      type="button"
      onClick={toggle}
      title={`${label} — click to cycle`}
      className={`group relative inline-flex h-9 w-9 items-center justify-center overflow-hidden rounded-lg border border-ink-200/70 bg-white text-ink-600 transition-colors hover:bg-ink-50 hover:text-ink-900 dark:border-white/10 dark:bg-white/[0.04] dark:text-ink-200 dark:hover:bg-white/[0.08] dark:hover:text-white ${className}`}
      aria-label={label}
    >
      <AnimatePresence mode="wait" initial={false}>
        <motion.span
          key={theme}
          initial={{ opacity: 0, scale: 0.6, rotate: -30 }}
          animate={{ opacity: 1, scale: 1, rotate: 0 }}
          exit={{ opacity: 0, scale: 0.6, rotate: 30 }}
          transition={{ duration: 0.18 }}
          className="absolute inset-0 flex items-center justify-center"
        >
          <Icon size={15} strokeWidth={2} />
        </motion.span>
      </AnimatePresence>
    </button>
  );
}
