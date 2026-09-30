"use client";

import type { ReactNode } from "react";

/**
 * Route content appears without travelling.
 *
 * This used to remount every page behind a 320 ms fade-and-lift keyed on the
 * path, so changing a filter that touched the URL, or going back to a table,
 * replayed the entrance and threw away scroll and component state. A plain
 * 160 ms opacity fade on first paint is all the motion a working screen needs,
 * and it does not re-run on re-render.
 */
export function PageTransition({ children }: { children: ReactNode }) {
  return <div className="animate-fade-in">{children}</div>;
}
