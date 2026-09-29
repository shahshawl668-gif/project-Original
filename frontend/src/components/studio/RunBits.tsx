"use client";

import Link from "next/link";
import { ArrowRight, CheckCircle2, XCircle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { STATUS_LABEL, STATUS_VARIANT, runTitle, type Connection, type Counts, type Run, type RunStatus } from "@/lib/studio";

export function StatusBadge({ status }: { status: RunStatus }) {
  return <Badge variant={STATUS_VARIANT[status]}>{STATUS_LABEL[status] ?? status}</Badge>;
}

export function RunLine({ run }: { run: Run }) {
  return (
    <li className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
      <Link href={`/studio/runs/${run.id}`} className="min-w-0 font-medium text-brand-700 hover:underline">
        {runTitle(run)}{run.source.batch_id && run.kind !== "workflow" ? ` · ${run.source.batch_id}` : ""}
      </Link>
      <span className="flex items-center gap-2 text-xs text-ink-500">
        {run.counts ? `${run.counts.rejected ?? 0} rejected of ${run.counts.received ?? 0}` : null}
        <StatusBadge status={run.status} />
      </span>
    </li>
  );
}

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

const n = (v: number | null | undefined) => (v ?? 0).toLocaleString("en-IN");

/**
 * Received → accepted / rejected / skipped → created / updated / unchanged.
 *
 * With the two identities every import must satisfy shown as checks, so a
 * reader can see that nothing went missing between the ends — or that
 * something did.
 */
export function CountsFunnel({ counts }: { counts: Counts }) {
  const received = counts.received ?? 0;
  const accepted = counts.accepted ?? 0;
  const split = accepted + (counts.rejected ?? 0) + (counts.skipped ?? 0);
  const stored = (counts.created ?? 0) + (counts.updated ?? 0) + (counts.unchanged ?? 0);
  const firstOk = received === split;
  const secondOk = accepted === 0 || accepted === stored;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-stretch gap-2 text-center">
        <Box label="Received" value={n(received)} />
        <Arrow />
        <div className="flex flex-wrap gap-2">
          <Box label="Accepted" value={n(accepted)} tone="ok" />
          <Box label="Rejected" value={n(counts.rejected)} tone={(counts.rejected ?? 0) > 0 ? "bad" : undefined} />
          <Box label="Skipped" value={n(counts.skipped)} tone={(counts.skipped ?? 0) > 0 ? "warn" : undefined} />
        </div>
        <Arrow />
        <div className="flex flex-wrap gap-2">
          <Box label="Created" value={n(counts.created)} />
          <Box label="Updated" value={n(counts.updated)} />
          <Box label="Unchanged" value={n(counts.unchanged)} />
          {(counts.removed ?? 0) > 0 ? <Box label="Removed (replace)" value={n(counts.removed)} tone="warn" /> : null}
        </div>
      </div>
      <ul className="space-y-1 text-xs">
        <Identity ok={firstOk} text={`Received ${n(received)} = accepted ${n(accepted)} + rejected ${n(counts.rejected)} + skipped ${n(counts.skipped)}`} />
        <Identity ok={secondOk} text={accepted === 0 ? "Nothing was accepted, so nothing was stored" :
          `Accepted ${n(accepted)} = created ${n(counts.created)} + updated ${n(counts.updated)} + unchanged ${n(counts.unchanged)}`} />
      </ul>
    </div>
  );
}

function Identity({ ok, text }: { ok: boolean; text: string }) {
  return (
    <li className={ok ? "flex items-center gap-1.5 text-success-700" : "flex items-center gap-1.5 font-semibold text-danger-700"}>
      {ok ? <CheckCircle2 size={13} /> : <XCircle size={13} />} {text}{ok ? "" : " — does not reconcile; report this run"}
    </li>
  );
}

function Box({ label, value, tone }: { label: string; value: string; tone?: "ok" | "bad" | "warn" }) {
  const cls = tone === "bad" ? "border-danger-200 bg-danger-50 text-danger-800"
    : tone === "warn" ? "border-warning-200 bg-warning-50 text-warning-900"
      : tone === "ok" ? "border-success-200 bg-success-50 text-success-800"
        : "border-ink-200 bg-white text-ink-800";
  return (
    <div className={`min-w-[88px] rounded-lg border px-3 py-2 ${cls}`}>
      <div className="text-lg font-bold tabular-nums">{value}</div>
      <div className="text-[11px] font-semibold opacity-80">{label}</div>
    </div>
  );
}

function Arrow() {
  return <ArrowRight size={16} className="self-center text-ink-300" aria-hidden />;
}

export function HealthBadge({ health }: { health: Connection["health"] }) {
  return <Badge variant={health === "healthy" ? "success" : health === "failing" ? "destructive" : "secondary"}>{health}</Badge>;
}
