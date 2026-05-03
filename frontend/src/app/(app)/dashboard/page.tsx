"use client";

import { apiJson, getApiTargetDescription } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { AlertBanner } from "@/components/ui/alert-banner";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton, StatCardSkeleton } from "@/components/ui/skeleton";
import { Card, CardContent, CardDescription, CardTitle } from "@/components/ui/card";
import { KpiCard } from "@/components/ui/kpi-card";
import { SectionHeader } from "@/components/ui/section-header";
import Link from "next/link";
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
} from "recharts";
import {
  UploadCloud,
  Settings2,
  Layers,
  Users,
  ShieldCheck,
  Activity,
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  CalendarDays,
  ClipboardList,
  Inbox,
  Sparkles,
  TrendingUp,
  FileSpreadsheet,
  Calculator,
  ArrowUpRight,
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

const sparkData = (n: number) =>
  Array.from({ length: 12 }, (_, i) => Math.round((Math.sin(i / 1.6 + n) + 1) * 30 + 20 + i * 2));

export default function DashboardPage() {
  const { user } = useAuth();
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
      label: "Set statutory engine",
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
  const setupPct = (setupDone / setupSteps.length) * 100;

  const fmtMonth = (iso: string) =>
    new Date(iso + (iso.length === 7 ? "-01" : "")).toLocaleDateString("en-IN", {
      month: "short",
      year: "numeric",
    });
  const fmtDate = (iso: string) =>
    new Date(iso).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });

  const greeting = (() => {
    const h = new Date().getHours();
    if (h < 12) return "Good morning";
    if (h < 17) return "Good afternoon";
    return "Good evening";
  })();

  const userFirstName = user?.email?.split("@")[0]?.split(".")[0] || "there";
  const displayName = userFirstName.charAt(0).toUpperCase() + userFirstName.slice(1);

  const riskDist = useMemo(() => {
    return [
      { name: "HIGH", value: sessionRisk.filter((r) => r.risk_level === "HIGH").length, fill: "#ef4444" },
      { name: "MEDIUM", value: sessionRisk.filter((r) => r.risk_level === "MEDIUM").length, fill: "#f59e0b" },
      { name: "LOW", value: sessionRisk.filter((r) => r.risk_level === "LOW").length, fill: "#22c55e" },
    ].filter((d) => d.value > 0);
  }, [sessionRisk]);

  const topRules = useMemo(() => {
    const counts: Record<string, { id: string; name: string; n: number }> = {};
    sessionFindings
      .filter((f) => f.status === "FAIL")
      .forEach((f) => {
        if (!counts[f.rule_id]) counts[f.rule_id] = { id: f.rule_id, name: f.rule_name, n: 0 };
        counts[f.rule_id].n++;
      });
    return Object.values(counts)
      .sort((a, b) => b.n - a.n)
      .slice(0, 6)
      .map((c) => ({ name: c.id, count: c.n }));
  }, [sessionFindings]);

  return (
    <div className="space-y-9">
      {/* HERO */}
      <section className="relative overflow-hidden rounded-3xl border border-ink-200/70 bg-ink-950 text-white shadow-elevated">
        <div
          aria-hidden
          className="absolute inset-0"
          style={{
            background:
              "radial-gradient(ellipse 70% 60% at 12% 0%, rgba(124,58,237,0.55) 0%, transparent 55%), radial-gradient(ellipse 60% 50% at 90% 10%, rgba(59,130,246,0.55) 0%, transparent 55%), radial-gradient(ellipse 60% 60% at 65% 100%, rgba(236,72,153,0.45) 0%, transparent 55%)",
          }}
        />
        <div
          aria-hidden
          className="absolute inset-0 opacity-[0.07]"
          style={{
            backgroundImage:
              "url(\"data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E\")",
          }}
        />
        <div className="relative grid gap-8 p-7 lg:grid-cols-[1.4fr_1fr] lg:p-10">
          <div>
            <span className="inline-flex items-center gap-1.5 rounded-full border border-white/15 bg-white/10 px-3 py-1 text-[10px] font-bold uppercase tracking-[0.2em] text-white/85 backdrop-blur">
              <Sparkles size={11} className="text-pink-200" />
              FY 2025-26 ready
            </span>
            <h1 className="mt-4 font-display text-3xl font-bold leading-tight tracking-tightest text-white sm:text-4xl">
              {greeting}, {displayName}.
              <br />
              Your payroll, <span className="text-gradient bg-gradient-to-r from-pink-200 via-fuchsia-200 to-amber-100 bg-clip-text text-transparent">audit-ready.</span>
            </h1>
            <p className="mt-3 max-w-xl text-[14px] leading-relaxed text-white/75">
              Validate every register against PF, ESIC, PT, LWF, and Income Tax (old vs new regime).
              Catch mismatches before they hit the payslip.
            </p>
            <div className="mt-6 flex flex-wrap items-center gap-3">
              <Link
                href="/payroll/upload"
                className="group inline-flex h-11 items-center gap-2 rounded-xl bg-white px-5 text-sm font-semibold text-ink-900 shadow-[0_10px_32px_-8px_rgba(255,255,255,0.4)] transition-all hover:bg-ink-100"
              >
                <UploadCloud size={16} strokeWidth={2.25} />
                New validation run
                <ArrowUpRight
                  size={14}
                  className="transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5"
                />
              </Link>
              <Link
                href="/config/statutory"
                className="inline-flex h-11 items-center gap-2 rounded-xl border border-white/15 bg-white/[0.06] px-5 text-sm font-semibold text-white backdrop-blur transition-all hover:bg-white/10"
              >
                <Settings2 size={15} strokeWidth={2} />
                Configure rules
              </Link>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <HeroStat
              icon={<Users className="h-4 w-4" />}
              label="Last run employees"
              value={(localStats.total || stats?.last_run_employee_count || 0).toLocaleString("en-IN")}
              hint={stats?.last_run_at ? fmtDate(stats.last_run_at) : "No runs yet"}
            />
            <HeroStat
              icon={<ShieldCheck className="h-4 w-4" />}
              label="Statutory rules"
              value="38"
              hint="PF · ESIC · PT · LWF · IT"
            />
            <HeroStat
              icon={<TrendingUp className="h-4 w-4" />}
              label="Setup progress"
              value={`${setupDone}/${setupSteps.length}`}
              hint={`${Math.round(setupPct)}% configured`}
            />
            <HeroStat
              icon={<CalendarDays className="h-4 w-4" />}
              label="Last register"
              value={stats?.last_register_period ? fmtMonth(stats.last_register_period) : "—"}
              hint={`${registers.length} stored`}
            />
          </div>
        </div>
      </section>

      {apiError && (
        <AlertBanner variant="error" title="API connection issue">
          <span className="block">{apiError}</span>
          <span className="mt-2 block text-xs leading-relaxed">
            Effective routing:{" "}
            <code className="rounded-md bg-white/70 px-1.5 py-0.5 text-[11px] font-medium text-red-950">
              {getApiTargetDescription()}
            </code>
            . Set <code className="rounded bg-white/70 px-1 text-[11px]">BACKEND_URL=https://api.peopleopslab.in</code>{" "}
            on Vercel (server env, not NEXT_PUBLIC) and redeploy.
          </span>
        </AlertBanner>
      )}

      {/* KPI ROW */}
      <section aria-label="Key metrics" className="space-y-4">
        <SectionHeader
          eyebrow="Snapshot"
          title="Operational pulse"
          description="Live blend of your last validation session and stored registers."
          actions={
            loadingApi ? (
              <span className="inline-flex items-center gap-1.5 text-[11px] font-medium text-ink-500">
                <Activity size={12} className="animate-pulse text-brand-500" />
                Syncing…
              </span>
            ) : null
          }
        />
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
              <KpiCard
                icon={Users}
                tone="indigo"
                label="Employees in last run"
                value={localStats.total || stats?.last_run_employee_count || 0}
                hint={stats?.last_run_at ? `Run ${fmtDate(stats.last_run_at)}` : "No runs logged yet"}
                spark={sparkData(1)}
                trend={{ value: "+12%", direction: "up", label: "vs last month" }}
              />
              <KpiCard
                icon={ShieldCheck}
                tone="emerald"
                label="PF-linked employees"
                value={localStats.pfLinked}
                hint="Employees with PF wage captured"
                spark={sparkData(2)}
                trend={{ value: "+5%", direction: "up", label: "vs last run" }}
              />
              <KpiCard
                icon={TrendingUp}
                tone="sky"
                label="ESIC-eligible"
                value={localStats.esicEligible}
                hint="Under configured ESIC ceiling (₹21,000)"
                spark={sparkData(3)}
                trend={{ value: "Stable", direction: "flat" }}
              />
              <KpiCard
                icon={AlertTriangle}
                tone={localStats.errors > 0 ? "rose" : "slate"}
                label="Validation issues"
                value={localStats.errors}
                hint={
                  localStats.errors > 0
                    ? "From last validation in this session"
                    : "Clean run · no flags"
                }
                spark={sparkData(4)}
                trend={
                  localStats.errors > 0
                    ? { value: "Action", direction: "down", label: "review now" }
                    : { value: "All clear", direction: "up" }
                }
              />
            </>
          )}
        </div>
      </section>

      {/* ANALYTICS (only if local session data exists) */}
      {sessionFindings.length > 0 && (
        <section className="grid gap-5 lg:grid-cols-2" aria-label="Session analytics">
          {riskDist.length > 0 && (
            <Card className="overflow-hidden">
              <div className="border-b border-ink-100 p-5">
                <CardTitle className="text-base">Risk distribution</CardTitle>
                <CardDescription className="mt-1">From your last validation</CardDescription>
              </div>
              <CardContent className="pt-4">
                <ResponsiveContainer width="100%" height={210}>
                  <PieChart>
                    <Pie
                      data={riskDist}
                      cx="50%"
                      cy="50%"
                      outerRadius={75}
                      innerRadius={42}
                      dataKey="value"
                      nameKey="name"
                      paddingAngle={2}
                    >
                      {riskDist.map((d, i) => (
                        <Cell key={i} fill={d.fill} stroke="#fff" strokeWidth={2} />
                      ))}
                    </Pie>
                    <Tooltip />
                  </PieChart>
                </ResponsiveContainer>
                <div className="mt-2 flex justify-center gap-4 text-[11px]">
                  {riskDist.map((d) => (
                    <span key={d.name} className="inline-flex items-center gap-1.5 font-medium text-ink-700">
                      <span className="h-2 w-2 rounded-full" style={{ background: d.fill }} />
                      {d.name}: <span className="num">{d.value}</span>
                    </span>
                  ))}
                </div>
                <div className="mt-3 text-center">
                  <Link
                    href="/payroll/results?tab=risk"
                    className="inline-flex items-center gap-1 text-xs font-semibold text-brand-700 hover:text-brand-800"
                  >
                    Open risk table <ArrowRight size={12} />
                  </Link>
                </div>
              </CardContent>
            </Card>
          )}

          {topRules.length > 0 && (
            <Card className="overflow-hidden">
              <div className="border-b border-ink-100 p-5">
                <CardTitle className="text-base">Top rule violations</CardTitle>
                <CardDescription className="mt-1">Failed checks in the last session</CardDescription>
              </div>
              <CardContent className="pt-4">
                <ResponsiveContainer width="100%" height={210}>
                  <BarChart data={topRules} layout="vertical" margin={{ left: 8 }}>
                    <XAxis type="number" tick={{ fontSize: 11, fill: "#64748b" }} />
                    <YAxis dataKey="name" type="category" tick={{ fontSize: 11, fill: "#475569" }} width={72} />
                    <Tooltip cursor={{ fill: "rgba(99,102,241,0.06)" }} />
                    <Bar dataKey="count" fill="url(#barGrad)" radius={[0, 6, 6, 0]} />
                    <defs>
                      <linearGradient id="barGrad" x1="0" y1="0" x2="1" y2="0">
                        <stop offset="0%" stopColor="#6366f1" />
                        <stop offset="100%" stopColor="#a855f7" />
                      </linearGradient>
                    </defs>
                  </BarChart>
                </ResponsiveContainer>
                <div className="mt-3 text-center">
                  <Link
                    href="/payroll/results?tab=findings"
                    className="inline-flex items-center gap-1 text-xs font-semibold text-brand-700 hover:text-brand-800"
                  >
                    View all findings <ArrowRight size={12} />
                  </Link>
                </div>
              </CardContent>
            </Card>
          )}
        </section>
      )}

      {/* SETUP + REGISTERS */}
      <div className="grid gap-5 lg:grid-cols-3">
        <Card className="overflow-hidden lg:col-span-1">
          <div className="border-b border-ink-100 p-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <CardTitle className="text-base">Onboarding checklist</CardTitle>
                <CardDescription className="mt-1">
                  {setupDone} of {setupSteps.length} complete
                </CardDescription>
              </div>
              <div className="relative flex h-14 w-14 items-center justify-center">
                <svg viewBox="0 0 36 36" className="absolute h-14 w-14 -rotate-90">
                  <circle cx="18" cy="18" r="14" fill="none" stroke="#e2e8f0" strokeWidth="3" />
                  <circle
                    cx="18"
                    cy="18"
                    r="14"
                    fill="none"
                    stroke="url(#progressGrad)"
                    strokeWidth="3"
                    strokeDasharray={`${(setupDone / setupSteps.length) * 87.96} 87.96`}
                    strokeLinecap="round"
                  />
                  <defs>
                    <linearGradient id="progressGrad" x1="0" y1="0" x2="1" y2="1">
                      <stop offset="0%" stopColor="#6366f1" />
                      <stop offset="100%" stopColor="#a855f7" />
                    </linearGradient>
                  </defs>
                </svg>
                <span className="num relative text-xs font-bold text-ink-900">
                  {Math.round(setupPct)}%
                </span>
              </div>
            </div>
          </div>
          <div className="space-y-1 p-3">
            {setupSteps.map((step, i) => (
              <Link
                key={i}
                href={step.href}
                className={`group flex items-start gap-3 rounded-xl px-3 py-2.5 transition-colors hover:bg-ink-50 ${
                  step.done ? "opacity-60" : ""
                }`}
              >
                {step.done ? (
                  <CheckCircle2
                    size={18}
                    className="mt-0.5 shrink-0 text-success-500"
                    strokeWidth={2.25}
                  />
                ) : (
                  <div
                    className="mt-1 h-4 w-4 shrink-0 rounded-full border-2 border-ink-300 transition-colors group-hover:border-brand-500"
                    aria-hidden
                  />
                )}
                <div className="min-w-0 flex-1">
                  <p
                    className={`text-[13px] font-semibold ${
                      step.done ? "text-ink-400 line-through" : "text-ink-900"
                    }`}
                  >
                    {step.label}
                  </p>
                  <p className="mt-0.5 text-[11px] leading-relaxed text-ink-500">{step.desc}</p>
                </div>
                <ArrowRight
                  size={14}
                  className="mt-1 shrink-0 text-ink-300 transition-all group-hover:translate-x-0.5 group-hover:text-brand-500"
                />
              </Link>
            ))}
          </div>
        </Card>

        <Card className="overflow-hidden lg:col-span-2">
          <div className="flex items-center justify-between border-b border-ink-100 px-5 py-4">
            <div className="flex items-center gap-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-brand-50 to-accent-50 ring-1 ring-brand-100">
                <FileSpreadsheet size={16} className="text-brand-600" />
              </div>
              <div>
                <CardTitle className="text-base">Salary registers</CardTitle>
                <CardDescription className="mt-0.5">
                  {loadingApi ? "Loading…" : `${registers.length} stored`}
                </CardDescription>
              </div>
            </div>
            <Link
              href="/payroll/history"
              className="inline-flex items-center gap-1 text-xs font-semibold text-brand-700 hover:text-brand-800"
            >
              View all
              <ArrowRight size={12} />
            </Link>
          </div>
          {loadingApi ? (
            <div className="space-y-0 p-5">
              {[1, 2, 3].map((i) => (
                <div key={i} className="flex items-center gap-4 border-b border-ink-50 py-3 last:border-0">
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
                icon={<Inbox className="h-6 w-6 text-brand-500" />}
                title="No salary registers yet"
                description="Upload and validate a payroll file to store your first register for the period."
                action={
                  <Link
                    href="/payroll/upload"
                    className="inline-flex h-10 items-center gap-2 rounded-xl bg-gradient-to-br from-brand-600 to-accent-600 px-4 text-sm font-semibold text-white shadow-soft hover:shadow-glow"
                  >
                    <UploadCloud size={15} />
                    Upload payroll
                  </Link>
                }
                className="border-0 bg-transparent py-10"
              />
            </div>
          ) : (
            <ul className="divide-y divide-ink-100">
              {registers.slice(0, 6).map((reg) => (
                <li key={reg.id}>
                  <Link
                    href={`/payroll/history?id=${reg.id}`}
                    className="flex items-center gap-4 px-5 py-3.5 transition-colors hover:bg-ink-50/60"
                  >
                    <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-brand-50 to-accent-50 ring-1 ring-brand-100">
                      <CalendarDays size={17} className="text-brand-600" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="text-[13px] font-semibold text-ink-900">{fmtMonth(reg.period_month)}</p>
                      <p className="truncate text-xs text-ink-500">{reg.filename || "Manual upload"}</p>
                    </div>
                    <div className="text-right">
                      <p className="num text-sm font-bold text-ink-900">
                        {reg.employee_count ?? "—"}
                      </p>
                      <p className="text-[10px] font-medium uppercase tracking-wide text-ink-400">
                        employees
                      </p>
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      {/* RECENT RUNS + QUICK ACTIONS */}
      <div className="grid gap-5 lg:grid-cols-3">
        <Card className="overflow-hidden lg:col-span-2">
          <div className="flex items-center gap-3 border-b border-ink-100 px-5 py-4">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-ink-100">
              <ClipboardList size={16} className="text-ink-600" />
            </div>
            <CardTitle className="text-base">Recent payroll runs</CardTitle>
          </div>
          {loadingApi ? (
            <div className="space-y-3 p-5">
              <Skeleton className="h-9 w-full" />
              <Skeleton className="h-9 w-full" />
              <Skeleton className="h-9 w-3/4" />
            </div>
          ) : runs.length === 0 ? (
            <div className="p-5">
              <EmptyState
                icon={<ClipboardList className="h-6 w-6 text-brand-500" />}
                title="No runs recorded"
                description="Each upload creates a payroll run row you can correlate with validations."
                action={
                  <Link
                    href="/payroll/upload"
                    className="text-sm font-semibold text-brand-700 hover:text-brand-800"
                  >
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
                  <tr className="border-b border-ink-100 bg-ink-50/60 text-left text-[10px] font-bold uppercase tracking-wider text-ink-500">
                    <th className="whitespace-nowrap px-5 py-3">Type</th>
                    <th className="whitespace-nowrap px-5 py-3">File</th>
                    <th className="whitespace-nowrap px-5 py-3">Employees</th>
                    <th className="whitespace-nowrap px-5 py-3">Date</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-ink-100">
                  {runs.map((run) => (
                    <tr key={run.id} className="transition-colors hover:bg-ink-50/60">
                      <td className="px-5 py-3">
                        <RunTypeBadge type={run.run_type} />
                      </td>
                      <td className="max-w-[220px] truncate px-5 py-3 text-xs text-ink-600">
                        {run.filename || "—"}
                      </td>
                      <td className="num px-5 py-3 text-[13px] font-semibold text-ink-900">
                        {run.employee_count ?? "—"}
                      </td>
                      <td className="px-5 py-3 text-xs text-ink-500">{fmtDate(run.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <Card className="overflow-hidden">
          <div className="border-b border-ink-100 p-5">
            <CardTitle className="text-base">Quick actions</CardTitle>
            <CardDescription className="mt-1">Shortcuts to frequent workflows</CardDescription>
          </div>
          <div className="flex flex-col gap-2 p-4">
            <QuickAction
              href="/payroll/upload"
              icon={UploadCloud}
              label="Upload & validate payroll"
              primary
            />
            <QuickAction
              href="/config/statutory"
              icon={Settings2}
              label="Statutory configuration"
            />
            <QuickAction
              href="/config/components"
              icon={Layers}
              label="Salary components"
            />
            <QuickAction
              href="/rule-engine/slabs"
              icon={Calculator}
              label="PT / LWF slabs"
            />
          </div>
        </Card>
      </div>
    </div>
  );
}

function HeroStat({
  icon,
  label,
  value,
  hint,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  hint: string;
}) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.06] p-4 backdrop-blur transition-all hover:bg-white/[0.09]">
      <div className="flex items-center gap-2 text-white/60">
        {icon}
        <span className="text-[10px] font-bold uppercase tracking-wider">{label}</span>
      </div>
      <p className="num mt-2 font-display text-xl font-bold text-white">{value}</p>
      <p className="mt-0.5 text-[10px] text-white/55">{hint}</p>
    </div>
  );
}

function RunTypeBadge({ type }: { type: string }) {
  const styles =
    type === "arrear"
      ? "bg-warning-50 text-warning-700 ring-warning-200"
      : type === "increment_arrear"
        ? "bg-accent-50 text-accent-700 ring-accent-200"
        : "bg-brand-50 text-brand-700 ring-brand-200";
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wide capitalize ring-1 ${styles}`}
    >
      {type.replace("_", " ")}
    </span>
  );
}

function QuickAction({
  href,
  icon: Icon,
  label,
  primary,
}: {
  href: string;
  icon: typeof UploadCloud;
  label: string;
  primary?: boolean;
}) {
  return (
    <Link
      href={href}
      className={`group flex items-center gap-3 rounded-xl px-3.5 py-3 text-sm font-semibold transition-all ${
        primary
          ? "bg-gradient-to-br from-brand-600 to-accent-600 text-white shadow-soft hover:shadow-glow"
          : "border border-ink-200 bg-white text-ink-800 hover:border-ink-300 hover:bg-ink-50"
      }`}
    >
      <Icon size={16} strokeWidth={2.25} className={primary ? "text-white" : "text-ink-500"} />
      <span className="flex-1">{label}</span>
      <ArrowRight
        size={14}
        className={`transition-transform group-hover:translate-x-0.5 ${
          primary ? "text-white/80" : "text-ink-400"
        }`}
      />
    </Link>
  );
}
