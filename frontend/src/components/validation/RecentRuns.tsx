"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ShieldCheck } from "lucide-react";

import { useEntity } from "@/context/EntityContext";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { monthLabel, validationApi, type ValidationJob } from "@/lib/validation";

/** Every validation of this company, newest first: finished ones link to their results, others to their progress. */
export function RecentRuns() {
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
        description="A month is checked from the Payroll Control Centre; every run is listed here."
        action={<Button asChild><Link href="/control-centre">Go to the Control Centre</Link></Button>}
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
