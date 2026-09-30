"use client";

import { useEffect } from "react";

/**
 * Warn before unsaved changes are lost — only when there are some.
 *
 * Covers closing or reloading the tab (the browser's own prompt) and leaving
 * through a link inside the product (one confirmation). Nothing is asked when
 * the page is clean, and nothing is asked twice.
 */
export function useUnsavedChanges(dirty: boolean, message = "You have unsaved changes. Leave without saving them?") {
  useEffect(() => {
    if (!dirty) return;
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    const onClick = (e: MouseEvent) => {
      if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      const a = (e.target as HTMLElement | null)?.closest?.("a[href]") as HTMLAnchorElement | null;
      if (!a || a.target === "_blank" || a.hasAttribute("download")) return;
      const url = new URL(a.href, window.location.href);
      if (url.origin !== window.location.origin) return;
      if (url.pathname === window.location.pathname && url.search === window.location.search) return;
      if (!window.confirm(message)) {
        e.preventDefault();
        e.stopPropagation();
      }
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    document.addEventListener("click", onClick, true);
    return () => {
      window.removeEventListener("beforeunload", onBeforeUnload);
      document.removeEventListener("click", onClick, true);
    };
  }, [dirty, message]);
}

export type Change = { field: string; before: unknown; after: unknown };

function sameNumber(a: unknown, b: unknown): boolean {
  if (a === null || b === null || a === undefined || b === undefined || a === "" || b === "") return false;
  const x = Number(a);
  const y = Number(b);
  return Number.isFinite(x) && Number.isFinite(y) && x === y;
}

/** Leaf-by-leaf differences between two plain objects; "0.0050" equals "0.005". */
export function diffObjects(before: unknown, after: unknown, path = "", out: Change[] = []): Change[] {
  const isObj = (v: unknown) => v !== null && typeof v === "object" && !Array.isArray(v);
  if (isObj(before) && isObj(after)) {
    const b = before as Record<string, unknown>;
    const a = after as Record<string, unknown>;
    for (const key of Array.from(new Set([...Object.keys(b), ...Object.keys(a)])).sort()) {
      diffObjects(b[key], a[key], path ? `${path}.${key}` : key, out);
    }
  } else if (JSON.stringify(before) !== JSON.stringify(after) && !sameNumber(before, after)) {
    out.push({ field: path, before, after });
  }
  return out;
}
