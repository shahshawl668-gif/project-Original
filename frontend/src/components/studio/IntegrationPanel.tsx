"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Cable } from "lucide-react";

import { useEntity } from "@/context/EntityContext";
import { Card, CardContent } from "@/components/ui/card";
import { StatusBadge, fmtTime } from "@/components/studio/RunBits";
import { OBJECT_LABEL, runTitle, studioFlowApi } from "@/lib/studio";

const INPUTS = ["employee_master", "attendance", "ctc", "salary_register"];
const STUDIO_ROLES = new Set(["owner", "manager", "analyst"]);

/**
 * How this month's inputs arrived through PeopleOps Studio: the latest import
 * or sync for each, anything that needs attention, workflows that ran, and the
 * health of the connections. Shown on Month close and Validations.
 */
export function IntegrationPanel({ period }: { period: string | null | undefined }) {
  const { entity, activeRole } = useEntity();
  const month = period ? period.slice(0, 7) : null;
  const allowed = STUDIO_ROLES.has(activeRole ?? "");
  const q = useQuery({ queryKey: ["studio-period", entity?.id, month], queryFn: () => studioFlowApi.period(month!),
    enabled: !!entity && !!month && allowed, retry: false });
  if (!allowed || !month) return null;
  if (q.error) return null;
  const d = q.data;
  const flows = (d?.runs ?? []).filter((r) => r.kind === "workflow");
  const failing = (d?.connections ?? []).filter((c) => c.health === "failing");
  return (
    <Card data-testid="integration-panel"><CardContent className="space-y-3 py-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="flex items-center gap-2 text-base font-semibold text-ink-900 dark:text-white"><Cable size={16} /> Data from your systems</h3>
        <Link href="/studio/runs" className="text-xs text-brand-700 underline">All Studio runs</Link>
      </div>
      {!d ? <p className="text-sm text-ink-500">Reading…</p> : d.runs.length === 0 && d.connections.length === 0 ? (
        <p className="text-sm text-ink-500">No input for this month arrived through Studio. Anything here was uploaded on its own screen.</p>
      ) : (
        <>
          <div className="grid gap-2 md:grid-cols-4">
            {INPUTS.map((k) => {
              const r = d.latest_by_input[k];
              return (
                <div key={k} className="rounded-lg border border-ink-200 p-2 text-xs dark:border-white/10">
                  <p className="font-semibold">{OBJECT_LABEL[k] ?? k}</p>
                  {r ? (
                    <Link href={`/studio/runs/${r.id}`} className="mt-1 flex flex-wrap items-center gap-1.5 hover:underline">
                      <StatusBadge status={r.status} />
                      <span>{r.counts ? `${r.counts.accepted ?? 0} of ${r.counts.received ?? 0} stored` : ""}</span>
                      <span className="text-ink-400">{fmtTime(r.finished_at ?? r.queued_at)}</span>
                    </Link>
                  ) : <p className="mt-1 text-ink-400">Not through Studio this month</p>}
                </div>
              );
            })}
          </div>
          {d.attention.length ? (
            <p className="text-sm text-warning-800">
              {d.attention.map((a) => <Link key={a.run_id} href={`/studio/runs/${a.run_id}`} className="mr-3 underline">{OBJECT_LABEL[a.object_type] ?? a.object_type}: {a.status.replace("_", " ")}{a.rejected ? `, ${a.rejected} rejected` : ""}</Link>)}
              — these records are not in the month until they are fixed and sent again.
            </p>
          ) : null}
          {failing.length ? <p className="text-sm text-danger-700">Failing: {failing.map((c) => <Link key={c.id} href={`/studio/connections/${c.id}`} className="mr-2 underline">{c.name}</Link>)}</p> : null}
          {flows.length ? (
            <ul className="text-xs text-ink-600 dark:text-ink-300">{flows.slice(0, 5).map((r) => (
              <li key={r.id} className="flex items-center gap-2 py-0.5"><Link href={`/studio/runs/${r.id}`} className="underline">{runTitle(r)}</Link> <StatusBadge status={r.status} /> <span className="text-ink-400">{fmtTime(r.queued_at)}</span></li>))}</ul>
          ) : null}
        </>
      )}
    </CardContent></Card>
  );
}
