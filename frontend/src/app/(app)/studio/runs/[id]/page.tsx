"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowLeft, Eye, RotateCcw, XCircle } from "lucide-react";

import { useEntity } from "@/context/EntityContext";
import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { StudioNav } from "@/components/studio/StudioNav";
import { CountsFunnel, StatusBadge, fmtTime } from "@/components/studio/RunBits";
import { runTitle, studioApi, type Rejection } from "@/lib/studio";
import { WorkflowSteps } from "@/components/studio/WorkflowSteps";

const MANAGE = new Set(["owner", "manager"]);
const WRITE = new Set(["owner", "manager", "analyst"]);

/**
 * One run, end to end: what arrived, what happened to every record, what it
 * produced downstream, and what to do if it went wrong.
 */
export default function StudioRunPage() {
  const { id } = useParams<{ id: string }>();
  const { entity, activeRole } = useEntity();
  const qc = useQueryClient();
  const [page, setPage] = useState(1);
  const [disposition, setDisposition] = useState<"" | "rejected" | "skipped">("");
  const [viewing, setViewing] = useState<Rejection | null>(null);
  const [busy, setBusy] = useState(false);

  const run = useQuery({
    queryKey: ["studio-run", entity?.id, id], queryFn: () => studioApi.run(id), enabled: !!entity && !!id, retry: false,
    refetchInterval: (query) => (query.state.data && ["queued", "running"].includes(query.state.data.status) ? 2500 : false),
  });
  const rejections = useQuery({
    queryKey: ["studio-rejections", entity?.id, id, page, disposition],
    queryFn: () => studioApi.rejections(id, page, disposition || undefined),
    enabled: !!run.data && ["import", "sync"].includes(run.data.kind),
  });

  if (run.error) {
    return (
      <div className="space-y-4">
        <PageHeader eyebrow="PeopleOps Studio" title="Run" />
        <AlertBanner variant="error" title="This run could not be opened">
          It may belong to another company. <Link href="/studio/runs" className="font-semibold underline">Run history</Link>
        </AlertBanner>
      </div>
    );
  }
  const r = run.data;
  if (!r) return <Skeleton className="h-96 w-full rounded-2xl" />;

  const act = async (fn: () => Promise<unknown>, done: string) => {
    setBusy(true);
    try {
      await fn();
      toast.success(done);
      await qc.invalidateQueries({ queryKey: ["studio-run", entity?.id, id] });
      await qc.invalidateQueries({ queryKey: ["studio-runs", entity?.id] });
    } catch (e) {
      toast.error("Refused", { description: e instanceof Error ? e.message : "" });
    } finally {
      setBusy(false);
    }
  };
  const retryable = ["import", "sync"].includes(r.kind) && r.object_type !== "salary_register" && (r.counts?.rejected ?? 0) > 0;
  const validationRun = r.links.validation_run_id as string | null | undefined;
  const missing = r.links.missing_in_source as { count: number; employee_ids: string[] } | undefined;
  const validationJob = r.links.validation_job_id as string | null | undefined;

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="PeopleOps Studio · run" title={<span className="flex flex-wrap items-center gap-3">{runTitle(r)} <StatusBadge status={r.status} /></span>}
        description={`${r.actor.label} · queued ${fmtTime(r.queued_at)}${r.finished_at ? ` · finished ${fmtTime(r.finished_at)}` : ""}`}
        actions={
          <div className="flex flex-wrap gap-2">
            <Link href="/studio/runs" className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-ink-200 px-3 text-sm"><ArrowLeft size={14} /> All runs</Link>
            {["queued", "running"].includes(r.status) && WRITE.has(activeRole ?? "") ? (
              <button type="button" disabled={busy} onClick={() => void act(() => studioApi.cancel(r.id), "Cancellation requested")}
                className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-danger-200 px-3 text-sm text-danger-700"><XCircle size={14} /> Cancel</button>
            ) : null}
            {retryable && WRITE.has(activeRole ?? "") ? (
              <button type="button" disabled={busy} onClick={() => void act(() => studioApi.retryRejected(r.id), "Rejected records queued again as a new run")}
                className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-brand-600 px-3 text-sm font-semibold text-white"><RotateCcw size={14} /> Retry rejected records</button>
            ) : null}
          </div>
        } />
      <StudioNav />

      {r.error ? (
        <AlertBanner variant={r.status === "failed" ? "error" : "warning"} title={r.error.message}>
          {r.error.recommended_action ? <><strong>What to do:</strong> {r.error.recommended_action}</> : null}
          <span className="block pt-1 text-xs opacity-80">Error category: {r.error.category}{r.attempts > 1 ? ` · ${r.attempts} attempts` : ""}</span>
        </AlertBanner>
      ) : null}

      {r.workflow ? <WorkflowSteps run={r} /> : null}

      {r.counts ? (
        <Card><CardContent className="space-y-3 py-5">
          <h2 className="text-base font-semibold text-ink-900">Reconciliation</h2>
          <CountsFunnel counts={r.counts} />
        </CardContent></Card>
      ) : r.status === "queued" || r.status === "running" ? (
        <AlertBanner variant="info" title={r.status === "queued" ? "Waiting for the worker" : `Running — ${r.stage ?? ""}`}>Counts appear when the run finishes. This page refreshes itself.</AlertBanner>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card><CardContent className="space-y-2 py-5 text-sm">
          <h2 className="text-base font-semibold text-ink-900">Source and lineage</h2>
          <Row k="Source system" v={r.source.system} />
          <Row k="Source object" v={r.source.object} />
          <Row k="Batch id" v={r.source.batch_id} />
          <Row k="Started by" v={r.actor.label} />
          <Row k="Trigger" v={r.trigger} />
          <Row k="Environment" v={r.environment} />
          <Row k="Period" v={r.period_month ?? r.effective_from} />
          <Row k="Mode" v={(r.options?.mode as string) ?? null} />
          {r.links.connection_id ? <p className="text-xs"><span className="text-ink-500">Connection:</span> <Link className="font-semibold text-brand-700 underline" href={`/studio/connections/${r.links.connection_id}`}>open</Link></p> : null}
          <Row k="Mapping version" v={(r.versions?.mapping as string) ?? "none — fields were read by their names"} />
          <Row k="Request id" v={r.request_id} mono />
          <Row k="Run id" v={r.id} mono />
          {r.retry_of_run_id ? <p className="text-xs">A retry of <Link className="font-semibold text-brand-700 underline" href={`/studio/runs/${r.retry_of_run_id}`}>an earlier run</Link>.</p> : null}
          <p className="pt-1 text-xs text-ink-500">Every stored record carries this run id, the source record id and the time it arrived.</p>
        </CardContent></Card>

        <Card><CardContent className="space-y-2 py-5 text-sm">
          <h2 className="text-base font-semibold text-ink-900">What it led to</h2>
          {validationRun ? (
            <p><Link href={`/payroll/results?run=${encodeURIComponent(validationRun)}`} className="font-semibold text-brand-700 underline">Validation results</Link> — findings, coverage and “Why this result?” for this data.</p>
          ) : validationJob ? (
            <p><Link href={`/payroll/validation?job=${encodeURIComponent(validationJob)}`} className="font-semibold text-brand-700 underline">Validation in progress</Link></p>
          ) : <p className="text-ink-500">No validation was started from this run.</p>}
          {r.links.register_upload_id ? <p>Stored as the {r.period_month?.slice(0, 7)} salary register (frozen upload {String(r.links.register_upload_id).slice(0, 8)}).</p> : null}
          {r.links.master_upload_id ? <p>Stored in the employee master effective {r.effective_from}.</p> : null}
          {r.links.attendance_register_id ? <p>Stored in the {r.period_month?.slice(0, 7)} attendance register.</p> : null}
          {r.links.ctc_upload_id ? <p>Stored in CTC history, each record at its own effective date.</p> : null}
          {r.links.ignored_columns?.length ? <p className="text-warning-800">Columns not recognised and ignored: {r.links.ignored_columns.join(", ")}</p> : null}
          {r.links.warnings?.length ? <ul className="list-disc pl-5 text-xs text-ink-600">{r.links.warnings.map((w) => <li key={w}>{w}</li>)}</ul> : null}
          {missing ? (
            <div className={missing.count ? "rounded-lg border border-warning-200 bg-warning-50 p-2 text-xs text-warning-900" : "text-xs text-ink-500"}>
              {missing.count
                ? <><strong>{missing.count} employee(s) stored here were not in this full fetch.</strong> Nothing was removed — the stream reports absences rather than acting on them. Check whether they left: {missing.employee_ids.join(", ")}{missing.count > missing.employee_ids.length ? " …" : ""}</>
                : "Every employee stored here was in this full fetch."}
            </div>
          ) : null}
          {r.retries?.length ? (
            <div className="pt-2"><p className="text-xs font-semibold text-ink-500">Retries</p>
              <ul className="text-xs">{r.retries.map((x) => <li key={x.id}><Link className="text-brand-700 underline" href={`/studio/runs/${x.id}`}>{fmtTime(x.queued_at)}</Link> — {x.status}</li>)}</ul></div>
          ) : null}
        </CardContent></Card>
      </div>

      {["import", "sync"].includes(r.kind) ? (
        <Card><CardContent className="space-y-3 py-5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-base font-semibold text-ink-900">Records not stored</h2>
            <select aria-label="Show" className="rounded-lg border border-ink-200 px-2 py-1 text-sm" value={disposition}
              onChange={(e) => { setDisposition(e.target.value as typeof disposition); setPage(1); }}>
              <option value="">Rejected and skipped</option><option value="rejected">Rejected</option><option value="skipped">Skipped</option>
            </select>
          </div>
          {r.rejection_summary?.length ? (
            <div className="flex flex-wrap gap-2 text-xs">{r.rejection_summary.map((s) => (
              <span key={`${s.disposition}-${s.code}`} className="rounded-full border border-ink-200 px-2 py-0.5">{s.code.replace(/_/g, " ")} · {s.count}</span>))}</div>
          ) : null}
          {!rejections.data ? <Skeleton className="h-24 w-full" /> : rejections.data.items.length === 0 ? (
            <p className="text-sm text-ink-500">Every record received was stored.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-ink-500">
                  <tr><th className="py-1 pr-3">Row</th><th className="py-1 pr-3">Employee</th><th className="py-1 pr-3">Outcome</th>
                    <th className="py-1 pr-3">Field</th><th className="py-1 pr-3">Reason</th><th className="py-1 pr-3">Source record</th><th className="py-1" /></tr>
                </thead>
                <tbody className="divide-y divide-ink-100">
                  {rejections.data.items.map((x) => (
                    <tr key={x.id}>
                      <td className="py-1.5 pr-3 tabular-nums">{x.row_number}</td>
                      <td className="py-1.5 pr-3 font-mono text-xs">{x.record_key ?? "—"}</td>
                      <td className="py-1.5 pr-3 text-xs">{x.disposition === "skipped" ? "Skipped" : "Rejected"} · {x.code.replace(/_/g, " ")}</td>
                      <td className="py-1.5 pr-3 font-mono text-xs">{x.field ?? "—"}</td>
                      <td className="py-1.5 pr-3 text-xs">{x.message}{x.retried_in_run_id ? <span className="block text-ink-400">retried in <Link className="underline" href={`/studio/runs/${x.retried_in_run_id}`}>a later run</Link></span> : null}</td>
                      <td className="py-1.5 pr-3 font-mono text-xs">{x.source_ref?.record_id ?? "—"}</td>
                      <td className="py-1.5 text-right">
                        {MANAGE.has(activeRole ?? "") && x.payload_retained ? (
                          <button type="button" className="inline-flex items-center gap-1 text-xs text-brand-700 underline"
                            onClick={() => void studioApi.rejectedRecord(r.id, x.id).then(setViewing).catch((e) => toast.error(e instanceof Error ? e.message : "Refused"))}>
                            <Eye size={12} /> Record
                          </button>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {rejections.data && rejections.data.pages > 1 ? (
            <div className="flex items-center gap-2 text-sm">
              <button type="button" disabled={page <= 1} onClick={() => setPage(page - 1)} className="rounded border px-2 py-1 disabled:opacity-40">Previous</button>
              <span>Page {page} of {rejections.data.pages}</span>
              <button type="button" disabled={page >= rejections.data.pages} onClick={() => setPage(page + 1)} className="rounded border px-2 py-1 disabled:opacity-40">Next</button>
            </div>
          ) : null}
          <p className="text-xs text-ink-500">The record as received is kept for a limited time and shown only to owners and managers; each viewing is written to the audit trail.</p>
        </CardContent></Card>
      ) : null}

      {viewing ? (
        <Card><CardContent className="space-y-2 py-5">
          <div className="flex items-center justify-between"><h2 className="text-base font-semibold">Row {viewing.row_number} as received</h2>
            <button type="button" className="text-sm underline" onClick={() => setViewing(null)}>Close</button></div>
          <pre className="max-h-80 overflow-auto rounded-lg bg-ink-900 p-3 text-xs text-ink-100">{JSON.stringify(viewing.record, null, 2)}</pre>
        </CardContent></Card>
      ) : null}
    </div>
  );
}

function Row({ k, v, mono }: { k: string; v: string | null | undefined; mono?: boolean }) {
  return (
    <p className="flex justify-between gap-3 border-b border-ink-100 py-1 last:border-0">
      <span className="text-ink-500">{k}</span>
      <span className={mono ? "break-all text-right font-mono text-xs" : "text-right"}>{v || "—"}</span>
    </p>
  );
}
