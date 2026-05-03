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
      if (res.ok) setStatus({ kind: "ok", via: res.via === "none" ? "direct" : res.via });
      else setStatus({ kind: "fail", detail: res.detail || "API unreachable" });
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (status.kind === "loading") {
    return (
      <span className="inline-flex items-center gap-2 rounded-full bg-white/[0.04] px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-ink-300 ring-1 ring-white/10">
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-ink-400" />
        Checking
      </span>
    );
  }

  if (status.kind === "ok") {
    return (
      <span className="inline-flex items-center gap-2 rounded-full bg-success-500/15 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-success-400 ring-1 ring-success-500/30">
        <span className="relative flex h-1.5 w-1.5">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-success-400 opacity-75" />
          <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-success-400" />
        </span>
        API live · {status.via}
      </span>
    );
  }

  return (
    <span
      title={status.detail}
      className="inline-flex items-center gap-2 rounded-full bg-danger-500/15 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-danger-400 ring-1 ring-danger-500/30"
    >
      <span className="h-1.5 w-1.5 rounded-full bg-danger-400" />
      API offline
    </span>
  );
}
