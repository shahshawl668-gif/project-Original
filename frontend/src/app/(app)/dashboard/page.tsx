"use client";

import { apiFetch } from "@/lib/api";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, Tooltip, ResponsiveContainer, Legend,
} from "recharts";
import {
  UploadCloud,
  Settings2,
  Layers,
  TrendingUp,
  Users,
  ShieldCheck,
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Clock,
  CalendarDays,
  FileCheck2,
  BarChart3,
} from "lucide-react";

type DashboardStats = {
  components_configured: number;
  last_run_employee_count: number;
  last_run_at: string | null;
  last_register_period: string | null;
};

type LocalRow = {
  employee_id: string;
  pf_wage: number;
  esic_eligible: boolean;
  errors: string[];
  pt_due?: number;
  lwf_employee?: number;
};

type PayrollRun = {
  id: string;
  run_type: string;
  filename: string | null;
  employee_count: number | null;
  effective_month_from: string | null;
  effective_month_to: string | null;
  created_at: string;
};

type Register = {
  id: string;
  period_month: string;
  filename: string | null;
  employee_count: number | null;
  created_at: string;
};

export default function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [runs, setRuns] = useState<PayrollRun[]>([]);
  const [registers, setRegisters] = useState<Register[]>([]);
  const [localRows, setLocalRows] = useState<LocalRow[]>([]);
  const [sessionFindings, setSessionFindings] = useState<{severity:string;status:string;rule_id:string;rule_name:string}[]>([]);
  const [sessionRisk, setSessionRisk] = useState<{risk_level:string;risk_score:number}[]>([]);

  useEffect(() => {
    void apiFetch("/api/payroll/dashboard-stats").then((r) => { if (r.ok) void r.json().then(setStats); });
    void apiFetch("/api/payroll/runs?limit=5").then((r) => { if (r.ok) void r.json().then(setRuns); });
    void apiFetch("/api/payroll/registers").then((r) => { if (r.ok) void r.json().then(setRegisters); });
    try {
      const raw = sessionStorage.getItem("payroll_results");
      if (raw) setLocalRows(JSON.parse(raw) as LocalRow[]);
      const rf = sessionStorage.getItem("payroll_findings");
      if (rf) setSessionFindings(JSON.parse(rf));
      const rr = sessionStorage.getItem("payroll_risk_scores");
      if (rr) setSessionRisk(JSON.parse(rr));
    } catch { /* ignore */ }
  }, []);

  const localStats = useMemo(() => {
    const total = localRows.length;
    const pfLinked = localRows.filter((r) => r.pf_wage > 0).length;
    const esicEligible = localRows.filter((r) => r.esic_eligible).length;
    const errors = localRows.reduce((acc, r) => acc + (r.errors?.length || 0), 0);
    return { total, pfLinked, esicEligible, errors };
  }, [localRows]);

  const setupSteps = [
    {
      done: (stats?.components_configured ?? 0) > 0,
      label: "Configure salary components",
      href: "/config/components",
      desc: "Define Basic, HRA, and other pay heads",
    },
    {
      done: false, // can't check statutory from dashboard-stats yet
      label: "Set statutory settings",
      href: "/config/statutory",
      desc: "PF, ESIC rates and PT / LWF states",
    },
    {
      done: registers.length > 0,
      label: "Upload first salary register",
      href: "/payroll/upload",
      desc: "Validate and store a payroll run",
    },
    {
      done: false,
      label: "Upload CTC report",
      href: "/ctc/upload",
      desc: "Required for increment arrear validation",
    },
  ];
  const setupDone = setupSteps.filter((s) => s.done).length;

  const fmtMonth = (iso: string) =>
    new Date(iso + (iso.length === 7 ? "-01" : "")).toLocaleDateString("en-IN", {
      month: "short",
      year: "numeric",
    });

  const fmtDate = (iso: string) =>
    new Date(iso).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });

  const runTypeBadge = (t: string) => {
    if (t === "arrear") return "bg-amber-100 text-amber-800";
    if (t === "increment_arrear") return "bg-purple-100 text-purple-800";
    return "bg-brand-100 text-brand-800";
  };

  return (
    <div className="space-y-8 max-w-6xl">
      {/* Page header */}
      <div>
        <h1 className="text-2xl font-bold text-slate-900 tracking-tight">Dashboard</h1>
        <p className="text-slate-500 text-sm mt-1">Your payroll validation overview</p>
      </div>

      {/* Stat cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          icon={<Users size={20} className="text-brand-600" />}
          label="Employees (last run)"
          value={localStats.total || stats?.last_run_employee_count || 0}
          bg="bg-brand-50"
          sub={stats?.last_run_at ? `Run ${fmtDate(stats.last_run_at)}` : "No runs yet"}
        />
        <StatCard
          icon={<ShieldCheck size={20} className="text-success-600" />}
          label="PF-linked"
          value={localStats.pfLinked}
          bg="bg-success-50"
          sub="Employees with PF wage > 0"
        />
        <StatCard
          icon={<TrendingUp size={20} className="text-blue-600" />}
          label="ESIC-eligible"
          value={localStats.esicEligible}
          bg="bg-blue-50"
          sub="Wage ≤ ESIC ceiling"
        />
        <StatCard
          icon={<AlertTriangle size={20} className={localStats.errors > 0 ? "text-danger-600" : "text-slate-400"} />}
          label="Validation errors"
          value={localStats.errors}
          bg={localStats.errors > 0 ? "bg-danger-50" : "bg-slate-50"}
          sub={localStats.errors > 0 ? "From last session" : "Clean run"}
          highlight={localStats.errors > 0}
        />
      </div>

      {/* ── Intelligence Charts (only when session data present) ── */}
      {sessionFindings.length > 0 && (
        <div className="grid gap-5 sm:grid-cols-2">
          {/* Risk distribution */}
          {sessionRisk.length > 0 && (() => {
            const dist = [
              { name: "HIGH",   value: sessionRisk.filter(r=>r.risk_level==="HIGH").length,   fill: "#ef4444" },
              { name: "MEDIUM", value: sessionRisk.filter(r=>r.risk_level==="MEDIUM").length, fill: "#f59e0b" },
              { name: "LOW",    value: sessionRisk.filter(r=>r.risk_level==="LOW").length,    fill: "#22c55e" },
            ].filter(d => d.value > 0);
            return (
              <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
                <h3 className="text-sm font-semibold text-slate-800 mb-3">Risk Distribution</h3>
                <ResponsiveContainer width="100%" height={180}>
                  <PieChart>
                    <Pie data={dist} cx="50%" cy="50%" outerRadius={70} dataKey="value" nameKey="name"
                      label={({name,value}) => `${name}: ${value}`} labelLine={false}>
                      {dist.map((d,i) => <Cell key={i} fill={d.fill}/>)}
                    </Pie>
                    <Tooltip/>
                    <Legend/>
                  </PieChart>
                </ResponsiveContainer>
                <div className="mt-2 text-center">
                  <Link href="/payroll/results?tab=risk"
                    className="text-xs text-indigo-600 hover:text-indigo-800 font-medium">
                    View full risk table →
                  </Link>
                </div>
              </div>
            );
          })()}

          {/* Top rule failures */}
          {(() => {
            const counts: Record<string, {id:string;name:string;n:number}> = {};
            sessionFindings.filter(f=>f.status==="FAIL").forEach(f => {
              if (!counts[f.rule_id]) counts[f.rule_id] = {id:f.rule_id, name:f.rule_name, n:0};
              counts[f.rule_id].n++;
            });
            const top = Object.values(counts).sort((a,b)=>b.n-a.n).slice(0,6)
              .map(c => ({ name: c.id, count: c.n }));
            return top.length > 0 ? (
              <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
                <h3 className="text-sm font-semibold text-slate-800 mb-3">Top Rule Violations</h3>
                <ResponsiveContainer width="100%" height={180}>
                  <BarChart data={top} layout="vertical" margin={{left:10}}>
                    <XAxis type="number" tick={{fontSize:10}}/>
                    <YAxis dataKey="name" type="category" tick={{fontSize:10}} width={70}/>
                    <Tooltip/>
                    <Bar dataKey="count" fill="#6366f1" radius={[0,4,4,0]}/>
                  </BarChart>
                </ResponsiveContainer>
                <div className="mt-2 text-center">
                  <Link href="/payroll/results?tab=findings"
                    className="text-xs text-indigo-600 hover:text-indigo-800 font-medium">
                    View all findings →
                  </Link>
                </div>
              </div>
            ) : null;
          })()}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Setup checklist */}
        <div className="lg:col-span-1 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="font-semibold text-slate-900 text-sm">Setup checklist</h2>
              <p className="text-xs text-slate-500 mt-0.5">{setupDone} of {setupSteps.length} done</p>
            </div>
            <div className="w-10 h-10 rounded-full border-4 border-slate-100 flex items-center justify-center relative">
              <svg viewBox="0 0 36 36" className="w-10 h-10 -rotate-90 absolute">
                <circle cx="18" cy="18" r="14" fill="none" stroke="#e2e8f0" strokeWidth="3" />
                <circle
                  cx="18" cy="18" r="14" fill="none"
                  stroke="#4f46e5" strokeWidth="3"
                  strokeDasharray={`${(setupDone / setupSteps.length) * 87.96} 87.96`}
                  strokeLinecap="round"
                />
              </svg>
              <span className="text-xs font-bold text-slate-700 relative z-10">{setupDone}/{setupSteps.length}</span>
            </div>
          </div>
          <div className="space-y-2">
            {setupSteps.map((step, i) => (
              <Link
                key={i}
                href={step.href}
                className={`flex items-start gap-3 rounded-lg p-2.5 transition-colors hover:bg-slate-50 group ${step.done ? "opacity-70" : ""}`}
              >
                {step.done ? (
                  <CheckCircle2 size={16} className="text-success-600 mt-0.5 flex-shrink-0" />
                ) : (
                  <div className="w-4 h-4 rounded-full border-2 border-slate-300 mt-0.5 flex-shrink-0" />
                )}
                <div className="min-w-0 flex-1">
                  <p className={`text-xs font-medium ${step.done ? "line-through text-slate-400" : "text-slate-800"}`}>
                    {step.label}
                  </p>
                  <p className="text-[11px] text-slate-500 mt-0.5">{step.desc}</p>
                </div>
                <ArrowRight size={13} className="text-slate-300 group-hover:text-brand-500 mt-0.5 flex-shrink-0 transition-colors" />
              </Link>
            ))}
          </div>
        </div>

        {/* Recent registers */}
        <div className="lg:col-span-2 rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
          <div className="px-5 py-4 border-b border-slate-100 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Clock size={15} className="text-slate-400" />
            <h2 className="font-semibold text-slate-900 text-sm">Salary registers</h2>
              <span className="text-xs bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded-md font-medium">
                {registers.length}
              </span>
            </div>
            <Link
              href="/payroll/history"
              className="text-xs text-brand-600 hover:text-brand-700 font-medium flex items-center gap-1"
            >
              View all <ArrowRight size={12} />
            </Link>
          </div>
          {registers.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center px-6">
              <div className="w-12 h-12 rounded-xl bg-slate-100 flex items-center justify-center mb-3">
                <FileCheck2 size={22} className="text-slate-400" />
              </div>
              <p className="text-sm font-medium text-slate-700">No salary registers yet</p>
              <p className="text-xs text-slate-500 mt-1 max-w-[200px]">
                Upload and validate a payroll file to store a register.
              </p>
              <Link
                href="/payroll/upload"
                className="mt-4 rounded-lg bg-brand-600 px-4 py-2 text-xs font-medium text-white hover:bg-brand-700 transition-colors"
              >
                Upload payroll
              </Link>
            </div>
          ) : (
            <div>
              {registers.slice(0, 6).map((reg) => (
                <Link
                  key={reg.id}
                  href={`/payroll/history?id=${reg.id}`}
                  className="flex items-center gap-4 px-5 py-3 border-b border-slate-50 hover:bg-slate-50 transition-colors last:border-b-0"
                >
                  <div className="w-9 h-9 rounded-lg bg-brand-50 flex items-center justify-center flex-shrink-0">
                    <CalendarDays size={16} className="text-brand-600" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-slate-800">{fmtMonth(reg.period_month)}</p>
                    <p className="text-xs text-slate-500 truncate">{reg.filename || "Manual upload"}</p>
                  </div>
                  <div className="text-right flex-shrink-0">
                    <p className="text-sm font-semibold text-slate-900">{reg.employee_count ?? "—"}</p>
                    <p className="text-[11px] text-slate-400">employees</p>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Recent runs + Quick actions */}
      <div className="grid gap-6 lg:grid-cols-3">
        {/* Recent payroll runs */}
        <div className="lg:col-span-2 rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
          <div className="px-5 py-4 border-b border-slate-100 flex items-center gap-2">
            <Clock size={15} className="text-slate-400" />
            <h2 className="font-semibold text-slate-900 text-sm">Recent payroll runs</h2>
          </div>
          {runs.length === 0 ? (
            <div className="py-8 text-center text-sm text-slate-500">No runs yet.</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead>
                  <tr className="text-left text-xs font-medium text-slate-500 border-b border-slate-100 bg-slate-50/50">
                    <th className="px-5 py-2.5">Type</th>
                    <th className="px-5 py-2.5">File</th>
                    <th className="px-5 py-2.5">Employees</th>
                    <th className="px-5 py-2.5">Date</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.map((run) => (
                    <tr key={run.id} className="border-b border-slate-50 hover:bg-slate-50/50 last:border-b-0">
                      <td className="px-5 py-3">
                        <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${runTypeBadge(run.run_type)}`}>
                          {run.run_type.replace("_", " ")}
                        </span>
                      </td>
                      <td className="px-5 py-3 text-xs text-slate-600 max-w-[180px] truncate">
                        {run.filename || "—"}
                      </td>
                      <td className="px-5 py-3 font-medium text-slate-800">{run.employee_count ?? "—"}</td>
                      <td className="px-5 py-3 text-xs text-slate-500">{fmtDate(run.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Quick actions */}
        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm space-y-2">
          <h2 className="font-semibold text-slate-900 text-sm mb-3">Quick actions</h2>
          {[
            { href: "/payroll/upload", icon: UploadCloud, label: "Upload & validate payroll", color: "bg-brand-600 hover:bg-brand-700 text-white" },
            { href: "/config/statutory", icon: Settings2, label: "Edit statutory settings", color: "bg-white hover:bg-slate-50 text-slate-800 border border-slate-200" },
            { href: "/config/components", icon: Layers, label: "Manage salary components", color: "bg-white hover:bg-slate-50 text-slate-800 border border-slate-200" },
            { href: "/rule-engine/slabs", icon: BarChart3, label: "Configure PT / LWF slabs", color: "bg-white hover:bg-slate-50 text-slate-800 border border-slate-200" },
          ].map((a) => {
            const Icon = a.icon;
            return (
              <Link
                key={a.href}
                href={a.href}
                className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors ${a.color}`}
              >
                <Icon size={15} />
                {a.label}
              </Link>
            );
          })}
          {localRows.length > 0 && (
            <Link
              href="/payroll/results"
              className="flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium border border-amber-200 bg-amber-50 text-amber-800 hover:bg-amber-100 transition-colors"
            >
              <FileCheck2 size={15} />
              View last results ({localRows.length} rows)
            </Link>
          )}
        </div>
      </div>
    </div>
  );
}

function StatCard({
  icon, label, value, bg, sub, highlight = false,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
  bg: string;
  sub: string;
  highlight?: boolean;
}) {
  return (
    <div className={`rounded-xl border bg-white p-5 shadow-sm ${highlight ? "border-danger-200" : "border-slate-200"}`}>
      <div className="flex items-center justify-between mb-3">
        <div className={`w-9 h-9 rounded-lg ${bg} flex items-center justify-center`}>{icon}</div>
      </div>
      <p className={`text-3xl font-bold ${highlight ? "text-danger-600" : "text-slate-900"}`}>{value}</p>
      <p className="text-xs font-medium text-slate-600 mt-1">{label}</p>
      <p className="text-[11px] text-slate-400 mt-0.5">{sub}</p>
    </div>
  );
}

