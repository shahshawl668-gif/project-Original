"use client";

import Link from "next/link";
import { Suspense, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { useEntity } from "@/context/EntityContext";
import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Skeleton } from "@/components/ui/skeleton";
import { StudioNav } from "@/components/studio/StudioNav";
import { StatusBadge, fmtTime } from "@/components/studio/RunBits";
import { OBJECT_LABEL, STATUS_LABEL, runTitle, studioApi, type RunStatus } from "@/lib/studio";
import { cn } from "@/lib/utils";

const FIELD =
  "rounded-lg border border-ink-200 bg-white px-2.5 py-1.5 text-sm text-ink-900";

export default function StudioRunsPage() {
  return <Suspense fallback={<Skeleton className="h-96 w-full rounded-2xl" />}><Runs /></Suspense>;
}

/** Every integration run for this company, newest first, searchable. */
function Runs() {
  const { entity } = useEntity();
  const [filters, setFilters] = useState({ kind: "", status: "", object_type: "", actor_type: "", q: "", date_from: "", date_to: "" });
  const [page, setPage] = useState(1);
  const q = useQuery({
    queryKey: ["studio-runs", entity?.id, filters, page],
    queryFn: () => studioApi.runs({ ...filters, page, page_size: 50 }),
    enabled: !!entity,
    refetchInterval: (query) => (query.state.data?.items.some((r) => r.status === "queued" || r.status === "running") ? 3000 : false),
  });
  const set = (k: keyof typeof filters) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    setFilters({ ...filters, [k]: e.target.value });
    setPage(1);
  };

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="PeopleOps Studio" title="Run history"
        description="Every import and API-started validation for this company: who started it, what arrived, what was accepted and rejected, and what it led to." />
      <StudioNav />
      <div className="flex flex-wrap items-end gap-2">
        <label className="text-xs font-semibold text-ink-700">Search
          <input className={cn(FIELD, "mt-1 block w-56")} placeholder="Batch id, system, key, run id" value={filters.q} onChange={set("q")} />
        </label>
        <label className="text-xs font-semibold text-ink-700">Status
          <select aria-label="Status" className={cn(FIELD, "mt-1 block")} value={filters.status} onChange={set("status")}>
            <option value="">Any</option>
            {(Object.keys(STATUS_LABEL) as RunStatus[]).map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
          </select>
        </label>
        <label className="text-xs font-semibold text-ink-700">Kind
          <select aria-label="Kind" className={cn(FIELD, "mt-1 block")} value={filters.kind} onChange={set("kind")}>
            <option value="">Any</option><option value="import">Import</option><option value="sync">Sync</option><option value="validation">Validation</option>
          </select>
        </label>
        <label className="text-xs font-semibold text-ink-700">Data
          <select aria-label="Data" className={cn(FIELD, "mt-1 block")} value={filters.object_type} onChange={set("object_type")}>
            <option value="">Any</option>
            {Object.entries(OBJECT_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <label className="text-xs font-semibold text-ink-700">Started by
          <select aria-label="Started by" className={cn(FIELD, "mt-1 block")} value={filters.actor_type} onChange={set("actor_type")}>
            <option value="">Anyone</option><option value="machine">A service account</option><option value="user">A person</option>
          </select>
        </label>
        <label className="text-xs font-semibold text-ink-700">From<input type="date" className={cn(FIELD, "mt-1 block")} value={filters.date_from} onChange={set("date_from")} /></label>
        <label className="text-xs font-semibold text-ink-700">To<input type="date" className={cn(FIELD, "mt-1 block")} value={filters.date_to} onChange={set("date_to")} /></label>
      </div>

      {q.error ? <AlertBanner variant="error" title="Could not load run history">{(q.error as Error).message}</AlertBanner> : null}
      {!q.data ? <Skeleton className="h-64 w-full rounded-2xl" /> : q.data.items.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-ink-200 px-6 py-12 text-center text-sm text-ink-500">
          No runs match. Runs appear here when a system sends data through the integration API — see the <Link href="/studio/api" className="font-semibold text-brand-700 underline">API Centre</Link>.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-2xl border border-ink-200">
          <table className="w-full text-sm">
            <thead className="bg-ink-50 text-left text-xs uppercase tracking-wide text-ink-500">
              <tr><th className="px-3 py-2">Queued</th><th className="px-3 py-2">Run</th><th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Started by</th><th className="px-3 py-2">Source / batch</th>
                <th className="px-3 py-2 text-right">Received</th><th className="px-3 py-2 text-right">Accepted</th><th className="px-3 py-2 text-right">Rejected</th></tr>
            </thead>
            <tbody className="divide-y divide-ink-100">
              {q.data.items.map((r) => (
                <tr key={r.id} className="hover:bg-ink-50/60">
                  <td className="whitespace-nowrap px-3 py-2 text-ink-600">{fmtTime(r.queued_at)}</td>
                  <td className="px-3 py-2"><Link href={`/studio/runs/${r.id}`} className="font-medium text-brand-700 hover:underline">{runTitle(r)}</Link>
                    <span className="block text-[11px] text-ink-400">{r.period_month ? `for ${r.period_month.slice(0, 7)}` : r.effective_from ? `from ${r.effective_from}` : ""} {r.trigger !== "api" ? `· ${r.trigger}` : ""}</span></td>
                  <td className="px-3 py-2"><StatusBadge status={r.status} /></td>
                  <td className="px-3 py-2 text-xs text-ink-600">{r.actor.type === "machine" ? "🔑 " : ""}{r.actor.label}</td>
                  <td className="px-3 py-2 text-xs text-ink-600">{[r.source.system, r.source.batch_id].filter(Boolean).join(" · ") || "—"}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{r.counts?.received ?? "—"}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{r.counts?.accepted ?? "—"}</td>
                  <td className={cn("px-3 py-2 text-right tabular-nums", (r.counts?.rejected ?? 0) > 0 && "font-semibold text-danger-700")}>{r.counts?.rejected ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {q.data && q.data.pages > 1 ? (
        <div className="flex items-center gap-2 text-sm">
          <button type="button" disabled={page <= 1} onClick={() => setPage(page - 1)} className="rounded border px-2 py-1 disabled:opacity-40">Previous</button>
          <span>Page {page} of {q.data.pages} · {q.data.total} runs</span>
          <button type="button" disabled={page >= q.data.pages} onClick={() => setPage(page + 1)} className="rounded border px-2 py-1 disabled:opacity-40">Next</button>
        </div>
      ) : null}
    </div>
  );
}
