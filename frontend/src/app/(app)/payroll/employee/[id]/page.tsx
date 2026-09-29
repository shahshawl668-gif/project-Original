"use client";

import Link from "next/link";
import { useEntity } from "@/context/EntityContext";
import { inr } from "@/lib/format";
import {
  monthLabel, validationApi, OUTCOME_LABEL,
  type Outcome, type RunEmployee, type ValidationRun, type Verdict,
} from "@/lib/validation";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { HelpCircle } from "lucide-react";

import { BackLink } from "@/components/layout/BackLink";
import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Stat } from "@/components/ui/kpi-card";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill, type StatusTone } from "@/components/ui/status-pill";
import { Tabs } from "@/components/ui/tabs";
import { plural } from "@/lib/format";
import { cn } from "@/lib/utils";

// ─── Types ────────────────────────────────────────────────────────────────────

type Finding = {
  employee_id: string;
  employee_name: string;
  rule_id: string;
  rule_name: string;
  component: string;
  expected_value: string;
  actual_value: string;
  difference: string;
  severity: "CRITICAL" | "WARNING" | "INFO";
  status: "FAIL" | "PASS";
  reason: string;
  suggested_fix: string;
  financial_impact: number;
};

type ResultRow = {
  employee_id: string;
  employee_name: string | null;
  pf_wage: number;
  pf_type: string;
  pf_amount_employee: number;
  pf_amount_employer: number;
  pf_breakup: { wage_capped: number; eps: number; epf: number; edli: number; admin: number };
  esic_wage: number;
  esic_eligible: boolean;
  esic_employee: number;
  esic_employer: number;
  pt_due: number;
  pt_applicable_state: string;
  lwf_employee: number;
  lwf_employer: number;
  lwf_applicable_state: string;
  paid_days: number | null;
  lop_days: number | null;
  days_in_month: number;
  increment_arrear: { applicable: boolean; expected_total: number; actual_total: number; months: number };
  prior_month: { is_joiner: boolean; is_continuing: boolean; changed_components: Record<string, { prior: number; current: number; diff: number }> };
  errors: string[];
  tds_risk_flags: string[];
  findings: Finding[];
  coverage?: Record<string, Verdict>;
  risk_score: number;
  risk_level: "LOW" | "MEDIUM" | "HIGH";
  score_breakdown: Record<string, number>;
};

// ─── Helpers ──────────────────────────────────────────────────────────────────

const fmt = (n: number | null | undefined) => inr(n, { digits: 2 });
const SEVERITY_TONE: Record<string, StatusTone> = { CRITICAL: "danger", WARNING: "warning", INFO: "info" };
const SEVERITY_LABEL: Record<string, string> = { CRITICAL: "Critical", WARNING: "Warning", INFO: "Info" };
const RISK_TONE: Record<string, StatusTone> = { HIGH: "danger", MEDIUM: "warning", LOW: "success" };

function FindingRow({ f, whyHref }: { f: Finding; whyHref: string | null }) {
  const pass = f.status === "PASS";
  return (
    <li className="px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        {pass ? <StatusPill tone="success">Passed</StatusPill> : <StatusPill tone={SEVERITY_TONE[f.severity] ?? "neutral"}>{SEVERITY_LABEL[f.severity] ?? f.severity}</StatusPill>}
        <span className="min-w-0 flex-1 text-[13px] text-ink-900"><span className="font-mono text-xs text-ink-500">{f.rule_id}</span> {f.rule_name}</span>
        {f.component ? <span className="text-xs text-ink-500">{f.component}</span> : null}
        {whyHref ? <Link href={whyHref} className="inline-flex items-center gap-1 text-xs font-medium text-brand-700 hover:underline"><HelpCircle size={12} aria-hidden /> Why?</Link> : null}
      </div>
      {f.reason ? <p className="mt-1 text-[13px] leading-relaxed text-ink-700">{f.reason}</p> : null}
      {f.expected_value || f.actual_value ? (
        <dl className="mt-1.5 flex flex-wrap gap-x-5 gap-y-0.5 text-xs">
          <div className="flex gap-1"><dt className="text-ink-500">Actual</dt><dd className="num font-medium text-ink-900">{f.actual_value || "—"}</dd></div>
          <div className="flex gap-1"><dt className="text-ink-500">Expected</dt><dd className="num font-medium text-ink-900">{f.expected_value || "—"}</dd></div>
          {f.difference && f.difference !== "0.00" ? <div className="flex gap-1"><dt className="text-ink-500">Difference</dt><dd className="num font-medium text-ink-900">{f.difference}</dd></div> : null}
          {!pass ? <div className="flex gap-1"><dt className="text-ink-500">Impact</dt><dd className="font-medium text-ink-900">{f.financial_impact > 0 ? <span className="num">{inr(f.financial_impact)}</span> : <span className="italic text-ink-400">not calculated</span>}</dd></div> : null}
        </dl>
      ) : null}
      {f.suggested_fix && !pass ? <p className="mt-1.5 rounded-md bg-brand-50 px-2.5 py-1.5 text-xs text-ink-800"><span className="font-medium text-brand-800">Suggested correction: </span>{f.suggested_fix}</p> : null}
    </li>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

function EmployeeDrilldown() {
  const { entity } = useEntity();
  const params = useParams();
  const rawId = params?.id as string | undefined;
  const employeeId = rawId ? decodeURIComponent(rawId) : "";

  const searchParams = useSearchParams();
  const runParam = searchParams.get("run");
  const [empData, setEmpData] = useState<ResultRow | null>(null);
  const [run, setRun] = useState<ValidationRun | null>(null);
  const [sourceRow, setSourceRow] = useState<Record<string, unknown> | null>(null);
  const [employee, setEmployee] = useState<RunEmployee | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [filterSev, setFilterSev] = useState<"ALL" | "CRITICAL" | "WARNING" | "INFO" | "PASS">("ALL");

  useEffect(() => {
    let cancelled = false;
    setEmpData(null);
    setRun(null);
    setSourceRow(null);
    setEmployee(null);
    setLoadError(null);
    if (!employeeId || !entity) return;
    (async () => {
      try {
        let id = runParam;
        if (!id) {
          const latest = await validationApi.runs({ include_superseded: false, limit: 1 });
          if (!latest.length) throw new Error("No validation run exists for this company yet.");
          id = latest[0].id;
        }
        const detail = await validationApi.employee(id, employeeId);
        if (cancelled) return;
        setRun(detail.run);
        setSourceRow(detail.source_row);
        setEmployee(detail.employee);
        setEmpData(detail.result as unknown as ResultRow);
      } catch (err) {
        if (!cancelled) setLoadError(err instanceof Error ? err.message : "Could not load this employee.");
      }
    })();
    return () => { cancelled = true; };
  }, [employeeId, entity, runParam]);

  const backHref = run ? `/payroll/results?run=${encodeURIComponent(run.id)}` : "/payroll/results";
  const runId = run?.id;
  // Finding ids, for the "Why?" links: the employee result carries the
  // findings but not the records they were stored as.
  const ids = useQuery({
    queryKey: ["run-findings", runId, "employee", employeeId],
    queryFn: () => validationApi.findings(runId!, { employee_id: employeeId, page_size: 200 }),
    enabled: !!runId && !!employeeId,
  });
  const whyFor = (f: Finding) => {
    const hit = ids.data?.items.find((x) => x.rule_id === f.rule_id && (x.component ?? "") === (f.component ?? ""))
      ?? ids.data?.items.find((x) => x.rule_id === f.rule_id);
    return hit && runId ? `/payroll/results/why?run=${encodeURIComponent(runId)}&finding=${encodeURIComponent(hit.id)}` : null;
  };

  const allFindings = useMemo(() => empData?.findings ?? [], [empData]);
  const filteredFindings = useMemo(() => allFindings.filter((f) => {
    if (filterSev === "ALL") return f.status === "FAIL";
    if (filterSev === "PASS") return f.status === "PASS";
    return f.status === "FAIL" && f.severity === filterSev;
  }), [allFindings, filterSev]);

  const fails = allFindings.filter((f) => f.status === "FAIL");
  const crit = fails.filter((f) => f.severity === "CRITICAL");
  const warn = fails.filter((f) => f.severity === "WARNING");
  const infos = fails.filter((f) => f.severity === "INFO");
  const passes = allFindings.filter((f) => f.status === "PASS");
  // The run's de-duplicated figure for this employee, not a raw sum that
  // would count the same rupees once per overlapping check.
  const totalImpact = employee?.financial_impact ?? null;
  const cannot = empData?.coverage ? Object.values(empData.coverage).filter((v) => v.outcome === "cannot_validate").length : null;

  if (!empData) {
    return (
      <div className="space-y-5">
        <BackLink fallback={backHref}>Back to results</BackLink>
        {loadError ? (
          <AlertBanner variant="error" title="This employee could not be opened">{loadError} The employee may not be in this run, or the run may belong to another company.</AlertBanner>
        ) : !employeeId ? (
          <AlertBanner variant="info">No employee was named in the link.</AlertBanner>
        ) : (
          <div className="space-y-4"><Skeleton className="h-10 w-72" /><div className="grid grid-cols-2 gap-3 md:grid-cols-4">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-24 rounded-xl" />)}</div><Skeleton className="h-72 w-full rounded-xl" /></div>
        )}
      </div>
    );
  }

  const breakdown = Object.entries(empData.score_breakdown ?? {}).filter(([, v]) => v > 0).sort((x, y) => y[1] - x[1]);
  const maxB = Math.max(1, ...breakdown.map(([, v]) => v));

  return (
    <div className="space-y-5">
      <BackLink fallback={backHref}>Back to results</BackLink>
      <PageHeader
        title={empData.employee_name || empData.employee_id}
        description={
          <>
            <span className="font-mono">{empData.employee_id}</span>
            {run ? <> · {monthLabel(run.period_month)} · run {run.run_number} ({run.status})</> : null}
            {run?.upload ? <> · {run.upload.filename ?? "register"}, revision {run.upload.revision}</> : null}
            {sourceRow && typeof sourceRow["_source_row"] === "number" ? <> · file row {sourceRow["_source_row"] as number}</> : null}
          </>
        }
        meta={<StatusPill tone={RISK_TONE[empData.risk_level] ?? "neutral"}>Risk {empData.risk_level.toLowerCase()} · score <span className="num">{empData.risk_score}</span></StatusPill>}
      />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Failed checks" value={fails.length} tone={crit.length ? "danger" : fails.length ? "warning" : "neutral"} qualifier={`${crit.length} critical · ${warn.length} warning · ${infos.length} info`} />
        <Stat label="Checks passed" value={passes.length} qualifier="that ran and agreed" />
        <Stat label="Could not validate" value={cannot} tone={cannot ? "warning" : "neutral"} qualifier="an input was missing" />
        <Stat label="Impact" value={totalImpact == null ? (fails.length ? "Not priced" : "—") : inr(totalImpact)} qualifier="counted once across overlapping checks" />
      </div>

      <div className="grid gap-4 xl:grid-cols-[1fr_22rem]">
        <section className="rounded-xl border border-ink-200 bg-white shadow-soft" aria-labelledby="findings-h">
          <header className="px-4 pt-3">
            <h2 id="findings-h" className="text-[15px] font-semibold text-ink-900">Checks for this employee</h2>
            <Tabs
              className="mt-2"
              label="Filter findings"
              value={filterSev}
              onChange={(v) => setFilterSev(v as typeof filterSev)}
              items={[
                { id: "ALL", label: "All failed", count: fails.length },
                { id: "CRITICAL", label: "Critical", count: crit.length },
                { id: "WARNING", label: "Warning", count: warn.length },
                { id: "INFO", label: "Info", count: infos.length },
                { id: "PASS", label: "Passed", count: passes.length },
              ]}
            />
          </header>
          {filteredFindings.length ? (
            <ul className="divide-y divide-ink-100">{filteredFindings.map((f, i) => <FindingRow key={i} f={f} whyHref={f.status === "FAIL" ? whyFor(f) : null} />)}</ul>
          ) : (
            <p className="px-4 py-8 text-center text-[13px] text-ink-500">{filterSev === "PASS" ? "No passed checks were recorded as findings." : "No failed checks in this category."} The outcome of every check is listed below.</p>
          )}
        </section>

        <div className="space-y-4">
          <section className="rounded-xl border border-ink-200 bg-white p-4 shadow-soft" aria-labelledby="snap-h">
            <h2 id="snap-h" className="text-[13px] font-semibold text-ink-900">Statutory snapshot</h2>
            <p className="text-xs text-ink-500">As computed by this run</p>
            <dl className="mt-2 divide-y divide-ink-100 text-[13px]">
              {[
                ["PF wage", fmt(empData.pf_wage)],
                ["PF employee", fmt(empData.pf_amount_employee)],
                ["PF employer", fmt(empData.pf_amount_employer)],
                ["ESIC", empData.esic_eligible ? "Covered" : "Exempt"],
                ["ESIC employee", empData.esic_eligible ? fmt(empData.esic_employee) : "—"],
                ["ESIC employer", empData.esic_eligible ? fmt(empData.esic_employer) : "—"],
                ["PT", empData.pt_due > 0 ? fmt(empData.pt_due) : "Nil"],
                ["PT state", empData.pt_applicable_state || "—"],
                ["LWF employee", empData.lwf_employee > 0 ? fmt(empData.lwf_employee) : "Nil"],
                ["LWF employer", empData.lwf_employer > 0 ? fmt(empData.lwf_employer) : "Nil"],
                ["Paid days", empData.paid_days != null ? String(empData.paid_days) : "Not supplied"],
                ["LOP days", empData.lop_days != null ? String(empData.lop_days) : "Not supplied"],
              ].map(([k, v]) => (
                <div key={k} className="flex justify-between gap-3 py-1.5">
                  <dt className="text-ink-500">{k}</dt>
                  <dd className={cn("num text-right font-medium", v === "Not supplied" ? "font-normal text-ink-400" : "text-ink-900")}>{v}</dd>
                </div>
              ))}
            </dl>
          </section>
          {breakdown.length ? (
            <section className="rounded-xl border border-ink-200 bg-white p-4 shadow-soft" aria-labelledby="risk-h">
              <h2 id="risk-h" className="text-[13px] font-semibold text-ink-900">What drives the risk score</h2>
              <ul className="mt-2 space-y-1.5">
                {breakdown.map(([k, v]) => (
                  <li key={k}>
                    <div className="flex justify-between text-xs"><span className="text-ink-700">{k.replace(/_/g, " ")}</span><span className="num font-medium text-ink-900">{v}</span></div>
                    <div className="mt-0.5 h-1.5 rounded-full bg-ink-100"><div className="h-full rounded-full bg-ink-400" style={{ width: `${(v / maxB) * 100}%` }} /></div>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </div>
      </div>

      <CoverageList coverage={empData.coverage} />
    </div>
  );
}

const OUTCOME_ORDER: Outcome[] = ["failed", "cannot_validate", "passed", "not_applicable", "disabled"];
const OUTCOME_CHIP: Record<Outcome, string> = {
  passed: "bg-success-100 text-success-800",
  failed: "bg-danger-100 text-danger-800",
  cannot_validate: "bg-warning-100 text-warning-800",
  not_applicable: "bg-ink-100 text-ink-600",
  disabled: "bg-ink-100 text-ink-500",
};

/** Every check's outcome for this employee — what ran, what could not, and why. */
function CoverageList({ coverage }: { coverage?: Record<string, Verdict> }) {
  const [show, setShow] = useState<Outcome>("cannot_validate");
  if (!coverage) {
    return (
      <p className="rounded-xl border border-dashed border-ink-200 px-4 py-3 text-sm text-ink-500">
        This run predates per-check outcomes, so which checks could not run is not recorded. Revalidate to see it.
      </p>
    );
  }
  const entries = Object.entries(coverage);
  const counts = Object.fromEntries(
    OUTCOME_ORDER.map((o) => [o, entries.filter(([, v]) => v.outcome === o).length]),
  ) as Record<Outcome, number>;
  const rows = entries.filter(([, v]) => v.outcome === show);
  return (
    <div className="rounded-xl border border-ink-200 bg-white p-4 shadow-soft">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-[15px] font-semibold text-ink-900">
          Every check&apos;s outcome ({plural(entries.length, "check")})
        </h2>
        <div className="flex flex-wrap gap-1">
          {OUTCOME_ORDER.map((o) => (
            <button key={o} type="button" onClick={() => setShow(o)} aria-pressed={show === o}
              className={`rounded-md px-2.5 py-1 text-xs font-medium ${show === o ? OUTCOME_CHIP[o] + " ring-1 ring-current" : "bg-ink-50 text-ink-600 hover:bg-ink-100"}`}>
              {OUTCOME_LABEL[o]} {counts[o]}
            </button>
          ))}
        </div>
      </div>
      {rows.length === 0 ? (
        <p className="text-sm text-ink-500">No checks with this outcome.</p>
      ) : (
        <ul className="divide-y divide-ink-100 text-sm">
          {rows.map(([rule, v]) => (
            <li key={rule} className="flex flex-wrap gap-x-3 gap-y-0.5 py-2">
              <span className="w-20 shrink-0 font-mono text-xs text-ink-500">{rule}</span>
              <span className="min-w-0 flex-1 text-ink-700">{v.reason || OUTCOME_LABEL[v.outcome]}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function EmployeeDrilldownPage() {
  return (
    <Suspense fallback={<Skeleton className="h-96 w-full rounded-xl" />}>
      <EmployeeDrilldown />
    </Suspense>
  );
}
