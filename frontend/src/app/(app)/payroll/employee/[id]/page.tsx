"use client";

import Link from "next/link";
import { useEntity } from "@/context/EntityContext";
import {
  inr, monthLabel, validationApi, OUTCOME_LABEL,
  type Outcome, type RunEmployee, type ValidationRun, type Verdict,
} from "@/lib/validation";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import {
  RadarChart, Radar, PolarGrid, PolarAngleAxis,
  ResponsiveContainer, Tooltip,
} from "recharts";
import {
  ArrowLeft, ShieldCheck, AlertTriangle, XCircle,
  CheckCircle2, Info, ChevronDown, ChevronUp, Activity,
} from "lucide-react";

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

const fmt = (n: number | null | undefined, digits = 2) =>
  n == null ? "–" : `₹${n.toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;

const SEV_STYLES: Record<string, { card: string; badge: string; icon: React.ReactNode }> = {
  CRITICAL: {
    card: "bg-danger-50/80 border-danger-200/80",
    badge:
      "bg-danger-100 text-danger-800 border border-danger-200",
    icon: <XCircle size={16} className="mt-0.5 shrink-0 text-danger-600" />,
  },
  WARNING: {
    card: "bg-warn-50/80 border-warn-200/80",
    badge:
      "bg-warn-100 text-warn-800 border border-warn-200",
    icon: <AlertTriangle size={16} className="mt-0.5 shrink-0 text-warn-600" />,
  },
  INFO: {
    card: "bg-brand-50/70 border-brand-100",
    badge:
      "bg-brand-100 text-brand-800 border border-brand-100",
    icon: <Info size={16} className="mt-0.5 shrink-0 text-brand-500" />,
  },
  PASS: {
    card: "bg-success-50/80 border-success-100",
    badge:
      "bg-success-100 text-success-800 border border-success-100",
    icon: <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-success-600" />,
  },
};

const RISK_META: Record<string, { bar: string; bg: string; text: string }> = {
  HIGH: {
    bar: "bg-danger-500",
    bg: "bg-danger-50/80 border-danger-200/80",
    text: "text-danger-700",
  },
  MEDIUM: {
    bar: "bg-warn-500",
    bg: "bg-warn-50/80 border-warn-200/80",
    text: "text-warn-700",
  },
  LOW: {
    bar: "bg-success-500",
    bg: "bg-success-50/80 border-success-200",
    text: "text-success-700",
  },
};

function FindingCard({ f }: { f: Finding }) {
  const [open, setOpen] = useState(true);
  const s = f.status === "PASS" ? SEV_STYLES.PASS : SEV_STYLES[f.severity] ?? SEV_STYLES.INFO;
  return (
    <div className={`overflow-hidden rounded-xl border ${s.card}`}>
      <button
        className="flex w-full items-start gap-3 p-4 text-left"
        onClick={() => setOpen((o) => !o)}
      >
        {s.icon}
        <div className="min-w-0 flex-1">
          <div className="mb-0.5 flex flex-wrap items-center gap-2">
            <span className={`rounded px-1.5 py-0.5 font-mono text-xs font-semibold ${s.badge}`}>
              {f.rule_id}
            </span>
            <span className={`rounded px-1.5 py-0.5 text-xs font-semibold ${s.badge}`}>
              {f.status === "PASS" ? "PASS" : f.severity}
            </span>
            <span className="text-sm font-semibold text-ink-800">
              {f.rule_name}
            </span>
            <span className="text-xs text-ink-400">· {f.component}</span>
          </div>
          <p className="line-clamp-1 text-sm text-ink-600">{f.reason}</p>
        </div>
        <div className="ml-2 shrink-0 text-ink-400">
          {open ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </div>
      </button>
      {open && (
        <div className="space-y-3 border-t border-black/5 px-4 pb-4 pt-3">
          {(f.expected_value || f.actual_value) && (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              {f.expected_value && (
                <div className="rounded-lg bg-white/70 p-3 text-xs">
                  <p className="mb-0.5 text-ink-400">Expected</p>
                  <p className="font-semibold text-ink-800">
                    {f.expected_value}
                  </p>
                </div>
              )}
              {f.actual_value && (
                <div className="rounded-lg bg-white/70 p-3 text-xs">
                  <p className="mb-0.5 text-ink-400">Actual</p>
                  <p className="font-semibold text-ink-800">{f.actual_value}</p>
                </div>
              )}
              {f.difference && f.difference !== "0.00" && (
                <div className="rounded-lg bg-white/70 p-3 text-xs">
                  <p className="mb-0.5 text-ink-400">Difference</p>
                  <p className="font-semibold text-warn-700">{f.difference}</p>
                </div>
              )}
            </div>
          )}
          <p className="text-sm text-ink-700">{f.reason}</p>
          {f.financial_impact > 0 && (
            <div className="flex items-center gap-2 text-sm font-semibold text-danger-700">
              <Activity size={14} />
              Estimated exposure: {fmt(f.financial_impact)}
            </div>
          )}
          {f.suggested_fix && (
            <div className="rounded-lg border border-brand-100 bg-brand-50/80 px-3 py-2 text-xs text-brand-900">
              <ShieldCheck
                size={12}
                className="mr-1.5 inline text-brand-600"
              />
              <strong>Recommended fix: </strong>
              {f.suggested_fix}
            </div>
          )}
        </div>
      )}
    </div>
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
  const [filterSev, setFilterSev] = useState<"ALL"|"CRITICAL"|"WARNING"|"INFO"|"PASS">("ALL");

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

  const allFindings = useMemo(() => empData?.findings ?? [], [empData]);

  const filteredFindings = useMemo(() => {
    return allFindings.filter(f => {
      if (filterSev === "ALL") return true;
      if (filterSev === "PASS") return f.status === "PASS";
      return f.status === "FAIL" && f.severity === filterSev;
    });
  }, [allFindings, filterSev]);

  const fails   = allFindings.filter(f => f.status === "FAIL");
  const crit    = fails.filter(f => f.severity === "CRITICAL");
  const warn    = fails.filter(f => f.severity === "WARNING");
  const infos   = fails.filter(f => f.severity === "INFO");
  const passes  = allFindings.filter(f => f.status === "PASS");
  // The run's de-duplicated figure for this employee, not a raw sum that
  // would count the same rupees once per overlapping check.
  const totalImpact = employee?.financial_impact ?? null;

  const radarData = useMemo(() => {
    const layers: Record<string, number> = {};
    fails.forEach(f => {
      const layer = f.rule_id.split("-")[0];
      layers[layer] = (layers[layer] || 0) + (f.severity === "CRITICAL" ? 3 : f.severity === "WARNING" ? 2 : 1);
    });
    return Object.entries(layers).map(([subject, value]) => ({ subject, value }));
  }, [fails]);

  const risk = empData ? (RISK_META[empData.risk_level] ?? RISK_META.LOW) : RISK_META.LOW;

  if (!empData) {
    return (
      <div className="mx-auto max-w-3xl space-y-6 p-6">
        <Link
          href={backHref}
          className="inline-flex items-center gap-1 text-sm font-semibold text-brand-700 transition-colors hover:text-brand-800"
        >
          <ArrowLeft size={14} /> Back to results
        </Link>
        <div className="rounded-2xl border border-ink-200 bg-white p-12 text-center shadow-soft">
          <ShieldCheck size={48} className="mx-auto mb-4 text-ink-200" />
          <p className="text-lg font-semibold text-ink-700">
            {!employeeId
              ? "No employee ID provided."
              : loadError
                ? loadError
                : "Loading…"}
          </p>
          <p className="mt-1 text-sm text-ink-500">
            Results are read from the validation run on the server.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <Link
        href={backHref}
        className="inline-flex items-center gap-1 text-sm font-semibold text-brand-700 transition-colors hover:text-brand-800"
      >
        <ArrowLeft size={14} /> Back to results
      </Link>

      {run ? (
        <p className="text-xs text-ink-500">
          {monthLabel(run.period_month)} · run #{run.run_number} ({run.status})
          {run.upload ? ` · ${run.upload.filename ?? "register"}, upload ${run.upload.revision}` : ""}
          {sourceRow && typeof sourceRow["_source_row"] === "number" ? ` · file row ${sourceRow["_source_row"] as number}` : ""}
        </p>
      ) : null}

      <div className={`rounded-2xl border p-5 ${risk.bg}`}>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="mb-1 font-display text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-500">
              Employee
            </p>
            <h1 className="font-display text-2xl font-bold tracking-tight text-ink-900">
              {empData.employee_name || empData.employee_id}
            </h1>
            {empData.employee_name && (
              <p className="font-mono text-sm text-ink-500">
                {empData.employee_id}
              </p>
            )}
          </div>
          <div className="flex flex-col items-end gap-2">
            <div
              className={`flex items-center gap-2 rounded-xl border bg-white/70 px-4 py-2 ${risk.bg}`}
            >
              <span className={`font-display text-3xl font-black ${risk.text}`}>
                {empData.risk_score}
              </span>
              <div>
                <p className="text-xs text-ink-400">Risk score</p>
                <p className={`text-sm font-bold ${risk.text}`}>{empData.risk_level}</p>
              </div>
            </div>
            <div className="h-2 w-40 rounded-full bg-ink-200">
              <div
                className={`h-2 rounded-full ${risk.bar}`}
                style={{ width: `${empData.risk_score}%` }}
              />
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
        {[
          {
            label: "Critical",
            value: crit.length,
            color: "text-danger-600",
            bg: "bg-danger-50 border-danger-100",
          },
          {
            label: "Warning",
            value: warn.length,
            color: "text-warn-700",
            bg: "bg-warn-50 border-warn-100",
          },
          {
            label: "Info",
            value: infos.length,
            color: "text-brand-700",
            bg: "bg-brand-50 border-brand-100",
          },
          {
            label: "Passed",
            value: passes.length,
            color: "text-success-700",
            bg: "bg-success-50 border-success-100",
          },
          {
            label: "Est. impact",
            value: totalImpact == null ? "—" : inr(totalImpact),
            color: "text-warn-700",
            bg: "bg-warn-50/60 border-warn-100",
          },
        ].map((s) => (
          <div key={s.label} className={`rounded-xl border p-3 ${s.bg}`}>
            <p className="text-xs text-ink-500">{s.label}</p>
            <p className={`font-display text-xl font-bold ${s.color}`}>{s.value}</p>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        {radarData.length > 0 && (
          <div className="rounded-xl border border-ink-200 bg-white p-5 shadow-soft">
            <h3 className="mb-3 font-display text-sm font-bold uppercase tracking-[0.1em] text-ink-700">
              Issue layer breakdown
            </h3>
            <ResponsiveContainer width="100%" height={200}>
              <RadarChart data={radarData}>
                <PolarGrid stroke="rgba(148,163,184,0.25)" />
                <PolarAngleAxis dataKey="subject" tick={{ fontSize: 11, fill: "#94a3b8" }} />
                <Radar
                  name="Issues"
                  dataKey="value"
                  stroke="#6366f1"
                  fill="#6366f1"
                  fillOpacity={0.3}
                />
                <Tooltip
                  contentStyle={{
                    background: "var(--surface-elevated, #fff)",
                    border: "1px solid rgba(148,163,184,0.25)",
                    borderRadius: 12,
                    color: "var(--text-primary, #0f172a)",
                  }}
                />
              </RadarChart>
            </ResponsiveContainer>
          </div>
        )}

        <div className="rounded-xl border border-ink-200 bg-white p-5 shadow-soft">
          <h3 className="mb-3 font-display text-sm font-bold uppercase tracking-[0.1em] text-ink-700">
            Statutory snapshot
          </h3>
          <div className="space-y-2 text-sm">
            {[
              ["PF wage", fmt(empData.pf_wage)],
              ["PF employee", fmt(empData.pf_amount_employee)],
              ["PF employer", fmt(empData.pf_amount_employer)],
              ["ESIC eligible", empData.esic_eligible ? "Yes" : "Exempt"],
              ["ESIC (emp)", empData.esic_eligible ? fmt(empData.esic_employee) : "–"],
              ["ESIC (er)", empData.esic_eligible ? fmt(empData.esic_employer) : "–"],
              ["PT", empData.pt_due > 0 ? fmt(empData.pt_due) : "Nil"],
              ["PT state", empData.pt_applicable_state || "–"],
              ["LWF (emp)", empData.lwf_employee > 0 ? fmt(empData.lwf_employee) : "Nil"],
              ["LWF (er)", empData.lwf_employer > 0 ? fmt(empData.lwf_employer) : "Nil"],
              ["Paid days", empData.paid_days != null ? String(empData.paid_days) : "–"],
              ["LOP days", empData.lop_days != null ? String(empData.lop_days) : "–"],
            ].map(([k, v]) => (
              <div
                key={k}
                className="flex justify-between border-b border-ink-100 pb-1"
              >
                <span className="text-ink-500">{k}</span>
                <span className="font-medium text-ink-800">{v}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <CoverageList coverage={empData.coverage} />

      <div>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <h2 className="font-display text-base font-bold tracking-tight text-ink-900">
            All findings ({filteredFindings.length})
          </h2>
          <div className="flex flex-wrap gap-1">
            {(["ALL", "CRITICAL", "WARNING", "INFO", "PASS"] as const).map((s) => {
              const active = filterSev === s;
              const activeColor =
                s === "CRITICAL"
                  ? "bg-danger-600 text-white"
                  : s === "WARNING"
                  ? "bg-warn-500 text-white"
                  : s === "INFO"
                  ? "bg-brand-600 text-white"
                  : s === "PASS"
                  ? "bg-success-600 text-white"
                  : "bg-brand-600 text-white";
              return (
                <button
                  key={s}
                  onClick={() => setFilterSev(s)}
                  className={`rounded-lg px-3 py-1 text-xs font-semibold transition-colors ${
                    active
                      ? activeColor
                      : "bg-ink-100 text-ink-600 hover:bg-ink-200"
                  }`}
                >
                  {s}{" "}
                  {s === "ALL"
                    ? ""
                    : s === "CRITICAL"
                    ? crit.length
                    : s === "WARNING"
                    ? warn.length
                    : s === "INFO"
                    ? infos.length
                    : passes.length}
                </button>
              );
            })}
          </div>
        </div>

        <div className="space-y-3">
          {filteredFindings.map((f, i) => (
            <FindingCard key={i} f={f} />
          ))}
          {filteredFindings.length === 0 && (
            <div className="rounded-2xl border border-dashed border-ink-200 bg-ink-50/40 py-12 text-center">
              <CheckCircle2
                size={40}
                className="mx-auto mb-3 text-success-300"
              />
              <p className="text-ink-500">No findings in this category.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

const OUTCOME_ORDER: Outcome[] = ["failed", "cannot_validate", "passed", "not_applicable", "disabled"];
const OUTCOME_CHIP: Record<Outcome, string> = {
  passed: "bg-success-100 text-success-800",
  failed: "bg-danger-100 text-danger-800",
  cannot_validate: "bg-warn-100 text-warn-800",
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
    <div className="rounded-xl border border-ink-200 bg-white p-5 shadow-soft">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-display text-base font-bold tracking-tight text-ink-900">
          Checks for this employee ({entries.length})
        </h2>
        <div className="flex flex-wrap gap-1">
          {OUTCOME_ORDER.map((o) => (
            <button key={o} type="button" onClick={() => setShow(o)} aria-pressed={show === o}
              className={`rounded-lg px-3 py-1 text-xs font-semibold ${show === o ? OUTCOME_CHIP[o] + " ring-1 ring-current" : "bg-ink-50 text-ink-600 hover:bg-ink-100"}`}>
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
    <Suspense fallback={<div className="mx-auto max-w-5xl p-6 text-sm text-ink-500">Loading…</div>}>
      <EmployeeDrilldown />
    </Suspense>
  );
}
