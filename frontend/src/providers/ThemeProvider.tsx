"use client";

/**
 * The product is light-only.
 *
 * This used to resolve a stored preference, fall back to the operating
 * system's, and toggle `dark` on `<html>`. Removing the toggle button from the
 * header did not remove that behaviour: the provider stayed mounted, read the
 * phone's dark-mode setting on mount, and put the class straight back after the
 * boot script had cleared it — so anyone whose device was in dark mode got a
 * dark canvas behind white cards.
 *
 * Kept as a provider rather than deleted because a couple of components ask it
 * which theme is in force — the Monaco editor picks its own colours, and the
 * cost charts theirs. They now get one answer, always.
 */

import { createContext, useCallback, useContext, useMemo } from "react";

export type Theme = "light";
export type ResolvedTheme = "light";

type Ctx = {
  theme: Theme;
  resolved: ResolvedTheme;
  setTheme: (t: Theme) => void;
  toggle: () => void;
};

const ThemeContext = createContext<Ctx | null>(null);

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const noop = useCallback(() => {}, []);
  const value = useMemo<Ctx>(
    () => ({ theme: "light", resolved: "light", setTheme: noop, toggle: noop }),
    [noop],
  );
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used inside ThemeProvider");
  return ctx;
}
