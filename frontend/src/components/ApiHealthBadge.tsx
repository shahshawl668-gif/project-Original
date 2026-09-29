"use client";

import { useEffect, useState } from "react";
import { probeApiHealth } from "@/lib/api";

type Status =
  | { kind: "loading" }
  | { kind: "ok"; via: "proxy" | "direct" }
  | { kind: "fail"; detail: string };

/** Whether the API answered on page load. Quiet when it did; plain when it did not. */
export function ApiHealthBadge() {
  const [status, setStatus] = useState<Status>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const res = await probeApiHealth();
      if (cancelled) return;
      if (res.ok) setStatus({ kind: "ok", via: res.via === "none" ? "direct" : res.via });
      else setStatus({ kind: "fail", detail: res.detail || "API unreachable" });
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const [dot, text, title] =
    status.kind === "loading"
      ? ["bg-ink-300 animate-pulse-soft", "Checking service…", undefined]
      : status.kind === "ok"
        ? ["bg-success-500", "Service available", `Connected (${status.via})`]
        : ["bg-danger-500", "Service unreachable", status.detail];

  return (
    <span role="status" title={title} className="inline-flex items-center gap-2 px-1 text-xs text-ink-500">
      <span className={`h-1.5 w-1.5 rounded-full ${dot}`} aria-hidden />
      <span className={status.kind === "fail" ? "font-medium text-danger-700" : undefined}>{text}</span>
    </span>
  );
}
