"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  ArrowRight,
  CheckCircle2,
  Circle,
  FileDown,
  Loader2,
  RotateCcw,
  ShieldCheck,
  Stamp,
} from "lucide-react";

import { useAuth } from "@/context/AuthContext";
import { useEntity } from "@/context/EntityContext";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  monthLabel,
  signoffApi,
  validationApi,
  type PeriodStatus,
  type ReadinessBlocker,
  type SignOffDetail,
} from "@/lib/validation";
import { cn } from "@/lib/utils";

/**
 * Approving a month.
 *
 * The month moves Uploaded → Validated → Issues handled → Submitted → Signed
 * off, and every step is a claim somebody makes on the record. The panel shows
 * what stands in the way of the next one in words the preparer can act on, and
 * it will not offer a button the server would refuse: a month that was never
 * validated, or whose inputs changed since, cannot be submitted at all.
 */

const STEPS = [
  { key: "uploaded", label: "Uploaded" },
  { key: "validated", label: "Validated" },
  { key: "handled", label: "Issues handled" },
  { key: "submitted", label: "Submitted" },
  { key: "signed", label: "Signed off" },
] as const;

function stepsDone(stage: string): number {
  switch (stage) {
    case "not_uploaded":
      return 0;
    case "uploaded":
    case "incomplete":
    case "validation_pending":
    case "validation_failed":
      return 1;
    case "revalidation_required":
    case "issues_found":
    case "checks_incomplete":
      return 2;
    case "ready_for_approval":
      return 3;
    case "pending_approval":
      return 4;
    case "signed_off":
      return 5;
    default:
      return 0;
  }
}

const BLOCKER_ACTION: Record<string, { href: (runId: string | null) => string; label: string }> = {
  not_validated: { href: () => "/payroll/upload", label: "Upload & validate" },
  revalidation_required: { href: () => "/payroll/validation", label: "Revalidate" },
  incomplete_coverage: {
    href: (runId) => (runId ? `/payroll/results?run=${encodeURIComponent(runId)}&tab=coverage` : "/payroll/results"),
    label: "See what could not be checked",
  },
};

const ADMIN_ROLES = new Set(["owner", "manager"]);
const WRITE_ROLES = new Set(["owner", "manager", "analyst"]);

export function SignOffPanel({ period }: { period: string }) {
  const { user } = useAuth();
  const { activeRole, entity } = useEntity();
  const qc = useQueryClient();
  const [notes, setNotes] = useState("");
  const [acceptReason, setAcceptReason] = useState("");
  const [reopenReason, setReopenReason] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const status = useQuery<PeriodStatus>({
    queryKey: ["period-status", entity?.id, period],
    queryFn: () => validationApi.periodStatus(period),
  });
  // Only ask for the sign-off record once the month has one.
  const hasSignoff = !!status.data?.signoff_state;
  const detail = useQuery<SignOffDetail | null>({
    queryKey: ["signoff", entity?.id, period],
    queryFn: () => signoffApi.get(period),
    enabled: hasSignoff,
  });
  const policy = useQuery({
    queryKey: ["approval-policy", entity?.org_id],
    queryFn: () => signoffApi.policy(),
  });

  const refresh = async () => {
    await Promise.all([
      qc.invalidateQueries({ queryKey: ["period-status", entity?.id, period] }),
      qc.invalidateQueries({ queryKey: ["signoff", entity?.id, period] }),
    ]);
  };

  const act = async (name: string, fn: () => Promise<unknown>, done: string) => {
    setBusy(name);
    setError(null);
    try {
      await fn();
      toast.success(done);
      setNotes("");
      setAcceptReason("");
      setReopenReason("");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "The request was refused.");
    } finally {
      setBusy(null);
    }
  };

  const downloadPack = async () => {
    setBusy("pack");
    try {
      const blob = await signoffApi.evidencePack(period);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `evidence-pack-${period.slice(0, 7)}.xlsx`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      toast.error("Could not build the evidence pack", { description: e instanceof Error ? e.message : "" });
    } finally {
      setBusy(null);
    }
  };

  if (status.isLoading || (hasSignoff && detail.isLoading)) {
    return (
      <Card>
        <CardContent className="flex items-center gap-2 py-8 text-sm text-ink-500">
          <Loader2 className="animate-spin" size={15} /> Reading the month&apos;s approval state…
        </CardContent>
      </Card>
    );
  }
  if (status.error || !status.data) {
    return (
      <AlertBanner variant="error" title="Could not read the approval state">
        {status.error instanceof Error ? status.error.message : "Try again."}
      </AlertBanner>
    );
  }

  const s = status.data;
  const signoff = detail.data?.signoff ?? null;
  const state = signoff?.state ?? null;
  const readiness = s.readiness;
  const hard = readiness.blockers.filter((b) => !b.acceptable);
  const soft = readiness.blockers.filter((b) => b.acceptable);
  const canWrite = WRITE_ROLES.has(activeRole ?? "");
  const canApprove = ADMIN_ROLES.has(activeRole ?? "");
  const independent = policy.data?.signoff_requires_independent_approver ?? false;
  const preparedBy =
    detail.data?.history.find((h) => h.to_state === "pending_approval")?.actor_email ?? null;
  const selfApproval =
    independent && !!preparedBy && !!user?.email && preparedBy.toLowerCase() === user.email.toLowerCase();
  const done = stepsDone(s.stage);
  const needsReason = soft.length > 0 && !acceptReason.trim();

  return (
    <Card>
      <CardContent className="space-y-5 py-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="flex items-center gap-2 text-base font-semibold text-ink-900 dark:text-white">
              <Stamp size={16} className="text-ink-400" /> Approval · {monthLabel(period)}
            </h3>
            <p className="text-xs text-ink-500 dark:text-ink-400">
              {s.stage_label}
              {readiness.run_number ? ` · run #${readiness.run_number}` : ""}
              {readiness.coverage?.coverage_pct != null
                ? ` · ${readiness.coverage.coverage_pct}% of applicable checks reached a verdict`
                : ""}
            </p>
          </div>
          <Button
            type="button"
            variant="outline"
            className="gap-2"
            disabled={busy === "pack"}
            onClick={() => void downloadPack()}
          >
            <FileDown size={14} /> {busy === "pack" ? "Building…" : "Evidence pack"}
          </Button>
        </div>

        <ol className="grid grid-cols-5 gap-1" aria-label="Month progress">
          {STEPS.map((step, i) => {
            const complete = i < done;
            const current = i === done;
            return (
              <li key={step.key} className="flex flex-col items-center gap-1 text-center">
                {complete ? (
                  <CheckCircle2 size={18} className="text-success-600 dark:text-success-400" aria-hidden />
                ) : (
                  <Circle
                    size={18}
                    className={current ? "text-brand-600 dark:text-brand-300" : "text-ink-300 dark:text-ink-600"}
                    aria-hidden
                  />
                )}
                <span
                  className={cn(
                    "text-[11px] leading-tight",
                    complete
                      ? "text-ink-700 dark:text-ink-200"
                      : current
                        ? "font-semibold text-ink-900 dark:text-white"
                        : "text-ink-400",
                  )}
                >
                  {step.label}
                  <span className="sr-only">{complete ? " (done)" : current ? " (next)" : ""}</span>
                </span>
              </li>
            );
          })}
        </ol>

        {state === "signed" && s.changed_since_signoff.length > 0 ? (
          <AlertBanner variant="warning" title="Changed since it was signed">
            The signature stands as recorded, but it no longer describes the month as it is now:
            <ul className="mt-1 list-disc pl-5">
              {s.changed_since_signoff.map((c) => (
                <li key={`${c.input}-${c.detail}`}>{c.detail}</li>
              ))}
            </ul>
            Reopen the month to approve what is true now.
          </AlertBanner>
        ) : null}

        {state !== "signed" && readiness.blockers.length > 0 ? (
          <div className="space-y-2">
            <p className="text-sm font-semibold text-ink-800 dark:text-ink-100">Before this month can be approved</p>
            {readiness.blockers.map((b) => (
              <Blocker key={b.code} blocker={b} runId={readiness.run_id} />
            ))}
          </div>
        ) : null}

        {state !== "signed" && readiness.ready && s.open_findings > 0 ? (
          <p className="text-xs text-ink-600 dark:text-ink-300">
            {s.open_findings} finding(s) are still open. They will be listed as outstanding in the sign-off record;
            resolve or waive them first if they should not be.
          </p>
        ) : null}

        {error ? (
          <AlertBanner variant="error" title="Refused">
            {error}
          </AlertBanner>
        ) : null}

        {/* Submit */}
        {state !== "signed" && state !== "pending_approval" ? (
          canWrite ? (
            <ActionForm
              notes={notes}
              setNotes={setNotes}
              acceptReason={acceptReason}
              setAcceptReason={setAcceptReason}
              askReason={soft.length > 0}
              disabled={hard.length > 0 || needsReason || busy !== null}
              busy={busy === "submit"}
              label={state === "reopened" ? "Resubmit for approval" : "Submit for approval"}
              onSubmit={() =>
                void act(
                  "submit",
                  () =>
                    signoffApi.submit({
                      period_month: period,
                      notes: notes || null,
                      accept_incomplete_reason: acceptReason || null,
                    }),
                  "Submitted for approval",
                )
              }
            />
          ) : (
            <p className="text-xs text-ink-500">Your role can view this month but not submit it.</p>
          )
        ) : null}

        {/* Sign */}
        {state === "pending_approval" ? (
          <div className="space-y-3">
            <p className="text-sm text-ink-700 dark:text-ink-200">
              Submitted by <strong>{preparedBy ?? "—"}</strong>
              {signoff?.prepared_at ? ` on ${new Date(signoff.prepared_at).toLocaleString("en-IN")}` : ""}
              {signoff?.notes ? ` — “${signoff.notes}”` : ""}
            </p>
            {selfApproval ? (
              <AlertBanner variant="info" title="Someone else must approve this month">
                Your organisation requires an independent approver, and you prepared this month. Ask another owner
                or manager to approve it.
              </AlertBanner>
            ) : canApprove ? (
              <ActionForm
                notes={notes}
                setNotes={setNotes}
                acceptReason={acceptReason}
                setAcceptReason={setAcceptReason}
                askReason={soft.length > 0}
                disabled={hard.length > 0 || needsReason || busy !== null}
                busy={busy === "sign"}
                label="Approve and sign off"
                icon={<ShieldCheck size={15} />}
                onSubmit={() =>
                  void act(
                    "sign",
                    () =>
                      signoffApi.sign({
                        period_month: period,
                        notes: notes || null,
                        accept_incomplete_reason: acceptReason || null,
                      }),
                    "Month signed off",
                  )
                }
              />
            ) : (
              <p className="text-xs text-ink-500">Only an owner or manager can approve a month.</p>
            )}
          </div>
        ) : null}

        {/* Signed */}
        {state === "signed" && signoff ? (
          <div className="space-y-3">
            <p className="flex items-center gap-2 text-sm text-ink-800 dark:text-ink-100">
              <ShieldCheck size={16} className="text-success-600" />
              Signed by <strong>{signoff.signed_by_email}</strong>
              {signoff.signed_at ? ` on ${new Date(signoff.signed_at).toLocaleString("en-IN")}` : ""}
              {detail.data?.snapshot?.approval?.independent === false ? " (approved by the preparer)" : ""}
            </p>
            <p className="text-xs text-ink-500 dark:text-ink-400">
              Record digest <span className="font-mono">{signoff.snapshot_digest?.slice(0, 16)}…</span> ·{" "}
              {signoff.open_findings ?? 0} outstanding finding(s) recorded
            </p>
            {canApprove ? (
              <div className="flex flex-wrap items-end gap-2">
                <label className="min-w-64 flex-1 text-xs text-ink-600 dark:text-ink-300">
                  Reason for reopening
                  <input
                    value={reopenReason}
                    onChange={(e) => setReopenReason(e.target.value)}
                    className="mt-1 w-full rounded-lg border border-ink-200 bg-white px-3 py-2 text-sm dark:border-white/10 dark:bg-white/[0.04] dark:text-white"
                    placeholder="What changed, and who asked"
                  />
                </label>
                <Button
                  type="button"
                  variant="outline"
                  className="gap-2"
                  disabled={!reopenReason.trim() || busy !== null}
                  onClick={() =>
                    void act(
                      "reopen",
                      () => signoffApi.reopen({ period_month: period, reason: reopenReason }),
                      "Month reopened — the signed record is kept",
                    )
                  }
                >
                  <RotateCcw size={14} /> Reopen
                </Button>
              </div>
            ) : null}
          </div>
        ) : null}

        <p className="text-[11px] text-ink-500 dark:text-ink-400">
          {independent
            ? "Your organisation requires the approver to be someone other than the preparer."
            : "Your organisation allows the preparer to approve their own month; each sign-off records whether it was independent."}{" "}
          <Link href="/config/team" className="underline">
            Approval controls
          </Link>
        </p>

        {detail.data?.history.length ? (
          <details className="text-xs">
            <summary className="cursor-pointer font-semibold text-ink-700 dark:text-ink-200">
              History ({detail.data.history.length})
            </summary>
            <ul className="mt-2 space-y-1">
              {detail.data.history.map((h, i) => (
                <li key={i} className="text-ink-600 dark:text-ink-300">
                  {h.created_at ? new Date(h.created_at).toLocaleString("en-IN") : "—"} ·{" "}
                  {(h.from_state ?? "new").replace("_", " ")} → {h.to_state.replace("_", " ")} by{" "}
                  {h.actor_email ?? "—"}
                  {h.reason ? ` — ${h.reason}` : ""}
                </li>
              ))}
            </ul>
          </details>
        ) : null}
      </CardContent>
    </Card>
  );
}

function Blocker({ blocker, runId }: { blocker: ReadinessBlocker; runId: string | null }) {
  const action = BLOCKER_ACTION[blocker.code];
  return (
    <div
      className={cn(
        "flex flex-wrap items-start justify-between gap-2 rounded-xl border px-3 py-2.5 text-sm",
        blocker.acceptable
          ? "border-warning-200/80 bg-warning-50/60 text-warning-900 dark:border-warning-500/30 dark:bg-warning-500/10 dark:text-warning-100"
          : "border-danger-200/80 bg-danger-50/60 text-danger-900 dark:border-danger-500/25 dark:bg-danger-500/10 dark:text-danger-100",
      )}
    >
      <span className="min-w-0 flex-1">{blocker.message}</span>
      {action ? (
        <Link
          href={action.href(runId)}
          className="inline-flex shrink-0 items-center gap-1 text-xs font-semibold underline-offset-2 hover:underline"
        >
          {action.label} <ArrowRight size={12} />
        </Link>
      ) : null}
    </div>
  );
}

function ActionForm({
  notes,
  setNotes,
  acceptReason,
  setAcceptReason,
  askReason,
  disabled,
  busy,
  label,
  icon,
  onSubmit,
}: {
  notes: string;
  setNotes: (v: string) => void;
  acceptReason: string;
  setAcceptReason: (v: string) => void;
  askReason: boolean;
  disabled: boolean;
  busy: boolean;
  label: string;
  icon?: React.ReactNode;
  onSubmit: () => void;
}) {
  const field =
    "mt-1 w-full rounded-lg border border-ink-200 bg-white px-3 py-2 text-sm dark:border-white/10 dark:bg-white/[0.04] dark:text-white";
  return (
    <div className="space-y-3">
      {askReason ? (
        <label className="block text-xs font-medium text-ink-700 dark:text-ink-200">
          Why is it acceptable to approve without those checks? (required, kept in the sign-off record)
          <textarea
            value={acceptReason}
            onChange={(e) => setAcceptReason(e.target.value)}
            rows={2}
            className={field}
            placeholder="e.g. Minimum wage is assessed by the external auditor this quarter"
          />
        </label>
      ) : null}
      <label className="block text-xs font-medium text-ink-700 dark:text-ink-200">
        Notes (optional)
        <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} className={field} />
      </label>
      <Button type="button" className="gap-2" disabled={disabled} onClick={onSubmit}>
        {busy ? <Loader2 size={15} className="animate-spin" /> : icon}
        {busy ? "Working…" : label}
      </Button>
    </div>
  );
}
