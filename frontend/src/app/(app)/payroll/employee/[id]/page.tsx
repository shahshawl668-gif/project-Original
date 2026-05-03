"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
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
  risk_score: number;
  risk_level: "LOW" | "MEDIUM" | "HIGH";
  score_breakdown: Record<string, number>;
};

// ─── Helpers ──────────────────────────────────────────────────────────────────

const fmt = (n: number | null | undefined, digits = 2) =>
  n == null ? "–" : `₹${n.toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;

const SEV_STYLES: Record<string, { card: string; badge: string; icon: React.ReactNode }> = {
  CRITICAL: {
    card: "bg-danger-50/80 border-danger-200/80 dark:bg-danger-500/[0.08] dark:border-danger-500/30",
    badge:
      "bg-danger-100 text-danger-800 border border-danger-200 dark:bg-danger-500/15 dark:text-danger-200 dark:border-danger-500/30",
    icon: <XCircle size={16} className="mt-0.5 shrink-0 text-danger-600 dark:text-danger-400" />,
  },
  WARNING: {
    card: "bg-warn-50/80 border-warn-200/80 dark:bg-warn-500/[0.08] dark:border-warn-500/30",
    badge:
      "bg-warn-100 text-warn-800 border border-warn-200 dark:bg-warn-500/15 dark:text-warn-200 dark:border-warn-500/30",
    icon: <AlertTriangle size={16} className="mt-0.5 shrink-0 text-warn-600 dark:text-warn-400" />,
  },
  INFO: {
    card: "bg-brand-50/70 border-brand-100 dark:bg-brand-500/[0.08] dark:border-brand-500/30",
    badge:
      "bg-brand-100 text-brand-800 border border-brand-100 dark:bg-brand-500/15 dark:text-brand-200 dark:border-brand-500/30",
    icon: <Info size={16} className="mt-0.5 shrink-0 text-brand-500 dark:text-brand-400" />,
  },
  PASS: {
    card: "bg-success-50/80 border-success-100 dark:bg-success-500/[0.08] dark:border-success-500/30",
    badge:
      "bg-success-100 text-success-800 border border-success-100 dark:bg-success-500/15 dark:text-success-200 dark:border-success-500/30",
    icon: <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-success-600 dark:text-success-400" />,
  },
};

const RISK_META: Record<string, { bar: string; bg: string; text: string }> = {
  HIGH: {
    bar: "bg-danger-500",
    bg: "bg-danger-50/80 border-danger-200/80 dark:bg-danger-500/[0.08] dark:border-danger-500/30",
    text: "text-danger-700 dark:text-danger-300",
  },
  MEDIUM: {
    bar: "bg-warn-500",
    bg: "bg-warn-50/80 border-warn-200/80 dark:bg-warn-500/[0.08] dark:border-warn-500/30",
    text: "text-warn-700 dark:text-warn-300",
  },
  LOW: {
    bar: "bg-success-500",
    bg: "bg-success-50/80 border-success-200 dark:bg-success-500/[0.08] dark:border-success-500/30",
    text: "text-success-700 dark:text-success-300",
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
            <span className="text-sm font-semibold text-ink-800 dark:text-ink-100">
              {f.rule_name}
            </span>
            <span className="text-xs text-ink-400 dark:text-ink-500">· {f.component}</span>
          </div>
          <p className="line-clamp-1 text-sm text-ink-600 dark:text-ink-300">{f.reason}</p>
        </div>
        <div className="ml-2 shrink-0 text-ink-400 dark:text-ink-500">
          {open ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </div>
      </button>
      {open && (
        <div className="space-y-3 border-t border-black/5 px-4 pb-4 pt-3 dark:border-white/10">
          {(f.expected_value || f.actual_value) && (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              {f.expected_value && (
                <div className="rounded-lg bg-white/70 p-3 text-xs dark:bg-white/[0.04]">
                  <p className="mb-0.5 text-ink-400 dark:text-ink-500">Expected</p>
                  <p className="font-semibold text-ink-800 dark:text-ink-100">
                    {f.expected_value}
                  </p>
                </div>
              )}
              {f.actual_value && (
                <div className="rounded-lg bg-white/70 p-3 text-xs dark:bg-white/[0.04]">
                  <p className="mb-0.5 text-ink-400 dark:text-ink-500">Actual</p>
                  <p className="font-semibold text-ink-800 dark:text-ink-100">{f.actual_value}</p>
                </div>
              )}
              {f.difference && f.difference !== "0.00" && (
                <div className="rounded-lg bg-white/70 p-3 text-xs dark:bg-white/[0.04]">
                  <p className="mb-0.5 text-ink-400 dark:text-ink-500">Difference</p>
                  <p className="font-semibold text-warn-700 dark:text-warn-300">{f.difference}</p>
                </div>
              )}
            </div>
          )}
          <p className="text-sm text-ink-700 dark:text-ink-200">{f.reason}</p>
          {f.financial_impact > 0 && (
            <div className="flex items-center gap-2 text-sm font-semibold text-danger-700 dark:text-danger-300">
              <Activity size={14} />
              Estimated exposure: {fmt(f.financial_impact)}
            </div>
          )}
          {f.suggested_fix && (
            <div className="rounded-lg border border-brand-100 bg-brand-50/80 px-3 py-2 text-xs text-brand-900 dark:border-brand-500/30 dark:bg-brand-500/[0.08] dark:text-brand-100">
              <ShieldCheck
                size={12}
                className="mr-1.5 inline text-brand-600 dark:text-brand-300"
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

export default function EmployeeDrilldownPage() {
  const params = useParams();
  const rawId = params?.id as string | undefined;
  const employeeId = rawId ? decodeURIComponent(rawId) : "";

  const [empData, setEmpData] = useState<ResultRow | null>(null);
  const [filterSev, setFilterSev] = useState<"ALL"|"CRITICAL"|"WARNING"|"INFO"|"PASS">("ALL");

  useEffect(() => {
    try {
      const raw = sessionStorage.getItem("payroll_results");
      if (!raw) return;
      const rows: ResultRow[] = JSON.parse(raw);
      const found = rows.find(r => String(r.employee_id).trim() === String(employeeId).trim());
      if (found) setEmpData(found);
    } catch { /* ignore */ }
  }, [employeeId]);

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
  const totalImpact = fails.reduce((s, f) => s + (f.financial_impact || 0), 0);

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
          href="/payroll/results"
          className="inline-flex items-center gap-1 text-sm font-semibold text-brand-700 transition-colors hover:text-brand-800 dark:text-brand-300 dark:hover:text-brand-200"
        >
          <ArrowLeft size={14} /> Back to results
        </Link>
        <div className="rounded-2xl border border-ink-200 bg-white p-12 text-center shadow-soft dark:border-white/[0.07] dark:bg-ink-900/70">
          <ShieldCheck size={48} className="mx-auto mb-4 text-ink-200 dark:text-ink-600" />
          <p className="text-lg font-semibold text-ink-700 dark:text-ink-200">
            {employeeId
              ? `Employee "${employeeId}" not found in session.`
              : "No employee ID provided."}
          </p>
          <p className="mt-1 text-sm text-ink-500 dark:text-ink-400">
            Run a validation first, then open this page.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <Link
        href="/payroll/results"
        className="inline-flex items-center gap-1 text-sm font-semibold text-brand-700 transition-colors hover:text-brand-800 dark:text-brand-300 dark:hover:text-brand-200"
      >
        <ArrowLeft size={14} /> Back to results
      </Link>

      <div className={`rounded-2xl border p-5 ${risk.bg}`}>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="mb-1 font-display text-[11px] font-bold uppercase tracking-[0.14em] text-ink-500 dark:text-ink-400">
              Employee
            </p>
            <h1 className="font-display text-2xl font-bold tracking-tight text-ink-900 dark:text-white">
              {empData.employee_name || empData.employee_id}
            </h1>
            {empData.employee_name && (
              <p className="font-mono text-sm text-ink-500 dark:text-ink-400">
                {empData.employee_id}
              </p>
            )}
          </div>
          <div className="flex flex-col items-end gap-2">
            <div
              className={`flex items-center gap-2 rounded-xl border bg-white/70 px-4 py-2 dark:bg-white/[0.04] ${risk.bg}`}
            >
              <span className={`font-display text-3xl font-black ${risk.text}`}>
                {empData.risk_score}
              </span>
              <div>
                <p className="text-xs text-ink-400 dark:text-ink-500">Risk score</p>
                <p className={`text-sm font-bold ${risk.text}`}>{empData.risk_level}</p>
              </div>
            </div>
            <div className="h-2 w-40 rounded-full bg-ink-200 dark:bg-white/10">
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
            color: "text-danger-600 dark:text-danger-300",
            bg: "bg-danger-50 border-danger-100 dark:bg-danger-500/[0.08] dark:border-danger-500/30",
          },
          {
            label: "Warning",
            value: warn.length,
            color: "text-warn-700 dark:text-warn-300",
            bg: "bg-warn-50 border-warn-100 dark:bg-warn-500/[0.08] dark:border-warn-500/30",
          },
          {
            label: "Info",
            value: infos.length,
            color: "text-brand-700 dark:text-brand-300",
            bg: "bg-brand-50 border-brand-100 dark:bg-brand-500/[0.08] dark:border-brand-500/30",
          },
          {
            label: "Passed",
            value: passes.length,
            color: "text-success-700 dark:text-success-300",
            bg: "bg-success-50 border-success-100 dark:bg-success-500/[0.08] dark:border-success-500/30",
          },
          {
            label: "Est. impact",
            value: `₹${Math.round(totalImpact).toLocaleString("en-IN")}`,
            color: "text-warn-700 dark:text-warn-300",
            bg: "bg-warn-50/60 border-warn-100 dark:bg-warn-500/[0.06] dark:border-warn-500/30",
          },
        ].map((s) => (
          <div key={s.label} className={`rounded-xl border p-3 ${s.bg}`}>
            <p className="text-xs text-ink-500 dark:text-ink-400">{s.label}</p>
            <p className={`font-display text-xl font-bold ${s.color}`}>{s.value}</p>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        {radarData.length > 0 && (
          <div className="rounded-xl border border-ink-200 bg-white p-5 shadow-soft dark:border-white/[0.07] dark:bg-ink-900/70">
            <h3 className="mb-3 font-display text-sm font-bold uppercase tracking-[0.1em] text-ink-700 dark:text-ink-200">
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

        <div className="rounded-xl border border-ink-200 bg-white p-5 shadow-soft dark:border-white/[0.07] dark:bg-ink-900/70">
          <h3 className="mb-3 font-display text-sm font-bold uppercase tracking-[0.1em] text-ink-700 dark:text-ink-200">
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
                className="flex justify-between border-b border-ink-100 pb-1 dark:border-white/[0.05]"
              >
                <span className="text-ink-500 dark:text-ink-400">{k}</span>
                <span className="font-medium text-ink-800 dark:text-ink-100">{v}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <h2 className="font-display text-base font-bold tracking-tight text-ink-900 dark:text-white">
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
                      : "bg-ink-100 text-ink-600 hover:bg-ink-200 dark:bg-white/[0.06] dark:text-ink-300 dark:hover:bg-white/[0.10]"
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
            <div className="rounded-2xl border border-dashed border-ink-200 bg-ink-50/40 py-12 text-center dark:border-white/[0.07] dark:bg-white/[0.02]">
              <CheckCircle2
                size={40}
                className="mx-auto mb-3 text-success-300 dark:text-success-500"
              />
              <p className="text-ink-500 dark:text-ink-400">No findings in this category.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
