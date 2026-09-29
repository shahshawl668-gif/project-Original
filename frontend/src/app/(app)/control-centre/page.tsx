"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  BarChart3,
  Check,
  CircleDashed,
  FileCheck2,
  FileSpreadsheet,
  GitCompare,
  Landmark,
  Loader2,
  RefreshCw,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";

import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill, type StatusTone } from "@/components/ui/status-pill";
import { useEntity } from "@/context/EntityContext";
import { fetchAttendanceRegisters } from "@/lib/attendance";
import { saveBlob } from "@/lib/download";
import { count, dateTime, inr, pct, plural } from "@/lib/format";
import { issuesApi } from "@/lib/issues";
import { fetchOverview } from "@/lib/reconciliation";
import { cn } from "@/lib/utils";
import { OUTCOME_LABEL, signoffApi, validationApi, type Outcome, type PeriodStatus } from "@/lib/validation";
import { periodLabel, useWorkingPeriod } from "@/lib/workspace";

/**
 * The month, in one place: what has arrived, what has been checked, what is
 * open, what blocks approval, and the one thing to do next.
 *
 * Its state comes from the server's own account of the month
 * (`/api/validation/periods/{p}/status`), which never calls a month clean by
 * default: no run, a run older than its inputs, or checks that could not be
 * performed each say so. This page adds nothing to that judgement — it only
 * lays it out and links each part to where it is worked.
 */

type Stage = PeriodStatus["stage"];

const STAGE_STATE: Record<string, { label: string; tone: StatusTone }> = {
  not_uploaded: { label: "Not started", tone: "neutral" },
  incomplete: { label: "Awaiting data", tone: "warning" },
  uploaded: { label: "Ready to validate", tone: "info" },
  validation_pending: { label: "Running", tone: "running" },
  validation_failed: { label: "Action required", tone: "danger" },
  revalidation_required: { label: "Action required", tone: "warning" },
  issues_found: { label: "Action required", tone: "danger" },
  checks_incomplete: { label: "Incomplete", tone: "warning" },
  ready_for_approval: { label: "Ready for approval", tone: "info" },
  pending_approval: { label: "Ready for approval", tone: "info" },
  signed_off: { label: "Signed off", tone: "success" },
};

function monthState(s: PeriodStatus) {
  if (s.signoff_state === "reopened" && s.stage !== "signed_off") return { label: "Reopened", tone: "warning" as StatusTone };
  return STAGE_STATE[s.stage] ?? { label: s.stage_label, tone: "neutral" as StatusTone };
}

export default function ControlCentrePage() {
  const { entity, activeRole } = useEntity();
  const { period, source } = useWorkingPeriod();
  const periodDate = period ? `${period}-01` : null;
  const enabled = !!entity && !!periodDate;

  const status = useQuery({
    queryKey: ["period-status", entity?.id, period],
    queryFn: () => validationApi.periodStatus(periodDate!),
    enabled,
    refetchInterval: (q) => (q.state.data?.active_job ? 4000 : false),
    placeholderData: (prev) => prev,
  });
  const recon = useQuery({
    queryKey: ["recon-overview", entity?.id, period],
    queryFn: () => fetchOverview(period!),
    enabled,
    retry: false,
  });
  const attendance = useQuery({
    queryKey: ["attendance-registers", entity?.id],
    queryFn: fetchAttendanceRegisters,
    enabled,
    retry: false,
  });
  const periodRuns = useQuery({
    queryKey: ["period-runs", entity?.id, period],
    queryFn: () => validationApi.runs({ period_month: periodDate!, include_superseded: true, limit: 20 }),
    enabled,
  });
  const worklist = useQuery({
    queryKey: ["worklist-summary", entity?.id],
    queryFn: () => issuesApi.worklist({ page: 1, page_size: 1, state: "active" }),
    enabled: !!entity,
    retry: false,
  });

  const s = status.data;
  const runs = (periodRuns.data ?? []).slice().sort((a, b) => b.run_number - a.run_number);
  const current = runs.find((r) => r.id === s?.current_run?.id) ?? null;
  const previous = current ? runs.find((r) => r.run_number < current.run_number) ?? null : null;
  const diff = useQuery({
    queryKey: ["run-compare-counts", entity?.id, previous?.id, current?.id],
    queryFn: () => validationApi.compare(previous!.id, current!.id, "new"),
    enabled: !!previous && !!current,
    retry: false,
  });

  const monthAttendance = (attendance.data ?? []).filter((a) => a.period_month?.slice(0, 7) === period);

  return (
    <div className="space-y-5">
      <PageHeader
        title="Payroll Control Centre"
        description={
          <>
            {entity?.name ?? "This company"} · {period ? periodLabel(period) : "…"}
            {source !== "chosen" && period ? <span className="text-ink-400"> (the latest month with a run — change it from the period menu above)</span> : null}
          </>
        }
        actions={s ? <StatusPill tone={monthState(s).tone} size="lg">{monthState(s).label}</StatusPill> : null}
      />

      {status.isError ? (
        <AlertBanner variant="error" title="The month's status could not be loaded" details={(status.error as Error)?.message}>
          Nothing below is a statement about this month until it loads. Try again in a moment.
        </AlertBanner>
      ) : null}

      {!s ? (
        <div className="space-y-4">
          <Skeleton className="h-36 w-full rounded-xl" />
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-44 rounded-xl" />)}
          </div>
        </div>
      ) : (
        <>
          <NextAction s={s} period={period!} canAct={activeRole !== "viewer"} />
          <Steps s={s} reconciled={recon.data?.reconciled ?? null} />

          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            <Panel title="Files & readiness" icon={FileSpreadsheet} href="/payroll/upload" linkLabel="Upload">
              <Row label="Salary register" state={s.upload ? (s.upload.missing_required.length ? "warn" : "ok") : "missing"}>
                {s.upload ? (
                  <>
                    <span className="block truncate text-ink-800" title={s.upload.filename ?? undefined}>{s.upload.filename ?? "Uploaded"}</span>
                    <span className="text-ink-500">
                      Revision {s.upload.revision} · {plural(s.upload.row_count, "row")} · {dateTime(s.upload.uploaded_at)}
                    </span>
                    {s.upload.missing_required.length ? (
                      <span className="block text-warning-800">Missing required: {s.upload.missing_required.join(", ")}</span>
                    ) : null}
                  </>
                ) : (
                  <span className="text-ink-500">Not uploaded for {periodLabel(period)}</span>
                )}
              </Row>
              <Row label="Attendance" state={attendance.isError ? "unknown" : monthAttendance.length ? "ok" : "missing"}>
                {attendance.isError ? (
                  <span className="text-ink-500">Could not be checked</span>
                ) : monthAttendance.length ? (
                  <span className="text-ink-700">{plural(monthAttendance[0].employee_count, "employee")} · {dateTime(monthAttendance[0].created_at)}</span>
                ) : (
                  <Link href="/payroll/attendance" className="text-ink-500 underline-offset-2 hover:underline">Not uploaded — attendance checks will not run</Link>
                )}
              </Row>
              <Row label="Bank file" state={recon.isError ? "unknown" : recon.data?.bank?.files.length ? "ok" : "missing"}>
                {recon.isError ? (
                  <span className="text-ink-500">Could not be checked</span>
                ) : recon.data?.bank?.files.length ? (
                  <span className="text-ink-700">{plural(recon.data.bank.files.length, "file")} · {inr(recon.data.bank.paid_total)} paid</span>
                ) : (
                  <Link href="/reconciliation/bank" className="text-ink-500 underline-offset-2 hover:underline">Not uploaded — payments are unreconciled</Link>
                )}
              </Row>
              <Row label="JV template" state={recon.isError ? "unknown" : recon.data?.jv?.template ? "ok" : "missing"}>
                {recon.data?.jv?.template ? (
                  <span className="text-ink-700">{recon.data.jv.template.name}</span>
                ) : (
                  <Link href="/config/jv-templates" className="text-ink-500 underline-offset-2 hover:underline">No approved template</Link>
                )}
              </Row>
            </Panel>

            <Panel
              title="Validation"
              icon={ShieldCheck}
              href={s.current_run ? `/payroll/results?run=${s.current_run.id}` : "/payroll/validation"}
              linkLabel={s.current_run ? "Results" : "Runs"}
            >
              {s.active_job ? (
                <div>
                  <div className="flex items-center justify-between text-[13px]">
                    <span className="font-medium text-ink-800">{s.active_job.stage_label}</span>
                    <span className="num text-ink-600">{pct(s.active_job.percent)}</span>
                  </div>
                  <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-ink-100" role="progressbar" aria-valuenow={Math.round(s.active_job.percent)} aria-valuemin={0} aria-valuemax={100} aria-label="Validation progress">
                    <div className="h-full rounded-full bg-brand-600 transition-[width] duration-slow" style={{ width: `${Math.max(2, s.active_job.percent)}%` }} />
                  </div>
                  <p className="mt-1.5 text-xs text-ink-500">
                    {count(s.active_job.employee_done)} of {count(s.active_job.employee_total)} employees
                  </p>
                </div>
              ) : s.current_run ? (
                <>
                  <p className="text-[13px] text-ink-700">
                    Run {s.current_run.run_number} · {plural(s.current_run.employee_count, "employee")} · {dateTime(s.current_run.finished_at ?? s.current_run.created_at)}
                  </p>
                  {s.freshness?.revalidation_required ? (
                    <p className="text-xs text-warning-800">
                      Out of date: {s.freshness.changes.map((c) => c.label).join(", ")} changed since this run.
                    </p>
                  ) : null}
                  <Coverage totals={s.readiness.coverage?.totals ?? null} pctValue={s.readiness.coverage?.coverage_pct ?? null} />
                </>
              ) : (
                <p className="text-[13px] text-ink-500">
                  {s.last_job?.state === "failed" ? `The last attempt failed: ${s.last_job.error ?? "no reason recorded"}` : "No validation has run for this month."}
                </p>
              )}
            </Panel>

            <Panel
              title="Findings needing attention"
              icon={TriangleAlert}
              href={s.current_run ? `/payroll/results?run=${s.current_run.id}&tab=findings` : "/payroll/issues"}
              linkLabel="Findings"
            >
              {s.current_run ? (
                <>
                  <div className="grid grid-cols-3 gap-2">
                    <Figure label="Critical" value={count(s.current_run.critical_count)} tone={s.current_run.critical_count ? "danger" : undefined} />
                    <Figure label="Warnings" value={count(s.current_run.warning_count)} tone={s.current_run.warning_count ? "warning" : undefined} />
                    <Figure label="Open" value={count(s.open_findings)} />
                  </div>
                  <p className="text-xs text-ink-500">
                    Open exposure{" "}
                    <span className="num font-medium text-ink-800">
                      {s.current_run.open_financial_impact === null ? "not calculated" : inr(s.current_run.open_financial_impact)}
                    </span>
                  </p>
                </>
              ) : (
                <p className="text-[13px] text-ink-500">No run for this month, so no findings — which is not the same as none.</p>
              )}
              {worklist.data ? (
                <p className="border-t border-ink-100 pt-2 text-xs text-ink-500">
                  Across all months:{" "}
                  <Link href="/payroll/issues?overdue=true" className="font-medium text-ink-800 hover:underline">{count(worklist.data.overdue)} overdue</Link>
                  {" · "}
                  <Link href="/payroll/issues?owner=none" className="font-medium text-ink-800 hover:underline">{count(worklist.data.unassigned)} unassigned</Link>
                </p>
              ) : null}
            </Panel>

            <Panel
              title="Changes since the previous run"
              icon={GitCompare}
              href={previous && current ? `/payroll/runs/compare?base=${previous.id}&target=${current.id}` : undefined}
              linkLabel="Compare"
            >
              {!current ? (
                <p className="text-[13px] text-ink-500">Nothing to compare until the month has a run.</p>
              ) : !previous ? (
                <p className="text-[13px] text-ink-500">Run {current.run_number} is the first run for {periodLabel(period)}.</p>
              ) : diff.data ? (
                <>
                  <p className="text-xs text-ink-500">Run {previous.run_number} → run {current.run_number}</p>
                  <div className="grid grid-cols-3 gap-2">
                    <Figure label="New" value={count(diff.data.counts.new)} tone={diff.data.counts.new ? "danger" : undefined} />
                    <Figure label="Resolved" value={count(diff.data.counts.resolved)} tone={diff.data.counts.resolved ? "success" : undefined} />
                    <Figure label="Changed" value={count(diff.data.counts.changed)} />
                  </div>
                </>
              ) : diff.isError ? (
                <p className="text-[13px] text-ink-500">The comparison could not be loaded.</p>
              ) : (
                <Skeleton className="h-14 w-full" />
              )}
            </Panel>

            <Panel title="Approval" icon={FileCheck2} href="/reconciliation" linkLabel="Month close">
              <p className="text-[13px] text-ink-700">
                {s.signoff_state === "signed"
                  ? "Signed off."
                  : s.signoff_state === "pending_approval"
                    ? "Submitted — waiting for an approver."
                    : s.signoff_state === "reopened"
                      ? "Reopened after sign-off."
                      : "Not submitted."}
              </p>
              {s.changed_since_signoff.length ? (
                <p className="text-xs text-warning-800">
                  Changed since sign-off: {s.changed_since_signoff.map((c) => c.label).join(", ")}.
                </p>
              ) : null}
              {s.readiness.blockers.length ? (
                <ul className="space-y-1.5">
                  {s.readiness.blockers.slice(0, 4).map((b) => (
                    <li key={b.code} className="flex gap-2 text-xs leading-relaxed text-ink-700">
                      <span className={cn("mt-1.5 h-1.5 w-1.5 flex-shrink-0 rounded-full", b.acceptable ? "bg-warning-500" : "bg-danger-500")} aria-hidden />
                      <span>
                        {b.message}
                        {b.acceptable ? <span className="text-ink-500"> — can be accepted with a stated reason</span> : null}
                      </span>
                    </li>
                  ))}
                  {s.readiness.blockers.length > 4 ? <li className="text-xs text-ink-500">and {s.readiness.blockers.length - 4} more</li> : null}
                </ul>
              ) : s.signoff_state !== "signed" && s.readiness.ready ? (
                <p className="text-xs text-ink-500">No blockers reported by the approval check.</p>
              ) : null}
            </Panel>

            <Panel title="Reconciliation" icon={Landmark} href="/reconciliation" linkLabel="Open">
              {recon.isError ? (
                <p className="text-[13px] text-ink-500">Reconciliation status could not be loaded.</p>
              ) : !recon.data ? (
                <Skeleton className="h-14 w-full" />
              ) : recon.data.period === null ? (
                <p className="text-[13px] text-ink-500">{recon.data.message ?? "No register to reconcile yet."}</p>
              ) : (
                <>
                  <Row label="Bank" state={recon.data.bank?.ready ? "ok" : "warn"}>
                    <span className="text-ink-700">{recon.data.bank?.message ?? (recon.data.bank?.ready ? "Ready to reconcile" : "Not ready")}</span>
                  </Row>
                  <Row label="Journal" state={recon.data.jv?.ready ? "ok" : "warn"}>
                    <span className="text-ink-700">{recon.data.jv?.message ?? (recon.data.jv?.ready ? "Ready to post" : "Not ready")}</span>
                  </Row>
                  <p className="text-xs text-ink-500">
                    {recon.data.reconciled ? "Reconciled for this month." : "Not reconciled for this month."}
                  </p>
                </>
              )}
            </Panel>

          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <Panel title="Evidence & reports" icon={FileSpreadsheet} href="/reports" linkLabel="Report Centre">
              <div className="flex flex-wrap items-center gap-3">
                <EvidenceButton period={period!} signed={s.signoff_state === "signed"} />
                <p className="min-w-0 flex-1 text-xs leading-relaxed text-ink-500">
                  {s.signoff_state === "signed"
                    ? "Built from the signed snapshot."
                    : "Built from live data, and marked inside the workbook as an unsigned draft."}
                </p>
              </div>
            </Panel>

            <Panel title="Dashboards" icon={BarChart3} href="/dashboards" linkLabel="Dashboards">
              {s.upload ? (
                s.upload.stored_as_register ? (
                  <p className="text-[13px] text-ink-700">
                    {periodLabel(period)} is in the register history, so cost analysis and dashboards include it.
                  </p>
                ) : (
                  <p className="text-[13px] text-warning-800">
                    This month&apos;s register was not stored in the register history, so dashboards do not include {periodLabel(period)}.
                  </p>
                )
              ) : (
                <p className="text-[13px] text-ink-500">Dashboards have no data for {periodLabel(period)} — no register was uploaded.</p>
              )}
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}

function NextAction({ s, period, canAct }: { s: PeriodStatus; period: string; canAct: boolean }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = s.current_run;
  const enqueue = async () => {
    setBusy(true);
    setError(null);
    try {
      const out = await validationApi.enqueue({ period_month: `${period}-01`, upload_id: s.freshness?.latest_upload_id ?? s.upload?.id ?? null });
      router.push(`/payroll/validation?job=${out.job.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Validation could not be started.");
      setBusy(false);
    }
  };

  const map: Record<Stage, { text: ReactNode; action?: ReactNode }> = {
    not_uploaded: {
      text: `Nothing has been uploaded for ${periodLabel(period)}, so nothing has been checked.`,
      action: <ActionLink href="/payroll/upload">Upload the salary register</ActionLink>,
    },
    incomplete: {
      text: `The register cannot be validated: ${s.upload?.missing_required.length ?? 0} required column(s) are missing (${s.upload?.missing_required.join(", ")}).`,
      action: <ActionLink href="/payroll/upload">Upload a corrected register</ActionLink>,
    },
    uploaded: {
      text: "The register is uploaded and complete. It has not been validated yet.",
      action: canAct ? <Button onClick={enqueue} disabled={busy}>{busy ? <Loader2 size={14} className="animate-spin" /> : null}Start validation</Button> : null,
    },
    validation_pending: {
      text: `Validation is running${s.active_job ? ` — ${s.active_job.stage_label.toLowerCase()}, ${pct(s.active_job.percent)}` : ""}. You can leave this page; the result is kept.`,
      action: s.active_job ? <ActionLink href={`/payroll/validation?job=${s.active_job.id}`} variant="outline">View progress</ActionLink> : null,
    },
    validation_failed: {
      text: `The last validation failed${s.last_job?.error ? `: ${s.last_job.error}` : ""}.`,
      action: s.last_job ? <ActionLink href={`/payroll/validation?job=${s.last_job.id}`}>Review and retry</ActionLink> : null,
    },
    revalidation_required: {
      text: `Inputs changed after run ${run?.run_number ?? ""}: ${s.freshness?.changes.map((c) => c.label).join(", ") || "see details"}. Its results no longer describe this month.`,
      action: canAct ? <Button onClick={enqueue} disabled={busy}>{busy ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}Revalidate</Button> : null,
    },
    issues_found: {
      text: `${plural(s.open_findings, "finding")} open in run ${run?.run_number ?? ""}. Resolve, fix or waive each with a reason before approval.`,
      action: <ActionLink href="/payroll/issues">Work the issues</ActionLink>,
    },
    checks_incomplete: {
      text: `No failures, but ${plural(s.readiness.coverage?.material_cannot_validate ?? 0, "material check")} could not be performed for want of an input. A month is not clean because nothing disagreed.`,
      action: run ? <ActionLink href={`/payroll/results?run=${run.id}&tab=coverage`}>See what could not be checked</ActionLink> : null,
    },
    ready_for_approval: {
      text: "The current run is up to date, nothing is open and every material check reached a verdict.",
      action: <ActionLink href="/reconciliation">Submit for approval</ActionLink>,
    },
    pending_approval: {
      text: "Submitted for approval. An approver reviews and signs it off from Month close.",
      action: <ActionLink href="/reconciliation" variant="outline">Open month close</ActionLink>,
    },
    signed_off: {
      text: s.changed_since_signoff.length
        ? `Signed off — but ${s.changed_since_signoff.map((c) => c.label.toLowerCase()).join(", ")} changed afterwards. The signed record is unchanged; consider reopening.`
        : "Signed off. The signed record and its evidence pack are kept unchanged.",
      action: <ActionLink href="/reconciliation" variant="outline">View sign-off</ActionLink>,
    },
  };
  const entry = map[s.stage] ?? { text: s.stage_label };
  const state = monthState(s);
  return (
    <section aria-labelledby="next-action" className="rounded-xl border border-ink-200 bg-white p-5 shadow-soft">
      <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div className="min-w-0">
          <p id="next-action" className="text-xs font-medium text-ink-500">Next step · {s.stage_label}</p>
          <p className="mt-1 max-w-3xl text-[15px] leading-relaxed text-ink-900">{entry.text}</p>
          {!canAct && (s.stage === "uploaded" || s.stage === "revalidation_required") ? (
            <p className="mt-1 text-xs text-ink-500">Your role can view this month; someone with analyst access or above starts validation.</p>
          ) : null}
        </div>
        <div className="flex flex-shrink-0 items-center gap-2">
          <span className="sr-only">Month state: {state.label}</span>
          {entry.action}
        </div>
      </div>
      {error ? <AlertBanner variant="error" className="mt-3">{error}</AlertBanner> : null}
    </section>
  );
}

function ActionLink({ href, children, variant = "default" }: { href: string; children: ReactNode; variant?: "default" | "outline" }) {
  return (
    <Button asChild variant={variant}>
      <Link href={href}>
        {children}
        <ArrowRight size={14} aria-hidden />
      </Link>
    </Button>
  );
}

type StepState = "done" | "current" | "attention" | "todo";

function Steps({ s, reconciled }: { s: PeriodStatus; reconciled: boolean | null }) {
  const fresh = s.current_run && !s.freshness?.revalidation_required;
  const steps: { label: string; state: StepState; note: string }[] = [
    {
      label: "Data",
      state: !s.upload ? "current" : s.upload.missing_required.length ? "attention" : "done",
      note: !s.upload ? "Awaiting register" : s.upload.missing_required.length ? "Columns missing" : `Revision ${s.upload.revision}`,
    },
    {
      label: "Validate",
      state: s.active_job ? "current" : s.stage === "validation_failed" ? "attention" : fresh ? "done" : s.upload ? (s.current_run ? "attention" : "current") : "todo",
      note: s.active_job ? "Running" : fresh ? `Run ${s.current_run!.run_number}` : s.current_run ? "Out of date" : "Not run",
    },
    {
      label: "Resolve",
      state: !fresh ? "todo" : s.open_findings ? "attention" : s.stage === "checks_incomplete" ? "attention" : "done",
      note: !fresh ? "—" : s.open_findings ? `${count(s.open_findings)} open` : s.stage === "checks_incomplete" ? "Checks incomplete" : "Nothing open",
    },
    {
      label: "Reconcile",
      state: reconciled === null ? "todo" : reconciled ? "done" : fresh ? "current" : "todo",
      note: reconciled === null ? "Unknown" : reconciled ? "Reconciled" : "Unreconciled",
    },
    {
      label: "Approve",
      state: s.signoff_state === "signed" ? "done" : s.signoff_state === "pending_approval" ? "current" : s.stage === "ready_for_approval" ? "current" : "todo",
      note: s.signoff_state === "signed" ? "Signed off" : s.signoff_state === "pending_approval" ? "Awaiting approver" : s.signoff_state === "reopened" ? "Reopened" : "Not submitted",
    },
  ];
  return (
    <ol aria-label="Month progress" className="grid grid-cols-2 gap-2 sm:grid-cols-5">
      {steps.map((step, i) => (
        <li
          key={step.label}
          className={cn(
            "flex items-center gap-2.5 rounded-lg border bg-white px-3 py-2.5",
            step.state === "attention" ? "border-warning-200" : step.state === "current" ? "border-brand-200" : "border-ink-200",
          )}
        >
          <span
            className={cn(
              "flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full text-[11px] font-semibold",
              step.state === "done" && "bg-success-600 text-white",
              step.state === "current" && "bg-brand-600 text-white",
              step.state === "attention" && "bg-warning-500 text-white",
              step.state === "todo" && "border border-ink-200 text-ink-400",
            )}
            aria-hidden
          >
            {step.state === "done" ? <Check size={13} strokeWidth={3} /> : step.state === "attention" ? "!" : i + 1}
          </span>
          <span className="min-w-0">
            <span className="block text-[13px] font-medium text-ink-900">{step.label}</span>
            <span className="block truncate text-xs text-ink-500">
              <span className="sr-only">{step.state === "done" ? "Done: " : step.state === "attention" ? "Needs attention: " : step.state === "current" ? "Current: " : "Not yet: "}</span>
              {step.note}
            </span>
          </span>
        </li>
      ))}
    </ol>
  );
}

function Panel({
  title,
  icon: Icon,
  href,
  linkLabel,
  children,
}: {
  title: string;
  icon: typeof ShieldCheck;
  href?: string;
  linkLabel?: string;
  children: ReactNode;
}) {
  return (
    <section className="flex flex-col rounded-xl border border-ink-200 bg-white shadow-soft">
      <header className="flex items-center gap-2 border-b border-ink-100 px-4 py-2.5">
        <Icon size={15} className="text-ink-400" aria-hidden />
        <h2 className="flex-1 text-[13px] font-semibold text-ink-900">{title}</h2>
        {href ? (
          <Link href={href} className="inline-flex items-center gap-0.5 text-xs font-medium text-brand-700 hover:text-brand-800">
            {linkLabel ?? "Open"}
            <span className="sr-only"> — {title}</span>
            <ArrowRight size={12} aria-hidden />
          </Link>
        ) : null}
      </header>
      <div className="flex flex-1 flex-col gap-2.5 px-4 py-3">{children}</div>
    </section>
  );
}

function Row({ label, state, children }: { label: string; state: "ok" | "warn" | "missing" | "unknown"; children: ReactNode }) {
  const icon =
    state === "ok" ? <Check size={13} className="text-success-600" aria-label="Present" /> :
    state === "warn" ? <TriangleAlert size={13} className="text-warning-600" aria-label="Needs attention" /> :
    state === "unknown" ? <CircleDashed size={13} className="text-ink-400" aria-label="Unknown" /> :
    <CircleDashed size={13} className="text-ink-400" aria-label="Missing" />;
  return (
    <div className="flex gap-2.5 text-[13px]">
      <span className="mt-0.5 flex-shrink-0">{icon}</span>
      <div className="min-w-0 flex-1">
        <p className="text-xs font-medium text-ink-500">{label}</p>
        <div className="text-xs leading-relaxed">{children}</div>
      </div>
    </div>
  );
}

function Figure({ label, value, tone }: { label: string; value: string; tone?: "danger" | "warning" | "success" }) {
  return (
    <div className="rounded-lg bg-ink-50 px-2.5 py-2">
      <p className="text-[11px] text-ink-500">{label}</p>
      <p
        className={cn(
          "num text-lg font-semibold leading-tight",
          tone === "danger" ? "text-danger-700" : tone === "warning" ? "text-warning-800" : tone === "success" ? "text-success-700" : "text-ink-900",
        )}
      >
        {value}
      </p>
    </div>
  );
}

const OUTCOME_ORDER: Outcome[] = ["passed", "failed", "cannot_validate", "not_applicable", "disabled"];
const OUTCOME_BAR: Record<Outcome, string> = {
  passed: "bg-success-500",
  failed: "bg-danger-500",
  cannot_validate: "bg-warning-400",
  not_applicable: "bg-ink-200",
  disabled: "bg-ink-100",
};

/** Coverage is how much was checked — separate from what failed. */
function Coverage({ totals, pctValue }: { totals: Record<Outcome, number> | null; pctValue: number | null }) {
  if (!totals) return <p className="text-xs text-ink-500">Coverage was not recorded for this run.</p>;
  const sum = OUTCOME_ORDER.reduce((a, k) => a + (totals[k] ?? 0), 0) || 1;
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <p className="text-xs text-ink-500">Checks that reached a verdict</p>
        <p className="num text-[13px] font-semibold text-ink-900">{pct(pctValue)}</p>
      </div>
      <div className="mt-1.5 flex h-1.5 overflow-hidden rounded-full bg-ink-100" aria-hidden>
        {OUTCOME_ORDER.map((k) => (totals[k] ? <div key={k} className={OUTCOME_BAR[k]} style={{ width: `${(totals[k] / sum) * 100}%` }} /> : null))}
      </div>
      <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-0.5 text-xs">
        {OUTCOME_ORDER.map((k) => (
          <div key={k} className="flex items-center justify-between gap-2">
            <dt className="flex items-center gap-1.5 text-ink-500">
              <span className={cn("h-2 w-2 rounded-sm", OUTCOME_BAR[k])} aria-hidden />
              {OUTCOME_LABEL[k]}
            </dt>
            <dd className="num text-ink-800">{count(totals[k] ?? 0)}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function EvidenceButton({ period, signed }: { period: string; signed: boolean }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <div>
      <Button
        variant="outline"
        size="sm"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          setError(null);
          try {
            saveBlob(await signoffApi.evidencePack(`${period}-01`), `evidence-pack-${period}${signed ? "" : "-draft"}.xlsx`);
          } catch (e) {
            setError(e instanceof Error ? e.message : "The evidence pack could not be built.");
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? <Loader2 size={13} className="animate-spin" /> : <FileSpreadsheet size={13} />}
        {signed ? "Evidence pack" : "Evidence pack (draft)"}
      </Button>
      {error ? <p className="mt-1.5 text-xs text-danger-700" role="alert">{error}</p> : null}
    </div>
  );
}
