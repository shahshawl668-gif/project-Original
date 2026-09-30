"use client";

import { useEntity } from "@/context/EntityContext";
import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { monthLabel, validationApi, type ValidationJob } from "@/lib/validation";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { CheckCircle2, Clock, Loader2, RotateCcw, ShieldCheck, UploadCloud, XCircle } from "lucide-react";
import { IntegrationPanel } from "@/components/studio/IntegrationPanel";

const STAGES = ["queued", "loading", "validating", "recording", "succeeded"] as const;
const STAGE_TEXT: Record<string, string> = {
  queued: "Queued",
  loading: "Reading register",
  validating: "Checking employees",
  recording: "Saving results",
  succeeded: "Finished",
};

function elapsed(from: string | null, to: string | null): string {
  if (!from) return "";
  const start = new Date(from).getTime();
  const end = to ? new Date(to).getTime() : Date.now();
  const s = Math.max(0, Math.round((end - start) / 1000));
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
}

function JobProgress({ jobId }: { jobId: string }) {
  const router = useRouter();
  const { entity } = useEntity();
  const [job, setJob] = useState<ValidationJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const started = useRef(Date.now());
  const entityAtStart = useRef<string | null>(null);

  const load = useCallback(async () => {
    try {
      const next = await validationApi.job(jobId);
      setJob(next);
      setError(null);
      return next;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not read this validation.");
      return null;
    }
  }, [jobId]);

  useEffect(() => {
    // Switching company mid-poll: this job belongs to the other company, and
    // asking for it now would (correctly) 404. Say so rather than spin.
    if (entityAtStart.current && entity?.id && entity.id !== entityAtStart.current) {
      setJob(null);
      setError("You switched company. This validation belongs to the previous one.");
      return;
    }
    entityAtStart.current = entity?.id ?? null;
  }, [entity?.id]);

  useEffect(() => {
    let stop = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = async () => {
      const next = await load();
      if (stop) return;
      if (next && (next.state === "queued" || next.state === "running")) {
        // Poll briskly at first, then ease off for a long job.
        const wait = Date.now() - started.current > 60_000 ? 3000 : 1200;
        timer = setTimeout(() => void tick(), wait);
      }
      if (next?.state === "succeeded" && next.run_id) {
        timer = setTimeout(() => router.push(`/payroll/results?run=${encodeURIComponent(next.run_id!)}`), 1200);
      }
    };
    void tick();
    return () => {
      stop = true;
      if (timer) clearTimeout(timer);
    };
  }, [load, router]);

  const cancel = async () => {
    if (!job) return;
    setBusy(true);
    try {
      setJob(await validationApi.cancel(job.id));
      toast.info("Stopping validation", { description: "Nothing from this attempt will be kept." });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not cancel.");
    } finally {
      setBusy(false);
    }
  };

  const retry = async () => {
    if (!job) return;
    setBusy(true);
    try {
      const { job: next } = await validationApi.retry(job.id);
      router.replace(`/payroll/validation?job=${encodeURIComponent(next.id)}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not retry.");
    } finally {
      setBusy(false);
    }
  };

  if (error && !job) {
    return (
      <AlertBanner variant="error" title="This validation is not available">
        {error}{" "}
        <Link href="/payroll/validation" className="font-semibold underline">See recent validations</Link>
      </AlertBanner>
    );
  }
  if (!job) {
    return <Skeleton className="h-56 w-full rounded-2xl" />;
  }

  const active = job.state === "queued" || job.state === "running";
  const currentIndex = STAGES.indexOf((job.state === "succeeded" ? "succeeded" : job.stage) as (typeof STAGES)[number]);

  return (
    <div className="space-y-5">
      <div className="rounded-2xl border border-ink-200/70 bg-white p-6 shadow-soft">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-2xs font-semibold tracking-[0.06em] text-ink-500">
              {monthLabel(job.period_month)} · job {job.id.slice(0, 8)}
            </p>
            <h2 className="mt-1 flex items-center gap-2 font-display text-xl font-bold text-ink-900">
              {job.state === "succeeded" ? (
                <CheckCircle2 className="text-success-600" size={22} />
              ) : job.state === "failed" ? (
                <XCircle className="text-danger-600" size={22} />
              ) : job.state === "cancelled" ? (
                <XCircle className="text-ink-500" size={22} />
              ) : (
                <Loader2 className="animate-spin text-brand-600" size={22} />
              )}
              {job.cancel_requested && active ? "Stopping…" : job.stage_label}
            </h2>
            <p className="mt-1 text-sm text-ink-600" aria-live="polite">
              {job.employee_total
                ? `${job.employee_done.toLocaleString("en-IN")} of ${job.employee_total.toLocaleString("en-IN")} employees checked`
                : "Counting employees…"}
              {job.started_at ? ` · ${elapsed(job.started_at, job.finished_at)}` : ""}
              {job.state === "queued" && job.queue_position ? ` · ${job.queue_position} ahead in the queue` : ""}
            </p>
          </div>
          <div className="flex gap-2">
            {job.can_cancel ? (
              <Button type="button" variant="outline" disabled={busy || job.cancel_requested} onClick={() => void cancel()}>
                Cancel
              </Button>
            ) : null}
            {job.can_retry ? (
              <Button type="button" disabled={busy} onClick={() => void retry()} className="gap-2">
                <RotateCcw size={15} /> Retry
              </Button>
            ) : null}
            {job.state === "succeeded" && job.run_id ? (
              <Button asChild className="gap-2">
                <Link href={`/payroll/results?run=${encodeURIComponent(job.run_id)}`}>
                  <ShieldCheck size={15} /> View results
                </Link>
              </Button>
            ) : null}
          </div>
        </div>

        <div
          className="mt-5 h-2.5 w-full overflow-hidden rounded-full bg-ink-100"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={job.percent}
          aria-label="Validation progress"
        >
          <div
            className={`h-2.5 rounded-full transition-all ${job.state === "failed" ? "bg-danger-500" : job.state === "cancelled" ? "bg-ink-400" : "bg-brand-600"}`}
            style={{ width: `${job.state === "succeeded" ? 100 : job.percent}%` }}
          />
        </div>

        <ol className="mt-5 grid grid-cols-2 gap-2 text-xs sm:grid-cols-5">
          {STAGES.map((stage, i) => {
            const done = currentIndex > i || job.state === "succeeded";
            const current = currentIndex === i && active;
            return (
              <li
                key={stage}
                className={`rounded-lg border px-3 py-2 font-semibold ${
                  done
                    ? "border-success-200 bg-success-50 text-success-700"
                    : current
                      ? "border-brand-300 bg-brand-50 text-brand-800"
                      : "border-ink-200 text-ink-500"
                }`}
              >
                {STAGE_TEXT[stage]}
              </li>
            );
          })}
        </ol>
      </div>

      {!job.worker_enabled && active ? (
        <AlertBanner variant="warning" title="Background validation is switched off on this server">
          This validation will wait until an administrator enables the validation worker
          (VALIDATION_WORKER_ENABLED) or starts a separate worker process.
        </AlertBanner>
      ) : null}

      {job.state === "queued" && job.error ? (
        <AlertBanner variant="warning" title="Retrying">{job.error}</AlertBanner>
      ) : null}
      {job.state === "failed" ? (
        <AlertBanner variant="error" title="Validation failed">
          {job.error || "Validation failed."} Nothing from this attempt was saved, so retrying is safe.
        </AlertBanner>
      ) : null}
      {job.state === "cancelled" ? (
        <AlertBanner variant="info" title="Cancelled">
          This validation was stopped before it finished. No results were saved.
        </AlertBanner>
      ) : null}
      {active ? (
        <p className="flex items-center gap-2 text-sm text-ink-500">
          <Clock size={14} /> You can leave this page. The validation keeps running, and the upload page links back here.
        </p>
      ) : null}
      <IntegrationPanel period={job.period_month} />
    </div>
  );
}

function RecentJobs() {
  const { entity } = useEntity();
  const [jobs, setJobs] = useState<ValidationJob[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setJobs(null);
    validationApi
      .jobs({ limit: 20 })
      .then((j) => { if (!cancelled) setJobs(j); })
      .catch((err) => { if (!cancelled) setError(err instanceof Error ? err.message : "Could not load validations."); });
    return () => { cancelled = true; };
  }, [entity?.id]);

  if (error) return <AlertBanner variant="error" title="Could not load validations">{error}</AlertBanner>;
  if (!jobs) return <Skeleton className="h-40 w-full rounded-2xl" />;
  if (jobs.length === 0) {
    return (
      <EmptyState
        icon={<ShieldCheck className="h-7 w-7 text-ink-500" strokeWidth={1.5} />}
        title="No validations yet"
        description="Upload a salary register to queue its validation."
        action={<Button asChild><Link href="/payroll/upload" className="gap-2"><UploadCloud size={15} /> Upload register</Link></Button>}
      />
    );
  }
  return (
    <div className="overflow-x-auto rounded-2xl border border-ink-200/70 bg-white shadow-soft">
      <table className="w-full text-sm">
        <thead className="bg-ink-50/80 text-left text-[11px] text-ink-500">
          <tr>
            <th className="px-4 py-2.5">Month</th>
            <th className="px-4 py-2.5">Status</th>
            <th className="px-4 py-2.5">Employees</th>
            <th className="px-4 py-2.5">Queued</th>
            <th className="px-4 py-2.5" />
          </tr>
        </thead>
        <tbody className="divide-y divide-ink-100">
          {jobs.map((j) => (
            <tr key={j.id}>
              <td className="px-4 py-3 font-medium">{monthLabel(j.period_month)}</td>
              <td className="px-4 py-3">{j.stage_label}{j.error_code && j.state === "failed" ? ` — ${j.error}` : ""}</td>
              <td className="num px-4 py-3">{j.employee_total ? j.employee_total.toLocaleString("en-IN") : "—"}</td>
              <td className="px-4 py-3 text-ink-500">{j.queued_at ? new Date(j.queued_at).toLocaleString("en-IN") : "—"}</td>
              <td className="px-4 py-3 text-right">
                {j.state === "succeeded" && j.run_id ? (
                  <Link className="font-semibold text-brand-700" href={`/payroll/results?run=${encodeURIComponent(j.run_id)}`}>Results</Link>
                ) : (
                  <Link className="font-semibold text-brand-700" href={`/payroll/validation?job=${encodeURIComponent(j.id)}`}>Details</Link>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ValidationContent() {
  const params = useSearchParams();
  const jobId = params.get("job");
  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <PageHeader
        title={jobId ? "Validation progress" : "Validation runs"}
        description="Validation runs on the server. Close this page whenever you like — the result is kept and linked from here."
        actions={
          <Button variant="outline" asChild>
            <Link href="/payroll/upload" className="gap-2"><UploadCloud size={15} /> Upload register</Link>
          </Button>
        }
      />
      {jobId ? <JobProgress jobId={jobId} /> : <RecentJobs />}
    </div>
  );
}

export default function ValidationPage() {
  return (
    <Suspense fallback={<Skeleton className="h-56 w-full rounded-2xl" />}>
      <ValidationContent />
    </Suspense>
  );
}
