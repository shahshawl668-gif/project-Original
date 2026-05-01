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
    card:  "bg-red-50 border-red-200",
    badge: "bg-red-100 text-red-800 border border-red-200",
    icon:  <XCircle size={16} className="text-red-600 shrink-0 mt-0.5"/>,
  },
  WARNING: {
    card:  "bg-yellow-50 border-yellow-200",
    badge: "bg-yellow-100 text-yellow-800 border border-yellow-200",
    icon:  <AlertTriangle size={16} className="text-yellow-600 shrink-0 mt-0.5"/>,
  },
  INFO: {
    card:  "bg-blue-50 border-blue-100",
    badge: "bg-blue-100 text-blue-800 border border-blue-100",
    icon:  <Info size={16} className="text-blue-500 shrink-0 mt-0.5"/>,
  },
  PASS: {
    card:  "bg-green-50 border-green-100",
    badge: "bg-green-100 text-green-800 border border-green-100",
    icon:  <CheckCircle2 size={16} className="text-green-600 shrink-0 mt-0.5"/>,
  },
};

const RISK_META: Record<string, { bar: string; bg: string; text: string }> = {
  HIGH:   { bar: "bg-red-500",    bg: "bg-red-50 border-red-200",    text: "text-red-700" },
  MEDIUM: { bar: "bg-yellow-500", bg: "bg-yellow-50 border-yellow-200", text: "text-yellow-700" },
  LOW:    { bar: "bg-green-500",  bg: "bg-green-50 border-green-200", text: "text-green-700" },
};

function FindingCard({ f }: { f: Finding }) {
  const [open, setOpen] = useState(true);
  const s = f.status === "PASS" ? SEV_STYLES.PASS : SEV_STYLES[f.severity] ?? SEV_STYLES.INFO;
  return (
    <div className={`rounded-xl border ${s.card} overflow-hidden`}>
      <button
        className="w-full flex items-start gap-3 p-4 text-left"
        onClick={() => setOpen(o => !o)}
      >
        {s.icon}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-0.5">
            <span className={`text-xs font-mono font-semibold px-1.5 py-0.5 rounded ${s.badge}`}>{f.rule_id}</span>
            <span className={`text-xs font-semibold px-1.5 py-0.5 rounded ${s.badge}`}>
              {f.status === "PASS" ? "PASS" : f.severity}
            </span>
            <span className="text-sm font-semibold text-slate-800">{f.rule_name}</span>
            <span className="text-xs text-slate-400">· {f.component}</span>
          </div>
          <p className="text-sm text-slate-600 line-clamp-1">{f.reason}</p>
        </div>
        <div className="shrink-0 ml-2 text-slate-400">
          {open ? <ChevronUp size={16}/> : <ChevronDown size={16}/>}
        </div>
      </button>
      {open && (
        <div className="px-4 pb-4 border-t border-black/5 pt-3 space-y-2">
          {/* Expected / Actual */}
          {(f.expected_value || f.actual_value) && (
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
              {f.expected_value && (
                <div className="bg-white/70 rounded-lg p-3 text-xs">
                  <p className="text-slate-400 mb-0.5">Expected</p>
                  <p className="font-semibold text-slate-800">{f.expected_value}</p>
                </div>
              )}
              {f.actual_value && (
                <div className="bg-white/70 rounded-lg p-3 text-xs">
                  <p className="text-slate-400 mb-0.5">Actual</p>
                  <p className="font-semibold text-slate-800">{f.actual_value}</p>
                </div>
              )}
              {f.difference && f.difference !== "0.00" && (
                <div className="bg-white/70 rounded-lg p-3 text-xs">
                  <p className="text-slate-400 mb-0.5">Difference</p>
                  <p className="font-semibold text-orange-700">{f.difference}</p>
                </div>
              )}
            </div>
          )}
          {/* Reason */}
          <p className="text-sm text-slate-700">{f.reason}</p>
          {/* Financial impact */}
          {f.financial_impact > 0 && (
            <div className="flex items-center gap-2 text-sm font-semibold text-red-700">
              <Activity size={14}/>
              Estimated exposure: {fmt(f.financial_impact)}
            </div>
          )}
          {/* Fix */}
          {f.suggested_fix && (
            <div className="bg-indigo-50 border border-indigo-100 rounded-lg px-3 py-2 text-xs text-indigo-900">
              <ShieldCheck size={12} className="inline mr-1.5 text-indigo-600"/>
              <strong>Recommended fix: </strong>{f.suggested_fix}
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
      <div className="p-6 max-w-3xl mx-auto">
        <Link href="/payroll/results" className="inline-flex items-center gap-1 text-sm text-indigo-600 hover:text-indigo-800 mb-6">
          <ArrowLeft size={14}/> Back to Results
        </Link>
        <div className="text-center py-20 text-slate-400">
          <ShieldCheck size={48} className="mx-auto mb-4 text-slate-200"/>
          <p className="text-lg font-medium text-slate-500">
            {employeeId ? `Employee "${employeeId}" not found in session.` : "No employee ID provided."}
          </p>
          <p className="text-sm mt-1">Run a validation first, then open this page.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      {/* Back */}
      <Link href="/payroll/results" className="inline-flex items-center gap-1 text-sm text-indigo-600 hover:text-indigo-800">
        <ArrowLeft size={14}/> Back to Results
      </Link>

      {/* Header */}
      <div className={`rounded-2xl border p-5 ${risk.bg}`}>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs text-slate-500 font-medium uppercase tracking-wide mb-1">Employee</p>
            <h1 className="text-2xl font-bold text-slate-800">
              {empData.employee_name || empData.employee_id}
            </h1>
            {empData.employee_name && (
              <p className="text-sm text-slate-500 font-mono">{empData.employee_id}</p>
            )}
          </div>
          <div className="flex flex-col items-end gap-2">
            <div className={`flex items-center gap-2 px-4 py-2 rounded-xl border ${risk.bg}`}>
              <span className={`text-3xl font-black ${risk.text}`}>{empData.risk_score}</span>
              <div>
                <p className="text-xs text-slate-400">Risk Score</p>
                <p className={`text-sm font-bold ${risk.text}`}>{empData.risk_level}</p>
              </div>
            </div>
            <div className="w-40 bg-slate-200 rounded-full h-2">
              <div className={`h-2 rounded-full ${risk.bar}`} style={{width:`${empData.risk_score}%`}}/>
            </div>
          </div>
        </div>
      </div>

      {/* Stat row */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
        {[
          { label: "Critical", value: crit.length, color: "text-red-600",    bg: "bg-red-50 border-red-100" },
          { label: "Warning",  value: warn.length, color: "text-yellow-600", bg: "bg-yellow-50 border-yellow-100" },
          { label: "Info",     value: infos.length, color: "text-blue-600",  bg: "bg-blue-50 border-blue-100" },
          { label: "Passed",   value: passes.length, color: "text-green-600", bg: "bg-green-50 border-green-100" },
          {
            label: "Est. Impact",
            value: `₹${Math.round(totalImpact).toLocaleString("en-IN")}`,
            color: "text-orange-600", bg: "bg-orange-50 border-orange-100",
          },
        ].map(s => (
          <div key={s.label} className={`rounded-xl border p-3 ${s.bg}`}>
            <p className="text-xs text-slate-400">{s.label}</p>
            <p className={`text-xl font-bold ${s.color}`}>{s.value}</p>
          </div>
        ))}
      </div>

      {/* Body: radar + statutory summary */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Radar */}
        {radarData.length > 0 && (
          <div className="bg-white rounded-xl border border-slate-200 p-5">
            <h3 className="text-sm font-semibold text-slate-700 mb-3">Issue Layer Breakdown</h3>
            <ResponsiveContainer width="100%" height={200}>
              <RadarChart data={radarData}>
                <PolarGrid/>
                <PolarAngleAxis dataKey="subject" tick={{fontSize:11}}/>
                <Radar name="Issues" dataKey="value" stroke="#6366f1" fill="#6366f1" fillOpacity={0.3}/>
                <Tooltip/>
              </RadarChart>
            </ResponsiveContainer>
          </div>
        )}

        {/* Statutory snapshot */}
        <div className="bg-white rounded-xl border border-slate-200 p-5">
          <h3 className="text-sm font-semibold text-slate-700 mb-3">Statutory Snapshot</h3>
          <div className="space-y-2 text-sm">
            {[
              ["PF Wage",      fmt(empData.pf_wage)],
              ["PF Employee",  fmt(empData.pf_amount_employee)],
              ["PF Employer",  fmt(empData.pf_amount_employer)],
              ["ESIC Eligible",empData.esic_eligible ? "Yes" : "Exempt"],
              ["ESIC (Emp)",   empData.esic_eligible ? fmt(empData.esic_employee) : "–"],
              ["ESIC (Er)",    empData.esic_eligible ? fmt(empData.esic_employer) : "–"],
              ["PT",           empData.pt_due > 0 ? fmt(empData.pt_due) : "Nil"],
              ["PT State",     empData.pt_applicable_state || "–"],
              ["LWF (Emp)",    empData.lwf_employee > 0 ? fmt(empData.lwf_employee) : "Nil"],
              ["LWF (Er)",     empData.lwf_employer > 0 ? fmt(empData.lwf_employer) : "Nil"],
              ["Paid Days",    empData.paid_days != null ? String(empData.paid_days) : "–"],
              ["LOP Days",     empData.lop_days != null ? String(empData.lop_days) : "–"],
            ].map(([k, v]) => (
              <div key={k} className="flex justify-between border-b border-slate-50 pb-1">
                <span className="text-slate-500">{k}</span>
                <span className="font-medium text-slate-800">{v}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Findings */}
      <div>
        <div className="flex items-center justify-between flex-wrap gap-3 mb-3">
          <h2 className="text-base font-semibold text-slate-800">
            All Findings ({filteredFindings.length})
          </h2>
          <div className="flex gap-1 flex-wrap">
            {(["ALL","CRITICAL","WARNING","INFO","PASS"] as const).map(s => (
              <button key={s}
                onClick={() => setFilterSev(s)}
                className={`px-3 py-1 text-xs rounded-lg font-medium transition-colors
                  ${filterSev === s
                    ? s==="CRITICAL"?"bg-red-600 text-white"
                    : s==="WARNING"?"bg-yellow-500 text-white"
                    : s==="INFO"?"bg-blue-600 text-white"
                    : s==="PASS"?"bg-green-600 text-white"
                    : "bg-indigo-600 text-white"
                    : "bg-slate-100 text-slate-600 hover:bg-slate-200"}`}
              >
                {s} {s==="ALL"?"":s==="CRITICAL"?crit.length:s==="WARNING"?warn.length:s==="INFO"?infos.length:passes.length}
              </button>
            ))}
          </div>
        </div>

        <div className="space-y-3">
          {filteredFindings.map((f, i) => <FindingCard key={i} f={f}/>)}
          {filteredFindings.length === 0 && (
            <div className="text-center py-12 text-slate-400">
              <CheckCircle2 size={40} className="mx-auto mb-3 text-green-300"/>
              <p className="text-slate-500">No findings in this category.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
