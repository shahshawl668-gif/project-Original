"use client";

import { useEffect, useState } from "react";
import { probeApiHealth } from "@/lib/api";

type Status =
  | { kind: "loading" }
  | { kind: "ok"; via: "proxy" | "direct" }
  | { kind: "fail"; detail: string };

export function ApiHealthBadge() {
  const [status, setStatus] = useState<Status>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const res = await probeApiHealth();
      if (cancelled) return;
      if (res.ok) {
        setStatus({ kind: "ok", via: res.via === "none" ? "direct" : res.via });
      } else {
        setStatus({ kind: "fail", detail: res.detail || "API unreachable" });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (status.kind === "loading") {
    return (
      <span className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-500">
        <span className="h-2 w-2 animate-pulse rounded-full bg-slate-400" />
        Checking API…
      </span>
    );
  }

  if (status.kind === "ok") {
    const colour =
      status.via === "proxy"
        ? "bg-emerald-50 text-emerald-700 border-emerald-200"
        : "bg-amber-50 text-amber-700 border-amber-200";
    return (
      <span className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium ${colour}`}>
        <span className="h-2 w-2 rounded-full bg-current" />
        API: {status.via === "proxy" ? "proxy ✓" : "direct ✓"}
      </span>
    );
  }

  return (
    <span
      title={status.detail}
      className="inline-flex items-center gap-2 rounded-full border border-red-200 bg-red-50 px-3 py-1 text-xs font-medium text-red-700"
    >
      <span className="h-2 w-2 rounded-full bg-red-500" />
      API unreachable
    </span>
  );
}
