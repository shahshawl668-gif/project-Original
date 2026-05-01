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
  CRITICAL: "bg-red-100 text-red-800 border border-red-200",
  WARNING:  "bg-yellow-100 text-yellow-800 border border-yellow-200",
  INFO:     "bg-blue-100 text-blue-700 border border-blue-200",
  PASS:     "bg-green-100 text-green-700 border border-green-200",
};

const RISK_COLOR: Record<string, { bg: string; text: string; dot: string }> = {
  HIGH:   { bg: "bg-red-50 border-red-200",    text: "text-red-700",    dot: "bg-red-500"    },
  MEDIUM: { bg: "bg-yellow-50 border-yellow-200", text: "text-yellow-700", dot: "bg-yellow-500" },
  LOW:    { bg: "bg-green-50 border-green-200", text: "text-green-700", dot: "bg-green-500"  },
};

const PIE_COLORS = ["#ef4444", "#f59e0b", "#22c55e"];

function StatCard({ label, value, sub, icon, color = "brand" }: {
  label: string; value: string | number; sub?: string;
  icon?: ReactNode; color?: string;
}) {
  const bg: Record<string, string> = {
    red: "bg-red-50 border-red-100 shadow-sm ring-1 ring-red-900/[0.03]",
    yellow: "bg-amber-50 border-amber-100 shadow-sm ring-1 ring-amber-900/[0.03]",
    green: "bg-emerald-50 border-emerald-100 shadow-sm ring-1 ring-emerald-900/[0.03]",
    brand: "bg-brand-50 border-brand-100 shadow-sm ring-1 ring-brand-900/[0.03]",
    blue: "bg-sky-50 border-sky-100 shadow-sm ring-1 ring-sky-900/[0.03]",
  };
  const txt: Record<string, string> = {
    red: "text-red-600",
    yellow: "text-amber-600",
    green: "text-emerald-600",
    brand: "text-brand-600",
    blue: "text-sky-600",
  };
  return (
    <div className={`flex items-center gap-4 rounded-2xl border p-4 ${bg[color] || bg.brand}`}>
      {icon && <div className={`text-2xl ${txt[color] || txt.brand}`}>{icon}</div>}
      <div className="min-w-0">
        <p className="text-2xs font-semibold uppercase tracking-widest text-slate-500">{label}</p>
        <p className={`truncate text-2xl font-semibold tabular-nums tracking-tight ${txt[color] || txt.brand}`}>{value}</p>
        {sub && <p className="mt-0.5 text-2xs font-medium text-slate-500">{sub}</p>}
      </div>
    </div>
  );
}

function RiskBadge({ level }: { level: "LOW" | "MEDIUM" | "HIGH" }) {
  const c = RISK_COLOR[level] || RISK_COLOR.LOW;
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-semibold border ${c.bg} ${c.text}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${c.dot}`} />
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
          icon={<Activity className="h-7 w-7 text-slate-400" strokeWidth={1.5} />}
          title="No results in this session"
          description="We keep the latest run in session storage so you can drill down without round-tripping the server. Start an upload to populate this view."
          action={
            <Button asChild variant="outline" className="rounded-xl">
              <Link href="/dashboard">Back to dashboard</Link>
            </Button>
          }
          className="bg-white shadow-soft ring-1 ring-slate-900/[0.04]"
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
              className="rounded-xl border-slate-200 bg-white shadow-sm gap-2"
              disabled={exportBusy}
              onClick={() => void downloadExcelAudit()}
            >
              <Download size={15} strokeWidth={2} />
              {exportBusy ? "Working…" : "Excel audit"}
            </Button>
            <Button variant="outline" asChild className="rounded-xl border-slate-200 bg-white shadow-sm">
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
      <div className="flex flex-wrap gap-1 rounded-2xl bg-slate-100/90 p-1.5 ring-1 ring-slate-200/80">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => commitTab(t.id)}
            className={`flex items-center gap-1.5 whitespace-nowrap rounded-xl px-4 py-2.5 text-sm font-semibold transition-all ${
              tab === t.id
                ? "bg-white text-slate-900 shadow-sm ring-1 ring-slate-200/80"
                : "text-slate-600 hover:bg-white/60 hover:text-slate-900"
            }`}
          >
            {t.label}
            {t.badge != null && t.badge > 0 && (
              <span className={`text-xs px-1.5 py-0.5 rounded-full font-semibold
                ${t.badgeColor === "red" ? "bg-red-100 text-red-700" : "bg-yellow-100 text-yellow-700"}`}>
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
          <div className="bg-white rounded-xl border border-slate-200 p-5">
            <h3 className="text-base font-semibold text-slate-800 mb-4 flex items-center gap-2">
              <Shield size={16} className="text-brand-600"/> Risk Distribution
            </h3>
            <ResponsiveContainer width="100%" height={220}>
              <PieChart>
                <Pie data={riskDist} cx="50%" cy="50%" outerRadius={80}
                  dataKey="value" nameKey="name" label={({name,value}) => `${name}: ${value}`}>
                  {riskDist.map((_, i) => (
                    <Cell key={i} fill={PIE_COLORS[i]}/>
                  ))}
                </Pie>
                <Tooltip/>
                <Legend/>
              </PieChart>
            </ResponsiveContainer>
          </div>

          {/* Top violated rules */}
          <div className="bg-white rounded-xl border border-slate-200 p-5">
            <h3 className="text-base font-semibold text-slate-800 mb-4 flex items-center gap-2">
              <TrendingUp size={16} className="text-brand-600"/> Top Rule Failures
            </h3>
            {ruleTriggerData.length === 0 ? (
              <div className="flex items-center gap-2 text-green-600 mt-8 justify-center">
                <CheckCircle2 size={20}/> No violations found
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={ruleTriggerData} layout="vertical" margin={{ left: 20 }}>
                  <XAxis type="number" tick={{fontSize:11}}/>
                  <YAxis dataKey="name" type="category" tick={{fontSize:11}} width={80}/>
                  <Tooltip/>
                  <Bar dataKey="count" fill="#6366f1" radius={[0,4,4,0]}/>
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>

          {/* Employee table with risk overview */}
          <div className="lg:col-span-2 bg-white rounded-xl border border-slate-200 overflow-hidden">
            <div className="px-5 py-4 border-b border-slate-100 flex items-center justify-between">
              <h3 className="text-base font-semibold text-slate-800">Employee Summary</h3>
              <span className="text-sm text-slate-500">{results.length} employees</span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-xs text-slate-500 uppercase tracking-wide">
                  <tr>
                    {["Emp ID","Name","Risk","Score","PF Emp","ESIC","PT","Issues",""].map(h=>(
                      <th key={h} className="px-4 py-2.5 text-left font-medium">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {results.map(r => {
                    const empFindings = r.findings || [];
                    const fails = empFindings.filter(f => f.status === "FAIL");
                    const hasCrit = fails.some(f => f.severity === "CRITICAL");
                    return (
                      <tr key={r.employee_id} className="hover:bg-slate-50 transition-colors">
                        <td className="px-4 py-3 font-mono text-slate-600">{r.employee_id}</td>
                        <td className="px-4 py-3 font-medium text-slate-800">{r.employee_name || "—"}</td>
                        <td className="px-4 py-3"><RiskBadge level={r.risk_level || "LOW"}/></td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <div className="w-16 bg-slate-200 rounded-full h-1.5">
                              <div
                                className={`h-1.5 rounded-full ${r.risk_level==="HIGH"?"bg-red-500":r.risk_level==="MEDIUM"?"bg-yellow-500":"bg-green-500"}`}
                                style={{width:`${r.risk_score || 0}%`}}
                              />
                            </div>
                            <span className="text-xs text-slate-500">{r.risk_score ?? 0}</span>
                          </div>
                        </td>
                        <td className="px-4 py-3 text-slate-700">{fmt(r.pf_amount_employee)}</td>
                        <td className="px-4 py-3 text-slate-700">{r.esic_eligible ? fmt(r.esic_employee) : <span className="text-slate-400 text-xs">exempt</span>}</td>
                        <td className="px-4 py-3 text-slate-700">{r.pt_due > 0 ? fmt(r.pt_due) : <span className="text-slate-400 text-xs">nil</span>}</td>
                        <td className="px-4 py-3">
                          {fails.length > 0 ? (
                            <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${hasCrit ? "bg-red-100 text-red-700" : "bg-yellow-100 text-yellow-700"}`}>
                              {fails.length} issue{fails.length > 1 ? "s" : ""}
                            </span>
                          ) : (
                            <span className="text-xs px-2 py-0.5 rounded-full bg-green-100 text-green-700">OK</span>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <Link
                            href={`/payroll/employee/${encodeURIComponent(r.employee_id)}`}
                            className="inline-flex items-center gap-1 text-xs text-brand-700 hover:text-brand-800 font-medium"
                          >
                            Drilldown <ArrowRight size={12}/>
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
          <div className="flex flex-wrap gap-3 items-center">
            <div className="relative flex-1 min-w-48">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400"/>
              <input
                className="w-full rounded-xl border border-slate-200 bg-white py-2.5 pl-9 pr-3 text-sm shadow-sm outline-none ring-brand-500/20 placeholder:text-slate-400 focus-visible:ring-[3px]"
                placeholder="Search employee…"
                value={rSearch}
                onChange={e => setRSearch(e.target.value)}
              />
            </div>
            {(["ALL","HIGH","MEDIUM","LOW"] as const).map(lvl => (
              <button key={lvl}
                onClick={() => setRLevel(lvl)}
                className={`px-3 py-1.5 text-xs rounded-lg font-medium transition-colors
                  ${rLevel === lvl
                    ? lvl==="HIGH" ? "bg-red-600 text-white"
                    : lvl==="MEDIUM" ? "bg-yellow-500 text-white"
                    : lvl==="LOW" ? "bg-green-600 text-white"
                    : "bg-brand-600 text-white shadow-sm"
                    : "bg-slate-100 text-slate-600 hover:bg-slate-200"}`}
              >
                {lvl}
              </button>
            ))}
          </div>
          <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-xs text-slate-500 uppercase tracking-wide">
                <tr>
                  {["Emp ID","Name","Risk Level","Score","Breakdown",""].map(h=>(
                    <th key={h} className="px-4 py-3 text-left font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {filteredRisk.map(r => (
                  <tr key={r.employee_id} className="hover:bg-slate-50">
                    <td className="px-4 py-3 font-mono text-slate-600">{r.employee_id}</td>
                    <td className="px-4 py-3 font-medium text-slate-800">{r.employee_name || "—"}</td>
                    <td className="px-4 py-3"><RiskBadge level={r.risk_level}/></td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <div className="w-24 bg-slate-200 rounded-full h-2">
                          <div
                            className={`h-2 rounded-full ${r.risk_level==="HIGH"?"bg-red-500":r.risk_level==="MEDIUM"?"bg-yellow-500":"bg-green-500"}`}
                            style={{width:`${r.risk_score}%`}}
                          />
                        </div>
                        <span className="text-sm font-semibold text-slate-700">{r.risk_score}</span>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-500">
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
                  <tr><td colSpan={6} className="px-4 py-10 text-center text-slate-400">No results match your filters.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── Findings Tab ── */}
      {tab === "findings" && (
        <div className="space-y-4">
          <div className="flex flex-wrap gap-3 items-center">
            <div className="relative flex-1 min-w-48">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400"/>
              <input
                className="w-full rounded-xl border border-slate-200 bg-white py-2.5 pl-9 pr-3 text-sm shadow-sm outline-none ring-brand-500/20 placeholder:text-slate-400 focus-visible:ring-[3px]"
                placeholder="Search rule, employee, component…"
                value={fSearch}
                onChange={e => setFSearch(e.target.value)}
              />
            </div>
            {(["ALL","CRITICAL","WARNING","INFO"] as const).map(s => (
              <button key={s} onClick={() => setFSev(s)}
                className={`px-3 py-1.5 text-xs rounded-lg font-medium transition-colors
                  ${fSev===s
                    ? s==="CRITICAL"?"bg-red-600 text-white"
                    : s==="WARNING"?"bg-yellow-500 text-white"
                    : s==="INFO"?"bg-blue-600 text-white"
                    : "bg-brand-600 text-white shadow-sm"
                    : "bg-slate-100 text-slate-600 hover:bg-slate-200"}`}
              >
                {s}
              </button>
            ))}
            <button onClick={() => setFStatus(s => s === "FAIL" ? "ALL" : "FAIL")}
              className={`px-3 py-1.5 text-xs rounded-lg font-medium transition-colors
                ${fStatus === "FAIL" ? "bg-slate-800 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"}`}
            >
              Fails Only
            </button>
          </div>

          <p className="text-sm text-slate-500">{filteredFindings.length} findings shown</p>

          <div className="space-y-2">
            {filteredFindings.map((f, i) => (
              <div key={i}
                className={`rounded-xl border p-4 ${f.status==="PASS" ? "bg-green-50 border-green-100" :
                  f.severity==="CRITICAL" ? "bg-red-50 border-red-200" :
                  f.severity==="WARNING" ? "bg-yellow-50 border-yellow-200" : "bg-blue-50 border-blue-100"}`}
              >
                <div className="flex flex-wrap items-start justify-between gap-2 mb-2">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className={`text-xs px-2 py-0.5 rounded font-mono font-semibold ${SEV_COLOR[f.status==="PASS"?"PASS":f.severity]}`}>
                      {f.rule_id}
                    </span>
                    <span className={`text-xs px-2 py-0.5 rounded font-semibold ${SEV_COLOR[f.status==="PASS"?"PASS":f.severity]}`}>
                      {f.status==="PASS" ? "PASS" : f.severity}
                    </span>
                    <span className="text-sm font-semibold text-slate-800">{f.rule_name}</span>
                  </div>
                  <Link
                    href={`/payroll/employee/${encodeURIComponent(f.employee_id)}`}
                    className="text-xs text-brand-700 hover:text-brand-800 font-medium"
                  >
                    {f.employee_id} {f.employee_name ? `· ${f.employee_name}` : ""}
                  </Link>
                </div>
                <p className="text-sm text-slate-700 mb-1.5">{f.reason}</p>
                <div className="flex flex-wrap gap-4 text-xs text-slate-500 mb-1.5">
                  {f.expected_value && <span>Expected: <strong>{f.expected_value}</strong></span>}
                  {f.actual_value && <span>Actual: <strong>{f.actual_value}</strong></span>}
                  {f.difference && f.difference !== "0.00" && <span>Diff: <strong>{f.difference}</strong></span>}
                  {f.financial_impact > 0 && (
                    <span className="text-red-600 font-semibold">
                      Impact: ₹{f.financial_impact.toLocaleString("en-IN")}
                    </span>
                  )}
                </div>
                {f.suggested_fix && (
                  <div className="mt-2 rounded-lg border border-brand-100 bg-brand-50/80 px-3 py-2 text-xs text-brand-950">
                    <span className="font-semibold">Fix: </span>{f.suggested_fix}
                  </div>
                )}
              </div>
            ))}
            {filteredFindings.length === 0 && (
              <div className="text-center py-16 text-slate-400">
                <CheckCircle2 size={40} className="mx-auto mb-3 text-green-300"/>
                <p className="text-lg font-medium text-slate-500">No findings match your filters</p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── PF Tab ── */}
      {tab === "pf" && (
        <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-xs text-slate-500 uppercase tracking-wide">
                <tr>
                  {["Emp ID","Name","PF Wage","Type","PF (Emp)","PF (Er)","EPS","EPF","EDLI+Admin"].map(h=>(
                    <th key={h} className="px-4 py-2.5 text-left font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {results.map(r => (
                  <tr key={r.employee_id} className="hover:bg-slate-50">
                    <td className="px-4 py-3 font-mono text-slate-600">{r.employee_id}</td>
                    <td className="px-4 py-3">{r.employee_name || "—"}</td>
                    <td className="px-4 py-3">{fmt(r.pf_wage)}</td>
                    <td className="px-4 py-3">
                      <span className={`text-xs px-2 py-0.5 rounded font-medium ${r.pf_type==="uncapped"?"bg-orange-100 text-orange-700":"bg-blue-100 text-blue-700"}`}>
                        {r.pf_type}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-semibold">{fmt(r.pf_amount_employee)}</td>
                    <td className="px-4 py-3 font-semibold">{fmt(r.pf_amount_employer)}</td>
                    <td className="px-4 py-3 text-slate-500">{fmt(r.pf_breakup?.eps)}</td>
                    <td className="px-4 py-3 text-slate-500">{fmt(r.pf_breakup?.epf)}</td>
                    <td className="px-4 py-3 text-slate-500">{fmt((r.pf_breakup?.edli || 0) + (r.pf_breakup?.admin || 0))}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── ESIC Tab ── */}
      {tab === "esic" && (
        <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-xs text-slate-500 uppercase tracking-wide">
                <tr>
                  {["Emp ID","Name","ESIC Wage","Eligible?","ESIC (Emp)","ESIC (Er)"].map(h=>(
                    <th key={h} className="px-4 py-2.5 text-left font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {results.map(r => (
                  <tr key={r.employee_id} className="hover:bg-slate-50">
                    <td className="px-4 py-3 font-mono text-slate-600">{r.employee_id}</td>
                    <td className="px-4 py-3">{r.employee_name || "—"}</td>
                    <td className="px-4 py-3">{fmt(r.esic_wage)}</td>
                    <td className="px-4 py-3">
                      {r.esic_eligible
                        ? <span className="text-xs px-2 py-0.5 rounded bg-green-100 text-green-700 font-medium">Yes</span>
                        : <span className="text-xs px-2 py-0.5 rounded bg-slate-100 text-slate-500 font-medium">Exempt</span>}
                    </td>
                    <td className="px-4 py-3 font-semibold">{r.esic_eligible ? fmt(r.esic_employee) : "–"}</td>
                    <td className="px-4 py-3 font-semibold">{r.esic_eligible ? fmt(r.esic_employer) : "–"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── PT/LWF Tab ── */}
      {tab === "ptlwf" && (
        <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-xs text-slate-500 uppercase tracking-wide">
                <tr>
                  {["Emp ID","Name","PT State","PT Due","LWF State","LWF (Emp)","LWF (Er)"].map(h=>(
                    <th key={h} className="px-4 py-2.5 text-left font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {results.map(r => (
                  <tr key={r.employee_id} className="hover:bg-slate-50">
                    <td className="px-4 py-3 font-mono text-slate-600">{r.employee_id}</td>
                    <td className="px-4 py-3">{r.employee_name || "—"}</td>
                    <td className="px-4 py-3 text-slate-500">{(r as unknown as {pt_applicable_state:string}).pt_applicable_state || "–"}</td>
                    <td className="px-4 py-3 font-semibold">{r.pt_due > 0 ? fmt(r.pt_due) : <span className="text-slate-400">nil</span>}</td>
                    <td className="px-4 py-3 text-slate-500">{(r as unknown as {lwf_applicable_state:string}).lwf_applicable_state || "–"}</td>
                    <td className="px-4 py-3">{r.lwf_employee > 0 ? fmt(r.lwf_employee) : "–"}</td>
                    <td className="px-4 py-3">{r.lwf_employer > 0 ? fmt(r.lwf_employer) : "–"}</td>
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
          {results.filter(r => r.lop_check?.diffs?.length || r.increment_arrear?.applicable || r.tds_risk_flags?.length).map(r => (
            <div key={r.employee_id} className="bg-white rounded-xl border border-slate-200 p-5">
              <div className="flex items-center justify-between mb-3">
                <div>
                  <span className="font-semibold text-slate-800">{r.employee_id}</span>
                  {r.employee_name && <span className="text-slate-500 text-sm ml-2">{r.employee_name}</span>}
                </div>
                <div className="flex gap-2">
                  {r.paid_days != null && (
                    <span className="text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded">
                      Paid: {r.paid_days}d | LOP: {r.lop_days ?? 0}d
                    </span>
                  )}
                </div>
              </div>
              {r.lop_check?.diffs?.length > 0 && (
                <div className="mb-3">
                  <p className="text-xs font-semibold text-slate-500 mb-1">LOP Proration Diffs</p>
                  <div className="space-y-1">
                    {r.lop_check.diffs.map((d,i) => (
                      <div key={i} className="flex items-center gap-3 text-xs">
                        <span className="font-mono text-slate-600">{d.component}</span>
                        <span className="text-slate-400">Expected: <strong>{d.expected.toFixed(2)}</strong></span>
                        <span className="text-slate-400">Actual: <strong>{d.actual.toFixed(2)}</strong></span>
                        <span className={d.diff > 0 ? "text-red-600 font-semibold" : "text-green-600 font-semibold"}>
                          {d.diff > 0 ? "+" : ""}{d.diff.toFixed(2)}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {r.increment_arrear?.applicable && (
                <div className="rounded-lg bg-brand-50 p-3 text-xs text-brand-950 ring-1 ring-brand-100">
                  <strong>Increment Arrear:</strong> Expected ₹{r.increment_arrear.expected_total.toFixed(2)} over {r.increment_arrear.months} month(s) · Actual ₹{r.increment_arrear.actual_total.toFixed(2)}
                </div>
              )}
              {r.tds_risk_flags?.length > 0 && (
                <div className="mt-2 space-y-1">
                  {r.tds_risk_flags.map((f,i) => (
                    <div key={i} className="bg-yellow-50 border border-yellow-200 rounded-lg p-2 text-xs text-yellow-800">
                      <AlertTriangle size={12} className="inline mr-1.5"/> {f}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
          {results.filter(r => r.lop_check?.diffs?.length || r.increment_arrear?.applicable || r.tds_risk_flags?.length).length === 0 && (
            <div className="text-center py-16 text-slate-400">
              <CheckCircle2 size={40} className="mx-auto mb-3 text-green-300"/>
              <p className="text-slate-500">No LOP/Arrear issues found.</p>
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
