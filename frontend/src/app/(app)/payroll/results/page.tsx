"use client";

import { apiBlob } from "@/lib/api";
import { PageHeader } from "@/components/layout/PageHeader";
import { EmptyState } from "@/components/ui/empty-state";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import Link from "next/link";
import { Suspense, useEffect, useMemo, useState, type ReactNode } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  BarChart, Bar, PieChart, Pie, Cell, XAxis, YAxis,
  Tooltip, ResponsiveContainer, Legend,
} from "recharts";
import {
  AlertTriangle, CheckCircle2,
  Users, XCircle, Search,
  ArrowRight, Shield, Flame, Activity, UploadCloud,
  TrendingUp, Download,
} from "lucide-react";
import { toast } from "sonner";

// ─── Types ────────────────────────────────────────────────────────────────────

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
  lwf_employee: number;
  lwf_employer: number;
  paid_days: number | null;
  lop_days: number | null;
  days_in_month: number;
  lop_check: { checked: boolean; diffs: { component: string; expected: number; actual: number; diff: number }[] };
  increment_arrear: { applicable: boolean; expected_total: number; actual_total: number; months: number };
  prior_month: { is_joiner: boolean; is_continuing: boolean; changed_components: Record<string, unknown> };
  errors: string[];
  tds_risk_flags: string[];
  findings: Finding[];
  risk_score: number;
  risk_level: "LOW" | "MEDIUM" | "HIGH";
  score_breakdown: Record<string, number>;
};

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

type FindingsSummary = {
  total_findings: number;
  critical: number;
  warning: number;
  info: number;
  pass: number;
  total_financial_impact: number;
  risk_distribution?: { LOW: number; MEDIUM: number; HIGH: number };
  rules_triggered: { rule_id: string; rule_name: string; severity: string; fail_count: number }[];
};

type RiskScore = {
  employee_id: string;
  employee_name: string;
  risk_score: number;
  risk_level: "LOW" | "MEDIUM" | "HIGH";
  score_breakdown: Record<string, number>;
};

type Tab = "overview" | "risk" | "findings" | "pf" | "esic" | "ptlwf" | "lop";

// ─── Helpers ──────────────────────────────────────────────────────────────────

const fmt = (n: number | null | undefined, digits = 2) =>
  n == null ? "–" : `₹${n.toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;

const SEV_COLOR: Record<string, string> = {
  CRITICAL:
    "bg-danger-50 text-danger-700 border border-danger-200 dark:bg-danger-500/10 dark:text-danger-300 dark:border-danger-500/30",
  WARNING:
    "bg-warning-50 text-warning-800 border border-warning-200 dark:bg-warning-500/10 dark:text-warning-300 dark:border-warning-500/30",
  INFO: "bg-sky-50 text-sky-700 border border-sky-200 dark:bg-sky-500/10 dark:text-sky-300 dark:border-sky-500/30",
  PASS: "bg-success-50 text-success-700 border border-success-200 dark:bg-success-500/10 dark:text-success-300 dark:border-success-500/30",
};

const RISK_COLOR: Record<string, { bg: string; text: string; dot: string }> = {
  HIGH: {
    bg: "bg-danger-50 border-danger-200 dark:bg-danger-500/10 dark:border-danger-500/30",
    text: "text-danger-700 dark:text-danger-300",
    dot: "bg-danger-500",
  },
  MEDIUM: {
    bg: "bg-warning-50 border-warning-200 dark:bg-warning-500/10 dark:border-warning-500/30",
    text: "text-warning-700 dark:text-warning-300",
    dot: "bg-warning-500",
  },
  LOW: {
    bg: "bg-success-50 border-success-200 dark:bg-success-500/10 dark:border-success-500/30",
    text: "text-success-700 dark:text-success-300",
    dot: "bg-success-500",
  },
};

const PIE_COLORS = ["#ef4444", "#f59e0b", "#22c55e"];

function StatCard({ label, value, sub, icon, color = "brand" }: {
  label: string; value: string | number; sub?: string;
  icon?: ReactNode; color?: string;
}) {
  const bg: Record<string, string> = {
    red: "bg-gradient-to-br from-danger-50 to-white border-danger-100 ring-danger-900/[0.03] dark:from-danger-500/10 dark:to-ink-900/40 dark:border-danger-500/20 dark:ring-white/[0.04]",
    yellow:
      "bg-gradient-to-br from-warning-50 to-white border-warning-100 ring-warning-900/[0.03] dark:from-warning-500/10 dark:to-ink-900/40 dark:border-warning-500/20 dark:ring-white/[0.04]",
    green:
      "bg-gradient-to-br from-success-50 to-white border-success-100 ring-success-900/[0.03] dark:from-success-500/10 dark:to-ink-900/40 dark:border-success-500/20 dark:ring-white/[0.04]",
    brand:
      "bg-gradient-to-br from-brand-50 to-white border-brand-100 ring-brand-900/[0.03] dark:from-brand-500/10 dark:to-ink-900/40 dark:border-brand-500/20 dark:ring-white/[0.04]",
    blue: "bg-gradient-to-br from-sky-50 to-white border-sky-100 ring-sky-900/[0.03] dark:from-sky-500/10 dark:to-ink-900/40 dark:border-sky-500/20 dark:ring-white/[0.04]",
  };
  const txt: Record<string, string> = {
    red: "text-danger-600 dark:text-danger-300",
    yellow: "text-warning-600 dark:text-warning-300",
    green: "text-success-600 dark:text-success-300",
    brand: "text-brand-600 dark:text-brand-300",
    blue: "text-sky-600 dark:text-sky-300",
  };
  return (
    <div
      className={`lift flex items-center gap-4 rounded-2xl border p-4 shadow-soft ring-1 ${bg[color] || bg.brand}`}
    >
      {icon && <div className={`text-2xl ${txt[color] || txt.brand}`}>{icon}</div>}
      <div className="min-w-0">
        <p className="text-2xs font-semibold uppercase tracking-widest text-ink-500 dark:text-ink-400">
          {label}
        </p>
        <p
          className={`num truncate text-2xl font-bold tracking-tight ${txt[color] || txt.brand}`}
        >
          {value}
        </p>
        {sub && (
          <p className="mt-0.5 text-2xs font-medium text-ink-500 dark:text-ink-400">{sub}</p>
        )}
      </div>
    </div>
  );
}

function RiskBadge({ level }: { level: "LOW" | "MEDIUM" | "HIGH" }) {
  const c = RISK_COLOR[level] || RISK_COLOR.LOW;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-semibold ${c.bg} ${c.text}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${c.dot}`} />
      {level}
    </span>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

function PayrollResultsContent() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [results, setResults] = useState<ResultRow[]>([]);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [summary, setSummary] = useState<FindingsSummary | null>(null);
  const [riskScores, setRiskScores] = useState<RiskScore[]>([]);
  const [tab, setTab] = useState<Tab>("overview");
  const [ready, setReady] = useState(false);

  // Findings filters
  const [fSev, setFSev] = useState<"ALL" | "CRITICAL" | "WARNING" | "INFO">("ALL");
  const [fStatus, setFStatus] = useState<"ALL" | "FAIL" | "PASS">("FAIL");
  const [fSearch, setFSearch] = useState("");

  // Risk filters
  const [rLevel, setRLevel] = useState<"ALL" | "HIGH" | "MEDIUM" | "LOW">("ALL");
  const [rSearch, setRSearch] = useState("");
  const [exportBusy, setExportBusy] = useState(false);

  useEffect(() => {
    try {
      const r = sessionStorage.getItem("payroll_results");
      const f = sessionStorage.getItem("payroll_findings");
      const s = sessionStorage.getItem("payroll_findings_summary");
      const rs = sessionStorage.getItem("payroll_risk_scores");
      if (r) setResults(JSON.parse(r));
      if (f) setFindings(JSON.parse(f));
      if (s) setSummary(JSON.parse(s));
      if (rs) setRiskScores(JSON.parse(rs));
    } catch {
      /* ignore */
    }
    setReady(true);
  }, []);

  useEffect(() => {
    const t = searchParams.get("tab");
    const valid: Tab[] = ["overview", "risk", "findings", "pf", "esic", "ptlwf", "lop"];
    if (t && valid.includes(t as Tab)) setTab(t as Tab);
  }, [searchParams]);

  // Filtered findings
  const filteredFindings = useMemo(() => {
    return findings.filter(f => {
      if (fSev !== "ALL" && f.severity !== fSev) return false;
      if (fStatus !== "ALL" && f.status !== fStatus) return false;
      if (fSearch) {
        const q = fSearch.toLowerCase();
        return (
          f.employee_id.toLowerCase().includes(q) ||
          (f.employee_name || "").toLowerCase().includes(q) ||
          f.rule_id.toLowerCase().includes(q) ||
          f.rule_name.toLowerCase().includes(q) ||
          f.component.toLowerCase().includes(q)
        );
      }
      return true;
    });
  }, [findings, fSev, fStatus, fSearch]);

  // Filtered risk
  const filteredRisk = useMemo(() => {
    return riskScores
      .filter(r => {
        if (rLevel !== "ALL" && r.risk_level !== rLevel) return false;
        if (rSearch) {
          const q = rSearch.toLowerCase();
          return r.employee_id.toLowerCase().includes(q) ||
            (r.employee_name || "").toLowerCase().includes(q);
        }
        return true;
      })
      .sort((a, b) => b.risk_score - a.risk_score);
  }, [riskScores, rLevel, rSearch]);

  const failFindings = findings.filter(f => f.status === "FAIL");
  const critCount = failFindings.filter(f => f.severity === "CRITICAL").length;

  const riskDist = useMemo(() => {
    const d = { HIGH: 0, MEDIUM: 0, LOW: 0 };
    riskScores.forEach(r => { d[r.risk_level] = (d[r.risk_level] || 0) + 1; });
    return [
      { name: "HIGH", value: d.HIGH },
      { name: "MEDIUM", value: d.MEDIUM },
      { name: "LOW", value: d.LOW },
    ];
  }, [riskScores]);

  const ruleTriggerData = useMemo(() => {
    return (summary?.rules_triggered || [])
      .slice(0, 10)
      .map(r => ({ name: r.rule_id, count: r.fail_count, severity: r.severity }));
  }, [summary]);

  const downloadExcelAudit = async () => {
    const raw = typeof window !== "undefined" ? sessionStorage.getItem("payroll_validate_request") : null;
    if (!raw) {
      toast.error("Audit export unavailable", {
        description: "Run validation again from Upload — we need the same payload for the Excel workbook.",
      });
      return;
    }
    let body: unknown;
    try {
      body = JSON.parse(raw);
    } catch {
      toast.error("Could not read validation session");
      return;
    }
    setExportBusy(true);
    try {
      const blob = await apiBlob("/api/payroll/validate/export-excel", {
        method: "POST",
        body: JSON.stringify(body),
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `payroll-audit-${new Date().toISOString().slice(0, 10)}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success("Audit workbook downloaded");
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Export failed";
      toast.error("Excel export failed", { description: msg });
    } finally {
      setExportBusy(false);
    }
  };

  const tabs: { id: Tab; label: string; badge?: number; badgeColor?: string }[] = [
    { id: "overview", label: "Overview" },
    { id: "risk",     label: "Risk Scores",  badge: riskScores.filter(r => r.risk_level === "HIGH").length, badgeColor: "red" },
    { id: "findings", label: "Findings",     badge: failFindings.length, badgeColor: critCount > 0 ? "red" : "yellow" },
    { id: "pf",    label: "PF" },
    { id: "esic",  label: "ESIC" },
    { id: "ptlwf", label: "PT / LWF" },
    { id: "lop",   label: "LOP / Arrear" },
  ];

  const commitTab = (id: Tab) => {
    setTab(id);
    const p = new URLSearchParams(searchParams.toString());
    p.set("tab", id);
    router.replace(`${pathname}?${p.toString()}`, { scroll: false });
  };

  if (!ready) {
    return (
      <div className="space-y-8">
        <div className="space-y-3">
          <Skeleton className="h-9 w-72" />
          <Skeleton className="h-4 w-full max-w-md" />
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-[5.5rem] rounded-2xl" />
          ))}
        </div>
        <Skeleton className="h-11 w-full max-w-xl rounded-xl" />
        <Skeleton className="h-[22rem] w-full rounded-2xl" />
      </div>
    );
  }

  if (results.length === 0) {
    return (
      <div className="space-y-8">
        <PageHeader
          title="Validation results"
          description="Per-employee computations, statutory findings, and risk scores appear here after you complete an upload validation in this browser."
          actions={
            <Button asChild className="rounded-xl shadow-soft">
              <Link href="/payroll/upload" className="gap-2">
                <UploadCloud size={16} strokeWidth={2} /> New validation
              </Link>
            </Button>
          }
        />
        <EmptyState
          icon={<Activity className="h-7 w-7 text-ink-400 dark:text-ink-300" strokeWidth={1.5} />}
          title="No results in this session"
          description="We keep the latest run in session storage so you can drill down without round-tripping the server. Start an upload to populate this view."
          action={
            <Button asChild variant="outline">
              <Link href="/dashboard">Back to dashboard</Link>
            </Button>
          }
        />
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <PageHeader
        title="Validation results"
        description={
          <>
            {results.length.toLocaleString("en-IN")} employees · {failFindings.length} open findings · Financial exposure{" "}
            {summary?.total_financial_impact != null
              ? `₹${Math.round(summary.total_financial_impact).toLocaleString("en-IN")}`
              : "—"}
          </>
        }
        actions={
          <>
            <Button
              type="button"
              variant="outline"
              className="gap-2"
              disabled={exportBusy}
              onClick={() => void downloadExcelAudit()}
            >
              <Download size={15} strokeWidth={2} />
              {exportBusy ? "Working…" : "Excel audit"}
            </Button>
            <Button variant="outline" asChild>
              <Link href="/payroll/upload" className="gap-2">
                <UploadCloud size={15} strokeWidth={2} /> New run
              </Link>
            </Button>
          </>
        }
      />

      {/* Summary stat cards */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <StatCard label="Employees"   value={results.length}               icon={<Users size={20}/>}        color="brand" />
        <StatCard label="Critical"    value={summary?.critical ?? 0}       icon={<XCircle size={20}/>}      color="red" />
        <StatCard label="Warnings"    value={summary?.warning ?? 0}        icon={<AlertTriangle size={20}/>} color="yellow" />
        <StatCard label="High Risk"   value={riskScores.filter(r=>r.risk_level==="HIGH").length} icon={<Flame size={20}/>} color="red" />
        <StatCard label="Passed"      value={summary?.pass ?? 0}           icon={<CheckCircle2 size={20}/>} color="green" />
        <StatCard
          label="Financial Impact"
          value={summary?.total_financial_impact != null
            ? `₹${Math.round(summary.total_financial_impact).toLocaleString("en-IN")}`
            : "–"}
          icon={<Activity size={20}/>}
          color="blue"
          sub="est. total exposure"
        />
      </div>

      {/* Tab bar */}
      <div className="flex flex-wrap gap-1 rounded-2xl border border-ink-200/70 bg-ink-50/80 p-1.5 ring-1 ring-ink-900/[0.02] dark:border-white/10 dark:bg-white/[0.04] dark:ring-white/[0.04]">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => commitTab(t.id)}
            className={`flex items-center gap-1.5 whitespace-nowrap rounded-xl px-4 py-2.5 text-sm font-semibold transition-all ${
              tab === t.id
                ? "bg-white text-ink-900 shadow-soft ring-1 ring-ink-200/80 dark:bg-ink-900 dark:text-white dark:ring-white/10"
                : "text-ink-600 hover:bg-white/70 hover:text-ink-900 dark:text-ink-300 dark:hover:bg-white/[0.06] dark:hover:text-white"
            }`}
          >
            {t.label}
            {t.badge != null && t.badge > 0 && (
              <span
                className={`rounded-full px-1.5 py-0.5 text-xs font-bold ${
                  t.badgeColor === "red"
                    ? "bg-danger-100 text-danger-700 dark:bg-danger-500/20 dark:text-danger-300"
                    : "bg-warning-100 text-warning-700 dark:bg-warning-500/20 dark:text-warning-300"
                }`}
              >
                {t.badge}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* ── Overview Tab ── */}
      {tab === "overview" && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Risk distribution pie */}
          <div className="rounded-2xl border border-ink-200/70 bg-white p-5 shadow-soft ring-1 ring-ink-900/[0.03] dark:border-white/[0.07] dark:bg-ink-900/70 dark:ring-white/[0.04]">
            <h3 className="mb-4 flex items-center gap-2 font-display text-base font-semibold tracking-tight text-ink-900 dark:text-white">
              <Shield size={16} className="text-brand-600 dark:text-brand-300" /> Risk distribution
            </h3>
            <ResponsiveContainer width="100%" height={220}>
              <PieChart>
                <Pie
                  data={riskDist}
                  cx="50%"
                  cy="50%"
                  outerRadius={80}
                  dataKey="value"
                  nameKey="name"
                  label={({ name, value }) => `${name}: ${value}`}
                >
                  {riskDist.map((_, i) => (
                    <Cell key={i} fill={PIE_COLORS[i]} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{
                    background: "rgba(15,18,32,0.95)",
                    border: "1px solid rgba(255,255,255,0.1)",
                    borderRadius: 10,
                    color: "#fff",
                    fontSize: 12,
                  }}
                />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          </div>

          {/* Top violated rules */}
          <div className="rounded-2xl border border-ink-200/70 bg-white p-5 shadow-soft ring-1 ring-ink-900/[0.03] dark:border-white/[0.07] dark:bg-ink-900/70 dark:ring-white/[0.04]">
            <h3 className="mb-4 flex items-center gap-2 font-display text-base font-semibold tracking-tight text-ink-900 dark:text-white">
              <TrendingUp size={16} className="text-brand-600 dark:text-brand-300" /> Top rule failures
            </h3>
            {ruleTriggerData.length === 0 ? (
              <div className="mt-8 flex items-center justify-center gap-2 text-success-600 dark:text-success-300">
                <CheckCircle2 size={20} /> No violations found
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={ruleTriggerData} layout="vertical" margin={{ left: 20 }}>
                  <XAxis
                    type="number"
                    tick={{ fontSize: 11, fill: "currentColor" }}
                    className="text-ink-500 dark:text-ink-400"
                  />
                  <YAxis
                    dataKey="name"
                    type="category"
                    tick={{ fontSize: 11, fill: "currentColor" }}
                    className="text-ink-600 dark:text-ink-300"
                    width={80}
                  />
                  <Tooltip
                    cursor={{ fill: "rgba(99,102,241,0.06)" }}
                    contentStyle={{
                      background: "rgba(15,18,32,0.95)",
                      border: "1px solid rgba(255,255,255,0.1)",
                      borderRadius: 10,
                      color: "#fff",
                      fontSize: 12,
                    }}
                  />
                  <Bar dataKey="count" fill="url(#resBarGrad)" radius={[0, 6, 6, 0]} />
                  <defs>
                    <linearGradient id="resBarGrad" x1="0" y1="0" x2="1" y2="0">
                      <stop offset="0%" stopColor="#6366f1" />
                      <stop offset="100%" stopColor="#a855f7" />
                    </linearGradient>
                  </defs>
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>

          {/* Employee table with risk overview */}
          <div className="overflow-hidden rounded-2xl border border-ink-200/70 bg-white shadow-soft ring-1 ring-ink-900/[0.03] dark:border-white/[0.07] dark:bg-ink-900/70 dark:ring-white/[0.04] lg:col-span-2">
            <div className="flex items-center justify-between border-b border-ink-100 px-5 py-4 dark:border-white/[0.06]">
              <h3 className="font-display text-base font-semibold tracking-tight text-ink-900 dark:text-white">
                Employee summary
              </h3>
              <span className="text-sm text-ink-500 dark:text-ink-400">{results.length} employees</span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-ink-50/80 text-[11px] uppercase tracking-[0.12em] text-ink-500 dark:bg-white/[0.03] dark:text-ink-300">
                  <tr>
                    {["Emp ID", "Name", "Risk", "Score", "PF emp", "ESIC", "PT", "Issues", ""].map((h) => (
                      <th key={h} className="px-4 py-2.5 text-left font-semibold">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-ink-100 dark:divide-white/[0.05]">
                  {results.map((r) => {
                    const empFindings = r.findings || [];
                    const fails = empFindings.filter((f) => f.status === "FAIL");
                    const hasCrit = fails.some((f) => f.severity === "CRITICAL");
                    return (
                      <tr
                        key={r.employee_id}
                        className="transition-colors hover:bg-ink-50/60 dark:hover:bg-white/[0.04]"
                      >
                        <td className="px-4 py-3 font-mono text-ink-600 dark:text-ink-300">{r.employee_id}</td>
                        <td className="px-4 py-3 font-medium text-ink-800 dark:text-white">
                          {r.employee_name || "—"}
                        </td>
                        <td className="px-4 py-3">
                          <RiskBadge level={r.risk_level || "LOW"} />
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <div className="h-1.5 w-16 overflow-hidden rounded-full bg-ink-200 dark:bg-white/10">
                              <div
                                className={`h-1.5 rounded-full ${
                                  r.risk_level === "HIGH"
                                    ? "bg-danger-500"
                                    : r.risk_level === "MEDIUM"
                                      ? "bg-warning-500"
                                      : "bg-success-500"
                                }`}
                                style={{ width: `${r.risk_score || 0}%` }}
                              />
                            </div>
                            <span className="num text-xs text-ink-500 dark:text-ink-400">
                              {r.risk_score ?? 0}
                            </span>
                          </div>
                        </td>
                        <td className="num px-4 py-3 text-ink-700 dark:text-ink-200">
                          {fmt(r.pf_amount_employee)}
                        </td>
                        <td className="num px-4 py-3 text-ink-700 dark:text-ink-200">
                          {r.esic_eligible ? (
                            fmt(r.esic_employee)
                          ) : (
                            <span className="text-xs text-ink-400 dark:text-ink-500">exempt</span>
                          )}
                        </td>
                        <td className="num px-4 py-3 text-ink-700 dark:text-ink-200">
                          {r.pt_due > 0 ? (
                            fmt(r.pt_due)
                          ) : (
                            <span className="text-xs text-ink-400 dark:text-ink-500">nil</span>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          {fails.length > 0 ? (
                            <span
                              className={`rounded-full px-2 py-0.5 text-xs font-semibold ${
                                hasCrit
                                  ? "bg-danger-100 text-danger-700 dark:bg-danger-500/15 dark:text-danger-300"
                                  : "bg-warning-100 text-warning-700 dark:bg-warning-500/15 dark:text-warning-300"
                              }`}
                            >
                              {fails.length} issue{fails.length > 1 ? "s" : ""}
                            </span>
                          ) : (
                            <span className="rounded-full bg-success-100 px-2 py-0.5 text-xs font-semibold text-success-700 dark:bg-success-500/15 dark:text-success-300">
                              OK
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <Link
                            href={`/payroll/employee/${encodeURIComponent(r.employee_id)}`}
                            className="inline-flex items-center gap-1 text-xs font-semibold text-brand-700 hover:text-brand-800 dark:text-brand-300 dark:hover:text-brand-200"
                          >
                            Drilldown <ArrowRight size={12} />
                          </Link>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* ── Risk Scores Tab ── */}
      {tab === "risk" && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <div className="relative min-w-48 flex-1">
              <Search
                size={14}
                className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-400 dark:text-ink-500"
              />
              <input
                className="w-full rounded-xl border border-ink-200 bg-white py-2.5 pl-9 pr-3 text-sm text-ink-900 shadow-sm outline-none ring-brand-500/20 placeholder:text-ink-400 focus-visible:ring-[3px] dark:border-white/10 dark:bg-white/[0.04] dark:text-white dark:placeholder:text-ink-500"
                placeholder="Search employee…"
                value={rSearch}
                onChange={(e) => setRSearch(e.target.value)}
              />
            </div>
            {(["ALL", "HIGH", "MEDIUM", "LOW"] as const).map((lvl) => (
              <button
                key={lvl}
                onClick={() => setRLevel(lvl)}
                className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
                  rLevel === lvl
                    ? lvl === "HIGH"
                      ? "bg-danger-600 text-white shadow-sm"
                      : lvl === "MEDIUM"
                        ? "bg-warning-500 text-white shadow-sm"
                        : lvl === "LOW"
                          ? "bg-success-600 text-white shadow-sm"
                          : "bg-gradient-to-br from-brand-600 to-accent-600 text-white shadow-sm"
                    : "bg-ink-100 text-ink-600 hover:bg-ink-200 dark:bg-white/[0.05] dark:text-ink-300 dark:hover:bg-white/[0.08]"
                }`}
              >
                {lvl}
              </button>
            ))}
          </div>
          <div className="overflow-hidden rounded-2xl border border-ink-200/70 bg-white shadow-soft ring-1 ring-ink-900/[0.03] dark:border-white/[0.07] dark:bg-ink-900/70 dark:ring-white/[0.04]">
            <table className="w-full text-sm">
              <thead className="bg-ink-50/80 text-[11px] uppercase tracking-[0.12em] text-ink-500 dark:bg-white/[0.03] dark:text-ink-300">
                <tr>
                  {["Emp ID", "Name", "Risk level", "Score", "Breakdown", ""].map((h) => (
                    <th key={h} className="px-4 py-3 text-left font-semibold">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-100 dark:divide-white/[0.05]">
                {filteredRisk.map((r) => (
                  <tr
                    key={r.employee_id}
                    className="transition-colors hover:bg-ink-50/60 dark:hover:bg-white/[0.04]"
                  >
                    <td className="px-4 py-3 font-mono text-ink-600 dark:text-ink-300">
                      {r.employee_id}
                    </td>
                    <td className="px-4 py-3 font-medium text-ink-800 dark:text-white">
                      {r.employee_name || "—"}
                    </td>
                    <td className="px-4 py-3">
                      <RiskBadge level={r.risk_level} />
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <div className="h-2 w-24 overflow-hidden rounded-full bg-ink-200 dark:bg-white/10">
                          <div
                            className={`h-2 rounded-full ${
                              r.risk_level === "HIGH"
                                ? "bg-danger-500"
                                : r.risk_level === "MEDIUM"
                                  ? "bg-warning-500"
                                  : "bg-success-500"
                            }`}
                            style={{ width: `${r.risk_score}%` }}
                          />
                        </div>
                        <span className="num text-sm font-semibold text-ink-700 dark:text-ink-200">
                          {r.risk_score}
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-xs text-ink-500 dark:text-ink-400">
                      {r.score_breakdown && Object.entries(r.score_breakdown)
                        .filter(([,v])=>v>0)
                        .map(([k,v])=>`${k}: ${v}`).join(" · ")}
                    </td>
                    <td className="px-4 py-3">
                      <Link
                        href={`/payroll/employee/${encodeURIComponent(r.employee_id)}`}
                        className="inline-flex items-center gap-1 text-xs text-brand-700 hover:text-brand-800 font-medium"
                      >
                        View <ArrowRight size={12}/>
                      </Link>
                    </td>
                  </tr>
                ))}
                {filteredRisk.length === 0 && (
                  <tr>
                    <td
                      colSpan={6}
                      className="px-4 py-10 text-center text-ink-400 dark:text-ink-500"
                    >
                      No results match your filters.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── Findings Tab ── */}
      {tab === "findings" && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <div className="relative min-w-48 flex-1">
              <Search
                size={14}
                className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-400 dark:text-ink-500"
              />
              <input
                className="w-full rounded-xl border border-ink-200 bg-white py-2.5 pl-9 pr-3 text-sm text-ink-900 shadow-sm outline-none ring-brand-500/20 placeholder:text-ink-400 focus-visible:ring-[3px] dark:border-white/10 dark:bg-white/[0.04] dark:text-white dark:placeholder:text-ink-500"
                placeholder="Search rule, employee, component…"
                value={fSearch}
                onChange={(e) => setFSearch(e.target.value)}
              />
            </div>
            {(["ALL", "CRITICAL", "WARNING", "INFO"] as const).map((s) => (
              <button
                key={s}
                onClick={() => setFSev(s)}
                className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
                  fSev === s
                    ? s === "CRITICAL"
                      ? "bg-danger-600 text-white shadow-sm"
                      : s === "WARNING"
                        ? "bg-warning-500 text-white shadow-sm"
                        : s === "INFO"
                          ? "bg-sky-600 text-white shadow-sm"
                          : "bg-gradient-to-br from-brand-600 to-accent-600 text-white shadow-sm"
                    : "bg-ink-100 text-ink-600 hover:bg-ink-200 dark:bg-white/[0.05] dark:text-ink-300 dark:hover:bg-white/[0.08]"
                }`}
              >
                {s}
              </button>
            ))}
            <button
              onClick={() => setFStatus((s) => (s === "FAIL" ? "ALL" : "FAIL"))}
              className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
                fStatus === "FAIL"
                  ? "bg-ink-900 text-white dark:bg-white dark:text-ink-900"
                  : "bg-ink-100 text-ink-600 hover:bg-ink-200 dark:bg-white/[0.05] dark:text-ink-300 dark:hover:bg-white/[0.08]"
              }`}
            >
              Fails only
            </button>
          </div>

          <p className="text-sm text-ink-500 dark:text-ink-400">
            {filteredFindings.length} findings shown
          </p>

          <div className="space-y-2">
            {filteredFindings.map((f, i) => (
              <div
                key={i}
                className={`rounded-2xl border p-4 shadow-soft transition-colors ${
                  f.status === "PASS"
                    ? "border-success-200/80 bg-gradient-to-br from-success-50 to-white dark:border-success-500/20 dark:from-success-500/10 dark:to-ink-900/40"
                    : f.severity === "CRITICAL"
                      ? "border-danger-200/80 bg-gradient-to-br from-danger-50 to-white dark:border-danger-500/20 dark:from-danger-500/10 dark:to-ink-900/40"
                      : f.severity === "WARNING"
                        ? "border-warning-200/80 bg-gradient-to-br from-warning-50 to-white dark:border-warning-500/25 dark:from-warning-500/10 dark:to-ink-900/40"
                        : "border-sky-200/80 bg-gradient-to-br from-sky-50 to-white dark:border-sky-500/25 dark:from-sky-500/10 dark:to-ink-900/40"
                }`}
              >
                <div className="mb-2 flex flex-wrap items-start justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={`rounded px-2 py-0.5 font-mono text-xs font-semibold ${
                        SEV_COLOR[f.status === "PASS" ? "PASS" : f.severity]
                      }`}
                    >
                      {f.rule_id}
                    </span>
                    <span
                      className={`rounded px-2 py-0.5 text-xs font-semibold ${
                        SEV_COLOR[f.status === "PASS" ? "PASS" : f.severity]
                      }`}
                    >
                      {f.status === "PASS" ? "PASS" : f.severity}
                    </span>
                    <span className="text-sm font-semibold text-ink-800 dark:text-white">
                      {f.rule_name}
                    </span>
                  </div>
                  <Link
                    href={`/payroll/employee/${encodeURIComponent(f.employee_id)}`}
                    className="text-xs font-semibold text-brand-700 hover:text-brand-800 dark:text-brand-300 dark:hover:text-brand-200"
                  >
                    {f.employee_id} {f.employee_name ? `· ${f.employee_name}` : ""}
                  </Link>
                </div>
                <p className="mb-1.5 text-sm text-ink-700 dark:text-ink-200">{f.reason}</p>
                <div className="mb-1.5 flex flex-wrap gap-4 text-xs text-ink-500 dark:text-ink-400">
                  {f.expected_value && (
                    <span>
                      Expected: <strong className="text-ink-700 dark:text-ink-200">{f.expected_value}</strong>
                    </span>
                  )}
                  {f.actual_value && (
                    <span>
                      Actual: <strong className="text-ink-700 dark:text-ink-200">{f.actual_value}</strong>
                    </span>
                  )}
                  {f.difference && f.difference !== "0.00" && (
                    <span>
                      Diff: <strong className="text-ink-700 dark:text-ink-200">{f.difference}</strong>
                    </span>
                  )}
                  {f.financial_impact > 0 && (
                    <span className="font-semibold text-danger-600 dark:text-danger-300">
                      Impact: ₹{f.financial_impact.toLocaleString("en-IN")}
                    </span>
                  )}
                </div>
                {f.suggested_fix && (
                  <div className="mt-2 rounded-lg border border-brand-100 bg-brand-50/80 px-3 py-2 text-xs text-brand-950 dark:border-brand-500/30 dark:bg-brand-500/10 dark:text-brand-100">
                    <span className="font-semibold">Fix: </span>
                    {f.suggested_fix}
                  </div>
                )}
              </div>
            ))}
            {filteredFindings.length === 0 && (
              <div className="py-16 text-center text-ink-400 dark:text-ink-500">
                <CheckCircle2 size={40} className="mx-auto mb-3 text-success-300 dark:text-success-400" />
                <p className="text-lg font-medium text-ink-500 dark:text-ink-400">
                  No findings match your filters
                </p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── PF Tab ── */}
      {tab === "pf" && (
        <div className="overflow-hidden rounded-2xl border border-ink-200/70 bg-white shadow-soft ring-1 ring-ink-900/[0.03] dark:border-white/[0.07] dark:bg-ink-900/70 dark:ring-white/[0.04]">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-ink-50/80 text-[11px] uppercase tracking-[0.12em] text-ink-500 dark:bg-white/[0.03] dark:text-ink-300">
                <tr>
                  {["Emp ID", "Name", "PF wage", "Type", "PF (emp)", "PF (er)", "EPS", "EPF", "EDLI+admin"].map((h) => (
                    <th key={h} className="px-4 py-2.5 text-left font-semibold">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-100 dark:divide-white/[0.05]">
                {results.map((r) => (
                  <tr
                    key={r.employee_id}
                    className="transition-colors hover:bg-ink-50/60 dark:hover:bg-white/[0.04]"
                  >
                    <td className="px-4 py-3 font-mono text-ink-600 dark:text-ink-300">{r.employee_id}</td>
                    <td className="px-4 py-3 text-ink-800 dark:text-white">{r.employee_name || "—"}</td>
                    <td className="num px-4 py-3 text-ink-700 dark:text-ink-200">{fmt(r.pf_wage)}</td>
                    <td className="px-4 py-3">
                      <span
                        className={`rounded px-2 py-0.5 text-xs font-semibold ${
                          r.pf_type === "uncapped"
                            ? "bg-warning-100 text-warning-800 dark:bg-warning-500/15 dark:text-warning-300"
                            : "bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300"
                        }`}
                      >
                        {r.pf_type}
                      </span>
                    </td>
                    <td className="num px-4 py-3 font-semibold text-ink-900 dark:text-white">
                      {fmt(r.pf_amount_employee)}
                    </td>
                    <td className="num px-4 py-3 font-semibold text-ink-900 dark:text-white">
                      {fmt(r.pf_amount_employer)}
                    </td>
                    <td className="num px-4 py-3 text-ink-500 dark:text-ink-400">{fmt(r.pf_breakup?.eps)}</td>
                    <td className="num px-4 py-3 text-ink-500 dark:text-ink-400">{fmt(r.pf_breakup?.epf)}</td>
                    <td className="num px-4 py-3 text-ink-500 dark:text-ink-400">
                      {fmt((r.pf_breakup?.edli || 0) + (r.pf_breakup?.admin || 0))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── ESIC Tab ── */}
      {tab === "esic" && (
        <div className="overflow-hidden rounded-2xl border border-ink-200/70 bg-white shadow-soft ring-1 ring-ink-900/[0.03] dark:border-white/[0.07] dark:bg-ink-900/70 dark:ring-white/[0.04]">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-ink-50/80 text-[11px] uppercase tracking-[0.12em] text-ink-500 dark:bg-white/[0.03] dark:text-ink-300">
                <tr>
                  {["Emp ID", "Name", "ESIC wage", "Eligible?", "ESIC (emp)", "ESIC (er)"].map((h) => (
                    <th key={h} className="px-4 py-2.5 text-left font-semibold">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-100 dark:divide-white/[0.05]">
                {results.map((r) => (
                  <tr
                    key={r.employee_id}
                    className="transition-colors hover:bg-ink-50/60 dark:hover:bg-white/[0.04]"
                  >
                    <td className="px-4 py-3 font-mono text-ink-600 dark:text-ink-300">{r.employee_id}</td>
                    <td className="px-4 py-3 text-ink-800 dark:text-white">{r.employee_name || "—"}</td>
                    <td className="num px-4 py-3 text-ink-700 dark:text-ink-200">{fmt(r.esic_wage)}</td>
                    <td className="px-4 py-3">
                      {r.esic_eligible ? (
                        <span className="rounded bg-success-100 px-2 py-0.5 text-xs font-semibold text-success-700 dark:bg-success-500/15 dark:text-success-300">
                          Yes
                        </span>
                      ) : (
                        <span className="rounded bg-ink-100 px-2 py-0.5 text-xs font-semibold text-ink-500 dark:bg-white/[0.06] dark:text-ink-300">
                          Exempt
                        </span>
                      )}
                    </td>
                    <td className="num px-4 py-3 font-semibold text-ink-900 dark:text-white">
                      {r.esic_eligible ? fmt(r.esic_employee) : "–"}
                    </td>
                    <td className="num px-4 py-3 font-semibold text-ink-900 dark:text-white">
                      {r.esic_eligible ? fmt(r.esic_employer) : "–"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── PT/LWF Tab ── */}
      {tab === "ptlwf" && (
        <div className="overflow-hidden rounded-2xl border border-ink-200/70 bg-white shadow-soft ring-1 ring-ink-900/[0.03] dark:border-white/[0.07] dark:bg-ink-900/70 dark:ring-white/[0.04]">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-ink-50/80 text-[11px] uppercase tracking-[0.12em] text-ink-500 dark:bg-white/[0.03] dark:text-ink-300">
                <tr>
                  {["Emp ID", "Name", "PT state", "PT due", "LWF state", "LWF (emp)", "LWF (er)"].map((h) => (
                    <th key={h} className="px-4 py-2.5 text-left font-semibold">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-100 dark:divide-white/[0.05]">
                {results.map((r) => (
                  <tr
                    key={r.employee_id}
                    className="transition-colors hover:bg-ink-50/60 dark:hover:bg-white/[0.04]"
                  >
                    <td className="px-4 py-3 font-mono text-ink-600 dark:text-ink-300">{r.employee_id}</td>
                    <td className="px-4 py-3 text-ink-800 dark:text-white">{r.employee_name || "—"}</td>
                    <td className="px-4 py-3 text-ink-500 dark:text-ink-400">
                      {(r as unknown as { pt_applicable_state: string }).pt_applicable_state || "–"}
                    </td>
                    <td className="num px-4 py-3 font-semibold text-ink-900 dark:text-white">
                      {r.pt_due > 0 ? (
                        fmt(r.pt_due)
                      ) : (
                        <span className="text-ink-400 dark:text-ink-500">nil</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-ink-500 dark:text-ink-400">
                      {(r as unknown as { lwf_applicable_state: string }).lwf_applicable_state || "–"}
                    </td>
                    <td className="num px-4 py-3 text-ink-700 dark:text-ink-200">
                      {r.lwf_employee > 0 ? fmt(r.lwf_employee) : "–"}
                    </td>
                    <td className="num px-4 py-3 text-ink-700 dark:text-ink-200">
                      {r.lwf_employer > 0 ? fmt(r.lwf_employer) : "–"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── LOP/Arrear Tab ── */}
      {tab === "lop" && (
        <div className="space-y-4">
          {results
            .filter(
              (r) =>
                r.lop_check?.diffs?.length ||
                r.increment_arrear?.applicable ||
                r.tds_risk_flags?.length,
            )
            .map((r) => (
              <div
                key={r.employee_id}
                className="rounded-2xl border border-ink-200/70 bg-white p-5 shadow-soft ring-1 ring-ink-900/[0.03] dark:border-white/[0.07] dark:bg-ink-900/70 dark:ring-white/[0.04]"
              >
                <div className="mb-3 flex items-center justify-between">
                  <div>
                    <span className="font-semibold text-ink-800 dark:text-white">{r.employee_id}</span>
                    {r.employee_name && (
                      <span className="ml-2 text-sm text-ink-500 dark:text-ink-400">
                        {r.employee_name}
                      </span>
                    )}
                  </div>
                  <div className="flex gap-2">
                    {r.paid_days != null && (
                      <span className="rounded bg-ink-100 px-2 py-0.5 text-xs text-ink-600 dark:bg-white/[0.06] dark:text-ink-300">
                        Paid: {r.paid_days}d | LOP: {r.lop_days ?? 0}d
                      </span>
                    )}
                  </div>
                </div>
                {r.lop_check?.diffs?.length > 0 && (
                  <div className="mb-3">
                    <p className="mb-1 text-xs font-semibold text-ink-500 dark:text-ink-400">
                      LOP proration diffs
                    </p>
                    <div className="space-y-1">
                      {r.lop_check.diffs.map((d, i) => (
                        <div key={i} className="flex items-center gap-3 text-xs">
                          <span className="font-mono text-ink-600 dark:text-ink-300">{d.component}</span>
                          <span className="text-ink-400 dark:text-ink-500">
                            Expected:{" "}
                            <strong className="text-ink-700 dark:text-ink-200">
                              {d.expected.toFixed(2)}
                            </strong>
                          </span>
                          <span className="text-ink-400 dark:text-ink-500">
                            Actual:{" "}
                            <strong className="text-ink-700 dark:text-ink-200">{d.actual.toFixed(2)}</strong>
                          </span>
                          <span
                            className={
                              d.diff > 0
                                ? "font-semibold text-danger-600 dark:text-danger-300"
                                : "font-semibold text-success-600 dark:text-success-300"
                            }
                          >
                            {d.diff > 0 ? "+" : ""}
                            {d.diff.toFixed(2)}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {r.increment_arrear?.applicable && (
                  <div className="rounded-lg bg-brand-50 p-3 text-xs text-brand-950 ring-1 ring-brand-100 dark:bg-brand-500/10 dark:text-brand-100 dark:ring-brand-500/30">
                    <strong>Increment arrear:</strong> Expected ₹
                    {r.increment_arrear.expected_total.toFixed(2)} over {r.increment_arrear.months}{" "}
                    month(s) · Actual ₹{r.increment_arrear.actual_total.toFixed(2)}
                  </div>
                )}
                {r.tds_risk_flags?.length > 0 && (
                  <div className="mt-2 space-y-1">
                    {r.tds_risk_flags.map((f, i) => (
                      <div
                        key={i}
                        className="rounded-lg border border-warning-200 bg-warning-50 p-2 text-xs text-warning-800 dark:border-warning-500/30 dark:bg-warning-500/10 dark:text-warning-200"
                      >
                        <AlertTriangle size={12} className="mr-1.5 inline" /> {f}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          {results.filter(
            (r) =>
              r.lop_check?.diffs?.length ||
              r.increment_arrear?.applicable ||
              r.tds_risk_flags?.length,
          ).length === 0 && (
            <div className="py-16 text-center text-ink-400 dark:text-ink-500">
              <CheckCircle2 size={40} className="mx-auto mb-3 text-success-300 dark:text-success-400" />
              <p className="text-ink-500 dark:text-ink-400">No LOP/Arrear issues found.</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ResultsPageSkeleton() {
  return (
    <div className="space-y-8">
      <div className="space-y-3">
        <Skeleton className="h-9 w-72" />
        <Skeleton className="h-4 w-full max-w-lg" />
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-[5.5rem] rounded-2xl" />
        ))}
      </div>
      <Skeleton className="h-12 w-full max-w-xl rounded-xl" />
      <Skeleton className="h-[28rem] w-full rounded-2xl" />
    </div>
  );
}

export default function ResultsPage() {
  return (
    <Suspense fallback={<ResultsPageSkeleton />}>
      <PayrollResultsContent />
    </Suspense>
  );
}
