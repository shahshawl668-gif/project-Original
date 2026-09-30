"use client";

import { useEntity } from "@/context/EntityContext";
import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { inr, monthLabel, validationApi, type ComparedFinding, type RunComparison } from "@/lib/validation";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { ArrowLeft, ArrowRight } from "lucide-react";

type Group = "new" | "resolved" | "changed" | "unchanged";
const GROUPS: { id: Group; label: string; meaning: string; tone: string }[] = [
  { id: "new", label: "New", meaning: "In the later run only", tone: "border-danger-200 bg-danger-50 text-danger-800" },
  { id: "resolved", label: "Resolved", meaning: "In the earlier run only", tone: "border-success-200 bg-success-50 text-success-800" },
  { id: "changed", label: "Changed", meaning: "In both, with different values", tone: "border-warning-200 bg-warning-50 text-warning-800" },
  { id: "unchanged", label: "Unchanged", meaning: "In both, identical", tone: "border-ink-200 bg-ink-50 text-ink-700" },
];

function Row({ f }: { f: ComparedFinding }) {
  return (
    <tr className="align-top">
      <td className="px-4 py-3 font-mono text-xs">{f.employee_id}<div className="font-sans text-ink-500">{f.employee_name}</div></td>
      <td className="px-4 py-3 text-xs"><span className="font-mono font-semibold">{f.rule_id}</span> · {f.rule_name}
        {f.component ? <div className="text-ink-500">{f.component}</div> : null}</td>
      <td className="px-4 py-3 text-xs">{f.severity}</td>
      <td className="px-4 py-3 text-xs">
        {f.before ? (
          <>
            <div className="text-ink-500 line-through">exp {f.before.expected_value ?? "—"} / act {f.before.actual_value ?? "—"} · {inr(f.before.financial_impact, 2)}</div>
            <div>exp {f.expected_value ?? "—"} / act {f.actual_value ?? "—"} · {inr(f.financial_impact, 2)}</div>
          </>
        ) : (
          <>exp {f.expected_value ?? "—"} / act {f.actual_value ?? "—"}</>
        )}
      </td>
      <td className="num px-4 py-3 text-right text-xs">{inr(f.financial_impact, 2)}</td>
    </tr>
  );
}

function CompareContent() {
  const params = useSearchParams();
  const { entity } = useEntity();
  const base = params.get("base");
  const target = params.get("target");
  const [data, setData] = useState<RunComparison | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [group, setGroup] = useState<Group>("new");

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    if (!base || !target) { setError("Choose two runs to compare."); return; }
    validationApi.compare(base, target)
      .then((d) => { if (!cancelled) setData(d); })
      .catch((err) => { if (!cancelled) setError(err instanceof Error ? err.message : "Could not compare these runs."); });
    return () => { cancelled = true; };
  }, [base, target, entity?.id]);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Run history"
        title="Compare validation runs"
        description={data ? (
          <>
            {monthLabel(data.base.period_month)} run #{data.base.run_number} → {monthLabel(data.target.period_month)} run #{data.target.run_number}.
            Findings are matched by employee, rule and component.
          </>
        ) : "Findings are matched by employee, rule and component."}
        actions={target ? (
          <Button variant="outline" asChild>
            <Link href={`/payroll/results?run=${encodeURIComponent(target)}`} className="gap-2"><ArrowLeft size={15} /> Back to results</Link>
          </Button>
        ) : undefined}
      />
      {error ? <AlertBanner variant="error" title="Comparison unavailable">{error}</AlertBanner> : null}
      {!data && !error ? <Skeleton className="h-64 w-full rounded-2xl" /> : null}
      {data ? (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {GROUPS.map((g) => (
              <button key={g.id} type="button" onClick={() => setGroup(g.id)}
                className={`rounded-2xl border p-4 text-left shadow-soft ${g.tone} ${group === g.id ? "ring-2 ring-brand-500" : ""}`}>
                <p className="text-2xs font-semibold tracking-[0.06em]">{g.label}</p>
                <p className="num text-2xl font-bold">{data.counts[g.id].toLocaleString("en-IN")}</p>
                <p className="text-xs">{g.meaning} · {inr(data.financial_impact[g.id])}</p>
              </button>
            ))}
          </div>
          <div className="overflow-x-auto rounded-2xl border border-ink-200/70 bg-white shadow-soft">
            <table className="w-full text-sm">
              <thead className="bg-ink-50/80 text-left text-[11px] text-ink-500">
                <tr>
                  <th className="px-4 py-2.5">Employee</th>
                  <th className="px-4 py-2.5">Rule</th>
                  <th className="px-4 py-2.5">Severity</th>
                  <th className="px-4 py-2.5">Values {group === "changed" ? "(before → after)" : ""}</th>
                  <th className="px-4 py-2.5 text-right">Impact</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-100">
                {data.items[group].length === 0 ? (
                  <tr><td colSpan={5} className="px-4 py-10 text-center text-ink-500">Nothing in this group.</td></tr>
                ) : data.items[group].map((f) => <Row key={f.fingerprint} f={f} />)}
              </tbody>
            </table>
          </div>
          {data.truncated[group] ? (
            <p className="text-xs text-ink-500">
              Showing the {data.items[group].length.toLocaleString("en-IN")} largest by impact. The Excel export of each run has every finding.
            </p>
          ) : null}
          <p className="flex items-center gap-1 text-xs text-ink-500">
            <Link className="font-semibold text-brand-700" href={`/payroll/results?run=${encodeURIComponent(data.base.id)}`}>Open run #{data.base.run_number}</Link>
            <ArrowRight size={12} />
            <Link className="font-semibold text-brand-700" href={`/payroll/results?run=${encodeURIComponent(data.target.id)}`}>Open run #{data.target.run_number}</Link>
          </p>
        </>
      ) : null}
    </div>
  );
}

export default function ComparePage() {
  return (
    <Suspense fallback={<Skeleton className="h-64 w-full rounded-2xl" />}>
      <CompareContent />
    </Suspense>
  );
}
