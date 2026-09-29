"use client";

import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { fmtTime } from "@/components/studio/RunBits";
import { STEP_VARIANT, type Run, type WorkflowStep } from "@/lib/studio";

/** A workflow run's steps: what each did, what it started, how it ended. */
export function WorkflowSteps({ run }: { run: Run }) {
  const wf = run.workflow!;
  const trigger = wf.trigger as { type?: string; event?: string; by?: string; slot?: string };
  return (
    <Card><CardContent className="space-y-3 py-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-semibold text-ink-900 dark:text-white">Steps</h2>
        <span className="text-xs text-ink-500">
          Triggered by {trigger.type === "manual" ? `hand (${trigger.by ?? "a person"})` : trigger.type === "schedule" ? `schedule (${trigger.slot ?? ""})` : `event ${trigger.event ?? trigger.type}`}
          {wf.period ? ` · month ${wf.period.slice(0, 7)}` : ""} · {String(run.versions?.workflow ?? "")}
          {run.links.workflow_id ? <> · <Link className="underline" href={`/studio/workflows/${run.links.workflow_id}`}>workflow</Link></> : null}
        </span>
      </div>
      <ol className="space-y-2">{wf.steps.map((s) => <StepRow key={s.index} step={s} />)}</ol>
      {wf.failure_branch.length ? (
        <>
          <h3 className="pt-2 text-sm font-semibold">Failure branch</h3>
          <ol className="space-y-2">{wf.failure_branch.map((s) => <StepRow key={`f${s.index}`} step={s} />)}</ol>
        </>
      ) : null}
      {wf.validation_run_id ? <p className="text-sm"><Link className="font-semibold text-brand-700 underline" href={`/payroll/results?run=${encodeURIComponent(wf.validation_run_id)}`}>Validation results</Link> produced by this run.</p> : null}
    </CardContent></Card>
  );
}

function StepRow({ step }: { step: WorkflowStep }) {
  return (
    <li className="rounded-xl border border-ink-200 p-3 text-sm dark:border-white/10">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-medium">{step.index + 1}. {step.label}</span>
        <span className="flex items-center gap-2 text-xs text-ink-500">
          {step.attempt && step.attempt > 1 ? `attempt ${step.attempt}` : null}
          {step.finished_at ? fmtTime(step.finished_at) : step.started_at ? `since ${fmtTime(step.started_at)}` : null}
          <Badge variant={STEP_VARIANT[step.status] ?? "secondary"}>{step.status}</Badge>
        </span>
      </div>
      {step.message ? <p className="mt-1 text-xs text-ink-600 dark:text-ink-300">{step.message}</p> : null}
      {step.ref?.run_id ? <Link className="text-xs text-brand-700 underline" href={`/studio/runs/${step.ref.run_id}`}>Open the run it started</Link> : null}
      {step.ref?.job_id ? <Link className="ml-3 text-xs text-brand-700 underline" href={`/payroll/validation?job=${step.ref.job_id}`}>Open the validation</Link> : null}
    </li>
  );
}
