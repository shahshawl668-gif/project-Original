"use client";

import { apiJson, getApiTargetDescription } from "@/lib/api";
import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton, StatCardSkeleton } from "@/components/ui/skeleton";
import { Card, CardContent, CardDescription, CardTitle } from "@/components/ui/card";
import Link from "next/link";
import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
import { useQueries } from "@tanstack/react-query";
import {
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Legend,
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
  ClipboardList,
  Inbox,
  Activity,
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
  const [localRows, setLocalRows] = useState<LocalRow[]>([]);
  const [sessionFindings, setSessionFindings] = useState<
    { severity: string; status: string; rule_id: string; rule_name: string }[]
  >([]);
  const [sessionRisk, setSessionRisk] = useState<{ risk_level: string; risk_score: number }[]>([]);

  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    setMounted(true);
  }, []);

  const results = useQueries({
    queries: [
      {
        queryKey: ["payroll", "dashboard-stats"],
        queryFn: () => apiJson<DashboardStats>("/api/payroll/dashboard-stats"),
        enabled: mounted,
      },
      {
        queryKey: ["payroll", "runs", 5],
        queryFn: () => apiJson<PayrollRun[]>("/api/payroll/runs?limit=5"),
        enabled: mounted,
      },
      {
        queryKey: ["payroll", "registers"],
        queryFn: () => apiJson<Register[]>("/api/payroll/registers"),
        enabled: mounted,
      },
    ],
  });

  const stats = results[0].data ?? null;
  const runs = results[1].data ?? [];
  const registers = results[2].data ?? [];
  const failed = results.find((q) => q.isError);
  const apiError = failed?.error instanceof Error ? failed.error.message : null;

  const loadingApi = results.some((q) => q.isPending);

  useEffect(() => {
    try {
      const raw = sessionStorage.getItem("payroll_results");
      if (raw) setLocalRows(JSON.parse(raw) as LocalRow[]);
      const rf = sessionStorage.getItem("payroll_findings");
      if (rf) setSessionFindings(JSON.parse(rf));
      const rr = sessionStorage.getItem("payroll_risk_scores");
      if (rr) setSessionRisk(JSON.parse(rr));
    } catch {
      /* ignore */
    }
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
      done: false,
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
    if (t === "arrear") return "bg-amber-100 text-amber-800 ring-1 ring-amber-200/80";
    if (t === "increment_arrear") return "bg-violet-100 text-violet-800 ring-1 ring-violet-200/80";
    return "bg-brand-50 text-brand-800 ring-1 ring-brand-200/80";
  };

  return (
    <div className="space-y-10">
      <PageHeader
        title="Dashboard"
        description="Overview of validations, payroll activity, and what to set up next."
        actions={
          <Link
            href="/payroll/upload"
            className="inline-flex h-10 items-center justify-center rounded-xl bg-brand-600 px-4 text-sm font-semibold text-white shadow-soft transition hover:bg-brand-700"
          >
            New validation run
          </Link>
        }
      />

      {apiError ? (
        <AlertBanner variant="error" title="Could not reach the API">
          <span className="block">{apiError}</span>
          <span className="mt-2 block text-sm">
            Effective routing:{" "}
            <code className="rounded-md bg-white/70 px-1.5 py-0.5 text-xs font-medium text-red-950">
              {getApiTargetDescription()}
            </code>
            . On{" "}
            <code className="rounded bg-white/70 px-1 text-xs">peopleopslab.in</code>, the app uses a
            same-origin proxy (<code className="rounded bg-white/70 px-1 text-xs">/api/proxy/*</code>).
            It also auto-falls back to direct API calls when the proxy returns a server connectivity error.
            Add server env{" "}
            <code className="rounded bg-white/70 px-1 text-xs">BACKEND_URL=https://api.peopleopslab.in</code>{" "}
            on Vercel (not NEXT_PUBLIC — mark for Production). Redeploy. Test{" "}
            <code className="rounded bg-white/70 px-1 text-xs">/api/proxy/api/health</code> on your site.
            To force browser→API directly:{" "}
            <code className="rounded bg-white/70 px-1 text-xs">NEXT_PUBLIC_DIRECT_API=1</code> plus{" "}
            <code className="rounded bg-white/70 px-1 text-xs">NEXT_PUBLIC_API_URL</code>.
          </span>
        </AlertBanner>
      ) : null}

      <section aria-label="Key metrics">
        <div className="mb-4 flex items-end justify-between gap-4">
          <div>
            <h2 className="text-sm font-semibold text-slate-900">Operational snapshot</h2>
            <p className="mt-1 text-xs text-slate-500">
              Figures blend your last uploaded session with server registers when listed.
            </p>
          </div>
          {loadingApi ? (
            <span className="flex items-center gap-2 text-2xs font-medium uppercase tracking-wide text-slate-400">
              <Activity size={13} className="animate-pulse" />
              Syncing…
            </span>
          ) : (
            stats?.last_register_period && (
              <span className="text-2xs font-medium uppercase tracking-wide text-slate-400">
                Last register · {fmtMonth(stats.last_register_period)}
              </span>
            )
          )}
        </div>
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {loadingApi ? (
            <>
              <StatCardSkeleton />
              <StatCardSkeleton />
              <StatCardSkeleton />
              <StatCardSkeleton />
            </>
          ) : (
            <>
              <MetricCard
                icon={<Users size={18} strokeWidth={2} className="text-brand-700" />}
                label="Employees (session / last run)"
                value={localStats.total || stats?.last_run_employee_count || 0}
                sub={stats?.last_run_at ? `Run ${fmtDate(stats.last_run_at)}` : "No runs logged yet"}
                tone="brand"
              />
              <MetricCard
                icon={<ShieldCheck size={18} strokeWidth={2} className="text-emerald-700" />}
                label="PF-linked"
                value={localStats.pfLinked}
                sub="Employees with PF wage captured"
                tone="emerald"
              />
              <MetricCard
                icon={<TrendingUp size={18} strokeWidth={2} className="text-sky-700" />}
                label="ESIC-eligible"
                value={localStats.esicEligible}
                sub="Under configured ESIC ceiling"
                tone="sky"
              />
              <MetricCard
                icon={
                  <AlertTriangle
                    size={18}
                    strokeWidth={2}
                    className={localStats.errors > 0 ? "text-red-600" : "text-slate-400"}
                  />
                }
                label="Validation issues"
                value={localStats.errors}
                sub={localStats.errors > 0 ? "From last session in browser" : "No issues in session"}
                tone={localStats.errors > 0 ? "danger" : "neutral"}
                highlight={localStats.errors > 0}
              />
            </>
          )}
        </div>
      </section>

      {sessionFindings.length > 0 && (
        <section className="grid gap-6 lg:grid-cols-2" aria-label="Session analytics">
          {sessionRisk.length > 0 &&
            (() => {
              const dist = [
                { name: "HIGH", value: sessionRisk.filter((r) => r.risk_level === "HIGH").length, fill: "#ef4444" },
                {
                  name: "MEDIUM",
                  value: sessionRisk.filter((r) => r.risk_level === "MEDIUM").length,
                  fill: "#f59e0b",
                },
                { name: "LOW", value: sessionRisk.filter((r) => r.risk_level === "LOW").length, fill: "#22c55e" },
              ].filter((d) => d.value > 0);
              return (
                <Card className="overflow-hidden">
                  <CardContent className="border-b border-slate-100 p-5">
                    <CardTitle className="text-base">Risk distribution</CardTitle>
                    <CardDescription className="mt-1">From your last validation in this browser</CardDescription>
                  </CardContent>
                  <CardContent className="p-5 pt-4">
                    <ResponsiveContainer width="100%" height={200}>
                      <PieChart>
                        <Pie
                          data={dist}
                          cx="50%"
                          cy="50%"
                          outerRadius={72}
                          dataKey="value"
                          nameKey="name"
                          label={({ name, value }) => `${name}: ${value}`}
                          labelLine={false}
                        >
                          {dist.map((d, i) => (
                            <Cell key={i} fill={d.fill} />
                          ))}
                        </Pie>
                        <Tooltip />
                        <Legend />
                      </PieChart>
                    </ResponsiveContainer>
                    <div className="mt-2 text-center">
                      <Link
                        href="/payroll/results?tab=risk"
                        className="text-xs font-semibold text-brand-700 hover:text-brand-800"
                      >
                        Open risk table →
                      </Link>
                    </div>
                  </CardContent>
                </Card>
              );
            })()}

          {(() => {
            const counts: Record<string, { id: string; name: string; n: number }> = {};
            sessionFindings
              .filter((f) => f.status === "FAIL")
              .forEach((f) => {
                if (!counts[f.rule_id]) counts[f.rule_id] = { id: f.rule_id, name: f.rule_name, n: 0 };
                counts[f.rule_id].n++;
              });
            const top = Object.values(counts)
              .sort((a, b) => b.n - a.n)
              .slice(0, 6)
              .map((c) => ({ name: c.id, count: c.n }));
            return top.length > 0 ? (
              <Card className="overflow-hidden">
                <CardContent className="border-b border-slate-100 p-5">
                  <CardTitle className="text-base">Top rule violations</CardTitle>
                  <CardDescription className="mt-1">Failed checks in the last session</CardDescription>
                </CardContent>
                <CardContent className="p-5 pt-4">
                  <ResponsiveContainer width="100%" height={200}>
                    <BarChart data={top} layout="vertical" margin={{ left: 8 }}>
                      <XAxis type="number" tick={{ fontSize: 11 }} />
                      <YAxis dataKey="name" type="category" tick={{ fontSize: 11 }} width={72} />
                      <Tooltip />
                      <Bar dataKey="count" fill="#6366f1" radius={[0, 6, 6, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                  <div className="mt-2 text-center">
                    <Link
                      href="/payroll/results?tab=findings"
                      className="text-xs font-semibold text-brand-700 hover:text-brand-800"
                    >
                      View all findings →
                    </Link>
                  </div>
                </CardContent>
              </Card>
            ) : null;
          })()}
        </section>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-1">
          <CardContent className="border-b border-slate-100 p-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <CardTitle className="text-base">Setup checklist</CardTitle>
                <CardDescription className="mt-1">
                  {setupDone} of {setupSteps.length} complete
                </CardDescription>
              </div>
              <div className="relative flex h-12 w-12 items-center justify-center">
                <svg viewBox="0 0 36 36" className="absolute h-12 w-12 -rotate-90">
                  <circle cx="18" cy="18" r="14" fill="none" stroke="#e2e8f0" strokeWidth="3" />
                  <circle
                    cx="18"
                    cy="18"
                    r="14"
                    fill="none"
                    stroke="#6366f1"
                    strokeWidth="3"
                    strokeDasharray={`${(setupDone / setupSteps.length) * 87.96} 87.96`}
                    strokeLinecap="round"
                  />
                </svg>
                <span className="relative text-2xs font-bold text-slate-800">
                  {setupDone}/{setupSteps.length}
                </span>
              </div>
            </div>
          </CardContent>
          <CardContent className="p-3">
            <div className="space-y-1">
              {setupSteps.map((step, i) => (
                <Link
                  key={i}
                  href={step.href}
                  className={`group flex items-start gap-3 rounded-xl px-3 py-2.5 transition-colors hover:bg-slate-50 ${
                    step.done ? "opacity-70" : ""
                  }`}
                >
                  {step.done ? (
                    <CheckCircle2 size={17} className="mt-0.5 shrink-0 text-emerald-600" aria-hidden />
                  ) : (
                    <div className="mt-0.5 h-4 w-4 shrink-0 rounded-full border-2 border-slate-300" aria-hidden />
                  )}
                  <div className="min-w-0 flex-1">
                    <p className={`text-sm font-medium ${step.done ? "text-slate-400 line-through" : "text-slate-900"}`}>
                      {step.label}
                    </p>
                    <p className="mt-0.5 text-xs leading-relaxed text-slate-500">{step.desc}</p>
                  </div>
                  <ArrowRight
                    size={14}
                    className="mt-1 shrink-0 text-slate-300 transition-colors group-hover:text-brand-500"
                    aria-hidden
                  />
                </Link>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card className="overflow-hidden lg:col-span-2">
          <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
            <div className="flex items-center gap-2.5">
              <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-slate-100">
                <Clock size={16} className="text-slate-600" />
              </div>
              <div>
                <CardTitle className="text-base">Salary registers</CardTitle>
                <CardDescription className="mt-0.5">
                  {loadingApi ? "Loading…" : `${registers.length} stored`}
                </CardDescription>
              </div>
            </div>
            <Link href="/payroll/history" className="text-sm font-semibold text-brand-700 hover:text-brand-800">
              View all
            </Link>
          </div>
          {loadingApi ? (
            <div className="space-y-0 border-t border-slate-50 p-5">
              {[1, 2, 3].map((i) => (
                <div key={i} className="flex items-center gap-4 border-b border-slate-50 py-3 last:border-0">
                  <Skeleton className="h-10 w-10 rounded-lg" />
                  <div className="flex-1 space-y-2">
                    <Skeleton className="h-4 w-32" />
                    <Skeleton className="h-3 w-48" />
                  </div>
                  <Skeleton className="h-6 w-12" />
                </div>
              ))}
            </div>
          ) : registers.length === 0 ? (
            <div className="p-5">
              <EmptyState
                icon={<Inbox className="h-6 w-6 text-slate-400" />}
                title="No salary registers yet"
                description="Upload and validate a payroll file to store a register for the selected period."
                action={
                  <Link
                    href="/payroll/upload"
                    className="inline-flex h-10 items-center rounded-xl bg-brand-600 px-4 text-sm font-semibold text-white hover:bg-brand-700"
                  >
                    Upload payroll
                  </Link>
                }
                className="border-0 bg-transparent py-10"
              />
            </div>
          ) : (
            <ul className="divide-y divide-slate-100">
              {registers.slice(0, 6).map((reg) => (
                <li key={reg.id}>
                  <Link
                    href={`/payroll/history?id=${reg.id}`}
                    className="flex items-center gap-4 px-5 py-3.5 transition-colors hover:bg-slate-50/80"
                  >
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-50 ring-1 ring-brand-600/10">
                      <CalendarDays size={17} className="text-brand-700" aria-hidden />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-semibold text-slate-900">{fmtMonth(reg.period_month)}</p>
                      <p className="truncate text-xs text-slate-500">{reg.filename || "Manual upload"}</p>
                    </div>
                    <div className="text-right">
                      <p className="text-sm font-semibold tabular-nums text-slate-900">{reg.employee_count ?? "—"}</p>
                      <p className="text-2xs font-medium uppercase tracking-wide text-slate-400">employees</p>
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="overflow-hidden lg:col-span-2">
          <div className="flex items-center gap-2.5 border-b border-slate-100 px-5 py-4">
            <ClipboardList size={17} className="text-slate-500" />
            <CardTitle className="text-base">Recent payroll runs</CardTitle>
          </div>
          {loadingApi ? (
            <div className="p-5">
              <Skeleton className="mb-4 h-8 w-full" />
              <Skeleton className="mb-4 h-8 w-full" />
              <Skeleton className="h-8 w-3/4" />
            </div>
          ) : runs.length === 0 ? (
            <div className="p-5">
              <EmptyState
                icon={<Clock className="h-6 w-6 text-slate-400" />}
                title="No runs recorded"
                description="Each upload creates a payroll run row you can correlate with validations."
                action={
                  <Link href="/payroll/upload" className="text-sm font-semibold text-brand-700 hover:text-brand-800">
                    Start an upload →
                  </Link>
                }
                className="border-0 bg-transparent py-8"
              />
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-100 bg-slate-50/70 text-left text-2xs font-semibold uppercase tracking-wide text-slate-500">
                    <th className="whitespace-nowrap px-5 py-3 font-semibold">Type</th>
                    <th className="whitespace-nowrap px-5 py-3 font-semibold">File</th>
                    <th className="whitespace-nowrap px-5 py-3 font-semibold">Employees</th>
                    <th className="whitespace-nowrap px-5 py-3 font-semibold">Date</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {runs.map((run) => (
                    <tr key={run.id} className="hover:bg-slate-50/80">
                      <td className="px-5 py-3">
                        <span
                          className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-2xs font-semibold capitalize ${runTypeBadge(run.run_type)}`}
                        >
                          {run.run_type.replace("_", " ")}
                        </span>
                      </td>
                      <td className="max-w-[200px] truncate px-5 py-3 text-xs text-slate-600">
                        {run.filename || "—"}
                      </td>
                      <td className="px-5 py-3 font-medium tabular-nums text-slate-900">{run.employee_count ?? "—"}</td>
                      <td className="px-5 py-3 text-xs text-slate-500">{fmtDate(run.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <Card>
          <CardContent className="border-b border-slate-100 p-5">
            <CardTitle className="text-base">Quick actions</CardTitle>
            <CardDescription className="mt-1">Shortcuts to frequent workflows</CardDescription>
          </CardContent>
          <CardContent className="flex flex-col gap-2 p-4">
            {[
              {
                href: "/payroll/upload",
                icon: UploadCloud,
                label: "Upload & validate payroll",
                primary: true,
              },
              { href: "/config/statutory", icon: Settings2, label: "Statutory configuration", primary: false },
              { href: "/config/components", icon: Layers, label: "Salary components", primary: false },
              { href: "/rule-engine/slabs", icon: BarChart3, label: "PT / LWF slabs", primary: false },
            ].map((a) => {
              const Icon = a.icon;
              return (
                <Link
                  key={a.href}
                  href={a.href}
                  className={`flex items-center gap-3 rounded-xl px-3 py-3 text-sm font-semibold transition-colors ${
                    a.primary
                      ? "bg-brand-600 text-white shadow-soft hover:bg-brand-700"
                      : "border border-slate-200 bg-white text-slate-800 hover:bg-slate-50"
                  }`}
                >
                  <Icon size={16} strokeWidth={2} />
                  {a.label}
                </Link>
              );
            })}
            {localRows.length > 0 ? (
              <Link
                href="/payroll/results"
                className="flex items-center gap-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-3 text-sm font-semibold text-amber-950 hover:bg-amber-100/90"
              >
                <FileCheck2 size={16} strokeWidth={2} />
                View session results ({localRows.length})
              </Link>
            ) : null}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

type Tone = "brand" | "emerald" | "sky" | "neutral" | "danger";

const toneClasses: Record<Tone, { ring: string; iconBg: string }> = {
  brand: {
    ring: "ring-brand-500/15",
    iconBg: "bg-brand-50",
  },
  emerald: {
    ring: "ring-emerald-500/15",
    iconBg: "bg-emerald-50",
  },
  sky: { ring: "ring-sky-500/15", iconBg: "bg-sky-50" },
  neutral: {
    ring: "ring-slate-500/10",
    iconBg: "bg-slate-100",
  },
  danger: {
    ring: "ring-red-500/15",
    iconBg: "bg-red-50",
  },
};

function MetricCard({
  icon,
  label,
  value,
  sub,
  tone,
  highlight,
}: {
  icon: ReactNode;
  label: string;
  value: number;
  sub: string;
  tone: Tone;
  highlight?: boolean;
}) {
  const t = toneClasses[tone];
  return (
    <div
      className={`rounded-2xl border bg-white p-5 shadow-soft ring-1 ${t.ring} ${
        highlight ? "border-red-200" : "border-slate-200/80"
      }`}
    >
      <div className={`mb-4 flex h-10 w-10 items-center justify-center rounded-xl ${t.iconBg}`}>{icon}</div>
      <p className={`text-3xl font-semibold tracking-tight tabular-nums ${highlight ? "text-red-600" : "text-slate-900"}`}>
        {value.toLocaleString("en-IN")}
      </p>
      <p className="mt-1 text-sm font-medium text-slate-700">{label}</p>
      <p className="mt-1 text-xs leading-snug text-slate-500">{sub}</p>
    </div>
  );
}
