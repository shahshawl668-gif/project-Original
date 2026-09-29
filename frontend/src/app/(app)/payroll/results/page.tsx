"use client";

import { useEntity } from "@/context/EntityContext";
import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { EmptyState } from "@/components/ui/empty-state";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  inr, monthLabel, validationApi, OUTCOME_LABEL,
  type CoverageSummary, type EmployeePage, type ExposureSummary, type FindingPage, type Outcome,
  type RunEmployee, type ValidationRun,
} from "@/lib/validation";
import Link from "next/link";
import { Suspense, useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  BarChart, Bar, PieChart, Pie, Cell, XAxis, YAxis,
  Tooltip, ResponsiveContainer, Legend,
} from "recharts";
import {
  AlertTriangle, CheckCircle2, Users, XCircle, Search, ArrowRight, Shield, Flame,
  Activity, UploadCloud, TrendingUp, Download, History, GitCompare, RefreshCw,
  ChevronLeft, ChevronRight, HelpCircle, ListChecks,
} from "lucide-react";
import { toast } from "sonner";
import { IntegrationPanel } from "@/components/studio/IntegrationPanel";

type Tab = "overview" | "coverage" | "risk" | "findings" | "pf" | "esic" | "ptlwf" | "lop";
const TABS: Tab[] = ["overview", "coverage", "risk", "findings", "pf", "esic", "ptlwf", "lop"];
const PAGE_SIZE = 50;

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

function Pager({ page, pages, total, onPage }: { page: number; pages: number; total: number; onPage: (p: number) => void }) {
  if (pages <= 1) return <p className="text-xs text-ink-500">{total.toLocaleString("en-IN")} shown</p>;
  return (
    <div className="flex items-center justify-between gap-3 text-sm">
      <span className="text-ink-500">
        Page {page} of {pages} · {total.toLocaleString("en-IN")} total
      </span>
      <div className="flex gap-2">
        <Button type="button" variant="outline" disabled={page <= 1} onClick={() => onPage(page - 1)} aria-label="Previous page">
          <ChevronLeft size={15} />
        </Button>
        <Button type="button" variant="outline" disabled={page >= pages} onClick={() => onPage(page + 1)} aria-label="Next page">
          <ChevronRight size={15} />
        </Button>
      </div>
    </div>
  );
}

function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

const TABLE = "overflow-hidden rounded-2xl border border-ink-200/70 bg-white shadow-soft ring-1 ring-ink-900/[0.03] dark:border-white/[0.07] dark:bg-ink-900/70 dark:ring-white/[0.04]";
const THEAD = "bg-ink-50/80 text-[11px] uppercase tracking-[0.12em] text-ink-500 dark:bg-white/[0.03] dark:text-ink-300";
const INPUT = "w-full rounded-xl border border-ink-200 bg-white py-2.5 pl-9 pr-3 text-sm text-ink-900 shadow-sm outline-none ring-brand-500/20 placeholder:text-ink-400 focus-visible:ring-[3px] dark:border-white/10 dark:bg-white/[0.04] dark:text-white dark:placeholder:text-ink-500";

// ─── Employee table (server-paged) ───────────────────────────────────────────

function EmployeeTable({
  runId, mode,
}: { runId: string; mode: "overview" | "risk" | "pf" | "esic" | "ptlwf" | "unverifiable" }) {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [level, setLevel] = useState<"ALL" | "HIGH" | "MEDIUM" | "LOW">("ALL");
  const [data, setData] = useState<EmployeePage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const q = useDebounced(search);
  const computed = mode === "pf" || mode === "esic" || mode === "ptlwf" || mode === "risk";

  useEffect(() => { setPage(1); }, [q, level, runId]);
  useEffect(() => {
    let cancelled = false;
    setError(null);
    validationApi
      .employees(runId, {
        page, page_size: PAGE_SIZE, q, risk_level: level === "ALL" ? undefined : level,
        sort: mode === "overview" || mode === "risk" ? "risk_score" : "employee_id",
        order: mode === "overview" || mode === "risk" ? "desc" : "asc",
        include_computed: computed,
        only_unverifiable: mode === "unverifiable",
      })
      .then((d) => { if (!cancelled) setData(d); })
      .catch((err) => { if (!cancelled) setError(err instanceof Error ? err.message : "Could not load employees."); });
    return () => { cancelled = true; };
  }, [runId, page, q, level, mode, computed]);

  if (error) return <AlertBanner variant="error" title="Could not load employees">{error}</AlertBanner>;
  if (data && !data.employee_results_recorded) {
    return (
      <AlertBanner variant="info" title="Per-employee results were not recorded for this run">
        This run was made before per-employee results were kept. Its findings are still available on the Findings tab; revalidate the month to see employee detail.
      </AlertBanner>
    );
  }

  const rows = data?.items ?? [];
  const header: Record<typeof mode, string[]> = {
    overview: ["Emp ID", "Name", "Risk", "Score", "Failed checks", "Impact", ""],
    risk: ["Emp ID", "Name", "Risk level", "Score", "Breakdown", ""],
    pf: ["Emp ID", "Name", "PF wage", "Type", "PF (emp)", "PF (er)", "EPS", "EPF", "EDLI+admin"],
    esic: ["Emp ID", "Name", "ESIC wage", "Eligible?", "ESIC (emp)", "ESIC (er)"],
    ptlwf: ["Emp ID", "Name", "PT state", "PT due", "LWF state", "LWF (emp)", "LWF (er)"],
    unverifiable: ["Emp ID", "Name", "Could not validate", "Failed checks", ""],
  };

  const cells = (r: RunEmployee): ReactNode[] => {
    const c = r.computed;
    const link = (
      <Link
        href={`/payroll/employee/${encodeURIComponent(r.employee_id)}?run=${encodeURIComponent(runId)}`}
        className="inline-flex items-center gap-1 text-xs font-semibold text-brand-700 hover:text-brand-800 dark:text-brand-300"
      >
        Drilldown <ArrowRight size={12} />
      </Link>
    );
    switch (mode) {
      case "overview":
        return [
          r.employee_id, r.employee_name || "—", <RiskBadge key="r" level={r.risk_level} />, r.risk_score,
          r.failed_checks > 0 ? (
            <span key="f" className={`rounded-full px-2 py-0.5 text-xs font-semibold ${r.critical_count ? "bg-danger-100 text-danger-700" : "bg-warning-100 text-warning-700"}`}>
              {r.failed_checks} issue{r.failed_checks > 1 ? "s" : ""}
            </span>
          ) : r.cannot_validate_checks ? (
            <span key="f" className="rounded-full bg-warning-100 px-2 py-0.5 text-xs font-semibold text-warning-800" title="Nothing failed, but some checks could not be performed for want of an input.">
              No failures · {r.cannot_validate_checks} not checked
            </span>
          ) : (
            <span key="f" className="rounded-full bg-success-100 px-2 py-0.5 text-xs font-semibold text-success-700" title="No check failed. See the employee view for which checks ran.">
              No failures
            </span>
          ),
          r.financial_impact ? inr(r.financial_impact) : "—", link,
        ];
      case "risk":
        return [
          r.employee_id, r.employee_name || "—", <RiskBadge key="r" level={r.risk_level} />, r.risk_score,
          c?.score_breakdown ? Object.entries(c.score_breakdown).filter(([, v]) => v > 0).map(([k, v]) => `${k}: ${v}`).join(" · ") : "", link,
        ];
      case "pf":
        return [
          r.employee_id, r.employee_name || "—", fmt(c?.pf_wage), c?.pf_type ?? "–", fmt(c?.pf_amount_employee),
          fmt(c?.pf_amount_employer), fmt(c?.pf_breakup?.eps), fmt(c?.pf_breakup?.epf),
          fmt((c?.pf_breakup?.edli || 0) + (c?.pf_breakup?.admin || 0)),
        ];
      case "esic":
        return [
          r.employee_id, r.employee_name || "—", fmt(c?.esic_wage), c?.esic_eligible ? "Yes" : "Exempt",
          c?.esic_eligible ? fmt(c?.esic_employee) : "–", c?.esic_eligible ? fmt(c?.esic_employer) : "–",
        ];
      case "unverifiable":
        return [
          r.employee_id, r.employee_name || "—",
          <span key="c" className="font-semibold text-warning-700">{r.cannot_validate_checks ?? 0} check(s)</span>,
          r.failed_checks, link,
        ];
      case "ptlwf":
        return [
          r.employee_id, r.employee_name || "—", c?.pt_applicable_state || "–",
          c?.pt_due ? fmt(c.pt_due) : "nil", c?.lwf_applicable_state || "–",
          c?.lwf_employee ? fmt(c.lwf_employee) : "–", c?.lwf_employer ? fmt(c.lwf_employer) : "–",
        ];
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative min-w-48 flex-1">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
          <input className={INPUT} placeholder="Search employee ID or name…" value={search}
            onChange={(e) => setSearch(e.target.value)} aria-label="Search employees" />
        </div>
        {(mode === "risk" || mode === "overview") && (["ALL", "HIGH", "MEDIUM", "LOW"] as const).map((lvl) => (
          <button key={lvl} type="button" onClick={() => setLevel(lvl)}
            className={`rounded-lg px-3 py-1.5 text-xs font-semibold ${level === lvl ? "bg-ink-900 text-white dark:bg-white dark:text-ink-900" : "bg-ink-100 text-ink-600 hover:bg-ink-200"}`}>
            {lvl}{data?.risk_levels?.[lvl] != null ? ` (${data.risk_levels[lvl]})` : ""}
          </button>
        ))}
      </div>
      <div className={TABLE}>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className={THEAD}>
              <tr>{header[mode].map((h) => <th key={h} className="px-4 py-2.5 text-left font-semibold">{h}</th>)}</tr>
            </thead>
            <tbody className="divide-y divide-ink-100 dark:divide-white/[0.05]">
              {!data ? (
                <tr><td colSpan={header[mode].length} className="p-4"><Skeleton className="h-24 w-full" /></td></tr>
              ) : rows.length === 0 ? (
                <tr><td colSpan={header[mode].length} className="px-4 py-10 text-center text-ink-400">No employees match these filters.</td></tr>
              ) : rows.map((r) => (
                <tr key={r.employee_id} className="hover:bg-ink-50/60 dark:hover:bg-white/[0.04]">
                  {cells(r).map((cell, i) => (
                    <td key={i} className={`px-4 py-3 ${i === 0 ? "font-mono text-ink-600" : "text-ink-700 dark:text-ink-200"}`}>{cell}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      {data ? <Pager page={data.page} pages={data.pages} total={data.total} onPage={setPage} /> : null}
    </div>
  );
}

// ─── Findings list (server-paged) ────────────────────────────────────────────

function FindingsList({ runId, rulePrefix }: { runId: string; rulePrefix?: string }) {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [sev, setSev] = useState<"ALL" | "CRITICAL" | "WARNING" | "INFO">("ALL");
  const [rule, setRule] = useState("");
  const [data, setData] = useState<FindingPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const q = useDebounced(search);

  useEffect(() => { setPage(1); }, [q, sev, rule, runId, rulePrefix]);
  useEffect(() => {
    let cancelled = false;
    setError(null);
    validationApi
      .findings(runId, {
        page, page_size: PAGE_SIZE, q, severity: sev === "ALL" ? undefined : sev,
        rule_id: rule || undefined, rule_prefix: rulePrefix,
      })
      .then((d) => { if (!cancelled) setData(d); })
      .catch((err) => { if (!cancelled) setError(err instanceof Error ? err.message : "Could not load findings."); });
    return () => { cancelled = true; };
  }, [runId, page, q, sev, rule, rulePrefix]);

  if (error) return <AlertBanner variant="error" title="Could not load findings">{error}</AlertBanner>;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative min-w-48 flex-1">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
          <input className={INPUT} placeholder="Search rule or employee…" value={search}
            onChange={(e) => setSearch(e.target.value)} aria-label="Search findings" />
        </div>
        {(["ALL", "CRITICAL", "WARNING", "INFO"] as const).map((s) => (
          <button key={s} type="button" onClick={() => setSev(s)}
            className={`rounded-lg px-3 py-1.5 text-xs font-semibold ${sev === s ? "bg-ink-900 text-white dark:bg-white dark:text-ink-900" : "bg-ink-100 text-ink-600 hover:bg-ink-200"}`}>
            {s}
          </button>
        ))}
        {data?.rules?.length ? (
          <select className="rounded-lg border border-ink-200 bg-white px-2 py-1.5 text-xs" value={rule}
            onChange={(e) => setRule(e.target.value)} aria-label="Filter by rule">
            <option value="">All rules</option>
            {data.rules.map((r) => <option key={r.rule_id} value={r.rule_id}>{r.rule_id} · {r.rule_name} ({r.count})</option>)}
          </select>
        ) : null}
      </div>
      {!data ? <Skeleton className="h-40 w-full rounded-2xl" /> : data.items.length === 0 ? (
        <div className="py-12 text-center text-ink-500">
          <CheckCircle2 size={36} className="mx-auto mb-3 text-success-400" />
          No failed checks match these filters. This is not a statement that every check ran — see the employee view for coverage.
        </div>
      ) : (
        <div className="space-y-2">
          {data.items.map((f) => (
            <div key={f.id} className={`rounded-2xl border p-4 shadow-soft ${
              f.severity === "CRITICAL" ? "border-danger-200/80 bg-gradient-to-br from-danger-50 to-white"
                : f.severity === "WARNING" ? "border-warning-200/80 bg-gradient-to-br from-warning-50 to-white"
                  : "border-sky-200/80 bg-gradient-to-br from-sky-50 to-white"
            } dark:bg-none dark:bg-ink-900/60`}>
              <div className="mb-2 flex flex-wrap items-start justify-between gap-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className={`rounded px-2 py-0.5 font-mono text-xs font-semibold ${SEV_COLOR[f.severity]}`}>{f.rule_id}</span>
                  <span className={`rounded px-2 py-0.5 text-xs font-semibold ${SEV_COLOR[f.severity]}`}>{f.severity}</span>
                  <span className="text-sm font-semibold text-ink-800 dark:text-white">{f.rule_name}</span>
                  {f.was_waived ? <span className="rounded bg-ink-100 px-2 py-0.5 text-xs text-ink-600">waived</span> : null}
                  {f.occurrence_count && f.occurrence_count > 1 ? (
                    <span className="rounded bg-ink-100 px-2 py-0.5 text-xs text-ink-600">seen in {f.occurrence_count} months</span>
                  ) : null}
                </div>
                <Link href={`/payroll/employee/${encodeURIComponent(f.employee_id)}?run=${encodeURIComponent(runId)}`}
                  className="text-xs font-semibold text-brand-700 hover:text-brand-800 dark:text-brand-300">
                  {f.employee_id}{f.employee_name ? ` · ${f.employee_name}` : ""}
                </Link>
              </div>
              {f.reason ? <p className="mb-1.5 text-sm text-ink-700 dark:text-ink-200">{f.reason}</p> : null}
              <div className="mb-1.5 flex flex-wrap gap-4 text-xs text-ink-500">
                {f.expected_value ? <span>Expected: <strong className="text-ink-700 dark:text-ink-200">{f.expected_value}</strong></span> : null}
                {f.actual_value ? <span>Actual: <strong className="text-ink-700 dark:text-ink-200">{f.actual_value}</strong></span> : null}
                {f.difference && f.difference !== "0.00" ? <span>Diff: <strong className="text-ink-700 dark:text-ink-200">{f.difference}</strong></span> : null}
                {f.impact_calculated && f.financial_impact ? (
                  <span className="font-semibold text-danger-600">Impact: {inr(f.financial_impact, 2)}</span>
                ) : (
                  <span className="italic text-ink-500" title="This check does not price its effect; it is not a ₹0 finding.">Impact not calculated</span>
                )}
                <Link href={`/payroll/results/why?run=${encodeURIComponent(runId)}&finding=${encodeURIComponent(f.id)}`}
                  className="inline-flex items-center gap-1 font-semibold text-brand-700 hover:text-brand-800 dark:text-brand-300">
                  <HelpCircle size={12} /> Why this result?
                </Link>
              </div>
              {f.suggested_fix ? (
                <div className="mt-2 rounded-lg border border-brand-100 bg-brand-50/80 px-3 py-2 text-xs text-brand-950 dark:border-brand-500/30 dark:bg-brand-500/10 dark:text-brand-100">
                  <span className="font-semibold">Fix: </span>{f.suggested_fix}
                </div>
              ) : null}
            </div>
          ))}
        </div>
      )}
      {data ? <Pager page={data.page} pages={data.pages} total={data.total} onPage={setPage} /> : null}
    </div>
  );
}

// ─── Coverage ────────────────────────────────────────────────────────────────

const OUTCOME_TONE: Record<Outcome, string> = {
  passed: "text-success-700 dark:text-success-300",
  failed: "text-danger-700 dark:text-danger-300",
  cannot_validate: "text-warning-700 dark:text-warning-300",
  not_applicable: "text-ink-500 dark:text-ink-400",
  disabled: "text-ink-400 dark:text-ink-500",
};
const OUTCOMES: Outcome[] = ["passed", "failed", "cannot_validate", "not_applicable", "disabled"];

/** Coverage beside the failures, never merged into them: "no failures" means nothing if nothing ran. */
function CoverageHeadline({ coverage, onOpen }: { coverage: CoverageSummary | null; onOpen: () => void }) {
  if (!coverage) {
    return (
      <AlertBanner variant="info" title="Coverage was not recorded for this run">
        This run predates per-check outcomes. Revalidate the month to see which checks could and could not be performed.
      </AlertBanner>
    );
  }
  const material = coverage.material_cannot_validate;
  return (
    <div className={`flex flex-wrap items-center justify-between gap-3 rounded-2xl border px-4 py-3 text-sm ${
      material ? "border-warning-200/80 bg-warning-50/60 dark:border-warning-500/30 dark:bg-warning-500/10"
        : "border-ink-200/70 bg-white dark:border-white/[0.07] dark:bg-ink-900/60"}`}>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1">
        <span className="flex items-center gap-2 font-semibold text-ink-800 dark:text-white">
          <ListChecks size={16} className="text-brand-600" />
          Coverage {coverage.coverage_pct != null ? `${coverage.coverage_pct}%` : "—"}
        </span>
        {OUTCOMES.map((o) => (
          <span key={o} className={`text-xs ${OUTCOME_TONE[o]}`}>
            {OUTCOME_LABEL[o]}: <strong className="tabular-nums">{coverage.totals[o].toLocaleString("en-IN")}</strong>
          </span>
        ))}
      </div>
      <button type="button" onClick={onOpen} className="text-xs font-semibold text-brand-700 hover:underline dark:text-brand-300">
        {material ? `${material} statutory check(s) could not be performed — see why` : "See coverage by check"}
      </button>
    </div>
  );
}

function CoverageTab({ runId, coverage, exposure }: {
  runId: string; coverage: CoverageSummary | null; exposure: ExposureSummary | null;
}) {
  const [show, setShow] = useState<"gaps" | "all">("gaps");
  if (!coverage) return <CoverageHeadline coverage={null} onOpen={() => undefined} />;
  const rules = coverage.rules.filter((r) =>
    show === "all" ? true : r.counts.cannot_validate > 0 || r.counts.failed > 0);
  const missing = Object.entries(coverage.missing_inputs);
  return (
    <div className="space-y-6">
      <p className="max-w-3xl text-sm text-ink-600 dark:text-ink-300">
        Every check reaches one of five outcomes for every employee. <strong>Cannot validate</strong> means an input the
        check needs was not supplied — it is never counted as a pass. Coverage is the share of applicable checks that
        reached a verdict.
      </p>
      {missing.length ? (
        <div className="rounded-2xl border border-warning-200/80 bg-warning-50/60 p-4 dark:border-warning-500/30 dark:bg-warning-500/10">
          <h3 className="mb-2 text-sm font-semibold text-warning-900 dark:text-warning-100">Inputs that were missing</h3>
          <ul className="grid gap-1 text-xs text-warning-900 dark:text-warning-100 sm:grid-cols-2">
            {missing.map(([label, n]) => (
              <li key={label}><strong>{label}</strong> — missing for {n.toLocaleString("en-IN")} check(s)</li>
            ))}
          </ul>
        </div>
      ) : null}
      {exposure ? (
        <p className="text-xs text-ink-500 dark:text-ink-400">
          Exposure {inr(exposure.gross)} counts each underlying error once
          {exposure.overlap_excluded ? `; ${inr(exposure.overlap_excluded)} reported by overlapping checks was not added twice` : ""}
          {exposure.impact_not_calculated ? `; ${exposure.impact_not_calculated} finding(s) have no calculated impact and are not in the total` : ""}.
        </p>
      ) : null}
      <div className="flex gap-2">
        {(["gaps", "all"] as const).map((v) => (
          <button key={v} type="button" onClick={() => setShow(v)}
            className={`rounded-lg px-3 py-1.5 text-xs font-semibold ${show === v ? "bg-ink-900 text-white dark:bg-white dark:text-ink-900" : "bg-ink-100 text-ink-600 hover:bg-ink-200"}`}>
            {v === "gaps" ? "Checks with failures or gaps" : `All ${coverage.rules.length} checks`}
          </button>
        ))}
      </div>
      <div className={TABLE}>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className={THEAD}>
              <tr>
                <th className="px-4 py-2.5 text-left font-semibold">Check</th>
                {OUTCOMES.map((o) => <th key={o} className="px-3 py-2.5 text-right font-semibold">{OUTCOME_LABEL[o]}</th>)}
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-100 dark:divide-white/[0.05]">
              {rules.length === 0 ? (
                <tr><td colSpan={6} className="px-4 py-8 text-center text-ink-500">Every applicable check reached a verdict and none failed.</td></tr>
              ) : rules.map((r) => (
                <tr key={r.rule_id}>
                  <td className="px-4 py-2.5">
                    <span className="font-mono text-xs text-ink-500">{r.rule_id}</span>{" "}
                    <span className="text-ink-800 dark:text-ink-100">{r.name}</span>
                    {r.material ? <span className="ml-2 rounded bg-ink-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-ink-600 dark:bg-white/10 dark:text-ink-300">statutory</span> : null}
                    {!r.runs_in_validation ? <span className="ml-2 text-[11px] text-ink-400">runs outside validation</span> : null}
                  </td>
                  {OUTCOMES.map((o) => (
                    <td key={o} className={`px-3 py-2.5 text-right tabular-nums ${r.counts[o] ? OUTCOME_TONE[o] : "text-ink-300 dark:text-ink-600"}`}>
                      {r.counts[o].toLocaleString("en-IN")}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      {coverage.totals.cannot_validate > 0 ? (
        <div className="space-y-2">
          <h3 className="text-sm font-semibold text-ink-800 dark:text-white">Employees with checks that could not be performed</h3>
          <EmployeeTable runId={runId} mode="unverifiable" />
        </div>
      ) : null}
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

function PayrollResultsContent() {
  const { entity } = useEntity();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const runParam = searchParams.get("run");
  const [run, setRun] = useState<ValidationRun | null>(null);
  const [overview, setOverview] = useState<FindingPage | null>(null);
  const [levels, setLevels] = useState<Record<string, number>>({});
  const [state, setState] = useState<"loading" | "ready" | "none" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [exportBusy, setExportBusy] = useState(false);
  const [revalidating, setRevalidating] = useState(false);

  useEffect(() => {
    const t = searchParams.get("tab");
    if (t && TABS.includes(t as Tab)) setTab(t as Tab);
  }, [searchParams]);

  const load = useCallback(async () => {
    setState("loading");
    setRun(null);
    setOverview(null);
    try {
      let id = runParam;
      if (!id) {
        // No run named: open the most recent current run for this company.
        const latest = await validationApi.runs({ include_superseded: false, limit: 1 });
        if (!latest.length) { setState("none"); return; }
        id = latest[0].id;
        router.replace(`${pathname}?run=${encodeURIComponent(id)}`, { scroll: false });
      }
      const [r, f, e] = await Promise.all([
        validationApi.run(id),
        validationApi.findings(id, { page_size: 1 }),
        validationApi.employees(id, { page_size: 1 }),
      ]);
      setRun(r);
      setOverview(f);
      setLevels(e.risk_levels || {});
      setState("ready");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load this run.");
      setState("error");
    }
  }, [runParam, pathname, router]);

  // Re-load on company switch too: a run id from another company answers 404.
  useEffect(() => { void load(); }, [load, entity?.id]);

  const riskDist = useMemo(() => [
    { name: "HIGH", value: levels.HIGH || 0 },
    { name: "MEDIUM", value: levels.MEDIUM || 0 },
    { name: "LOW", value: levels.LOW || 0 },
  ], [levels]);
  const ruleTriggerData = useMemo(
    () => (overview?.rules || []).slice(0, 10).map((r) => ({ name: r.rule_id, count: r.count, severity: r.severity })),
    [overview],
  );

  const commitTab = (id: Tab) => {
    setTab(id);
    const p = new URLSearchParams(searchParams.toString());
    p.set("tab", id);
    router.replace(`${pathname}?${p.toString()}`, { scroll: false });
  };

  const download = async () => {
    if (!run) return;
    setExportBusy(true);
    try {
      const blob = await validationApi.exportRun(run.id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `validation-${run.period_month.slice(0, 7)}-run${run.run_number}.xlsx`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      toast.success("Workbook downloaded", { description: "Exactly as this run recorded it." });
    } catch (e) {
      toast.error("Export failed", { description: e instanceof Error ? e.message : "" });
    } finally {
      setExportBusy(false);
    }
  };

  const revalidate = async () => {
    if (!run) return;
    setRevalidating(true);
    try {
      const { job } = await validationApi.enqueue({ period_month: run.period_month, run_type: run.run_type || undefined });
      router.push(`/payroll/validation?job=${encodeURIComponent(job.id)}`);
    } catch (e) {
      toast.error("Could not start revalidation", { description: e instanceof Error ? e.message : "" });
      setRevalidating(false);
    }
  };

  if (state === "loading") {
    return (
      <div className="space-y-8">
        <Skeleton className="h-9 w-72" />
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 2xl:grid-cols-6">
          {Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-[5.5rem] rounded-2xl" />)}
        </div>
        <Skeleton className="h-[22rem] w-full rounded-2xl" />
      </div>
    );
  }

  if (state === "error") {
    return (
      <div className="space-y-6">
        <PageHeader title="Validation results" />
        <AlertBanner variant="error" title="This run could not be opened">
          {error} It may belong to another company, or the link may be wrong.{" "}
          <Link href="/payroll/results" className="font-semibold underline">Open the latest run</Link>
        </AlertBanner>
      </div>
    );
  }

  if (state === "none" || !run) {
    return (
      <div className="space-y-8">
        <PageHeader
          title="Validation results"
          description="Each validation is kept as a run on the server. Nothing has been validated for this company yet."
          actions={<Button asChild className="rounded-xl shadow-soft"><Link href="/payroll/upload" className="gap-2"><UploadCloud size={16} /> Upload & validate</Link></Button>}
        />
        <EmptyState
          icon={<Activity className="h-7 w-7 text-ink-400" strokeWidth={1.5} />}
          title="No validation runs yet"
          description="Upload a register and queue its validation. If one is already running, follow it from Validations."
          action={<Button asChild variant="outline"><Link href="/payroll/validation">Validations</Link></Button>}
        />
      </div>
    );
  }

  const fresh = run.freshness;
  const superseded = run.status === "superseded";
  const coverage = (run.summary?.coverage as CoverageSummary | undefined) ?? null;
  const exposure = (run.summary?.exposure as ExposureSummary | undefined) ?? null;
  const tabs: { id: Tab; label: string; badge?: number; badgeColor?: string }[] = [
    { id: "overview", label: "Overview" },
    { id: "coverage", label: "Coverage", badge: coverage?.material_cannot_validate || 0, badgeColor: "yellow" },
    { id: "risk", label: "Risk Scores", badge: levels.HIGH || 0, badgeColor: "red" },
    { id: "findings", label: "Findings", badge: run.total_findings, badgeColor: run.critical_count > 0 ? "red" : "yellow" },
    { id: "pf", label: "PF" },
    { id: "esic", label: "ESIC" },
    { id: "ptlwf", label: "PT / LWF" },
    { id: "lop", label: "LOP / Arrear" },
  ];

  return (
    <div className="space-y-8">
      <PageHeader
        title={`Validation results · ${monthLabel(run.period_month)}`}
        description={
          <>
            Run #{run.run_number} ({run.status}) · {run.employee_count.toLocaleString("en-IN")} employees ·{" "}
            {run.total_findings.toLocaleString("en-IN")} failed checks
            {run.upload ? ` · ${run.upload.filename ?? "register"} (upload ${run.upload.revision})` : ""}
            {run.finished_at ? ` · validated ${new Date(run.finished_at).toLocaleString("en-IN")}` : ""}
          </>
        }
        actions={
          <>
            <Button type="button" variant="outline" className="gap-2" disabled={exportBusy} onClick={() => void download()}>
              <Download size={15} /> {exportBusy ? "Working…" : "Excel"}
            </Button>
            {run.period_runs && run.period_runs.length > 1 ? (
              <Button variant="outline" asChild>
                <Link className="gap-2" href={`/payroll/runs/compare?base=${encodeURIComponent(
                  (run.period_runs.find((r) => r.run_number < run.run_number) ?? run.period_runs[run.period_runs.length - 1]).id,
                )}&target=${encodeURIComponent(run.id)}`}>
                  <GitCompare size={15} /> Compare
                </Link>
              </Button>
            ) : null}
            <Button variant="outline" asChild>
              <Link href="/payroll/issues" className="gap-2"><Shield size={15} /> Work the issues</Link>
            </Button>
            <Button variant="outline" asChild>
              <Link href="/payroll/upload" className="gap-2"><UploadCloud size={15} /> New run</Link>
            </Button>
          </>
        }
      />

      {superseded ? (
        <AlertBanner variant="info" title={`This is run #${run.run_number}, which has been superseded`}>
          It is kept exactly as it was reported.{" "}
          {run.superseded_by_run_id ? (
            <Link className="font-semibold underline" href={`/payroll/results?run=${encodeURIComponent(run.superseded_by_run_id)}`}>Open the run that replaced it</Link>
          ) : null}
        </AlertBanner>
      ) : fresh?.revalidation_required ? (
        <AlertBanner variant="warning" title="Revalidation required — inputs changed since this run">
          <ul className="mt-1 list-disc pl-5">
            {fresh.changes.map((c) => <li key={c.input}>{c.detail}</li>)}
          </ul>
          <Button type="button" className="mt-3 gap-2" disabled={revalidating} onClick={() => void revalidate()}>
            <RefreshCw size={15} /> {revalidating ? "Queuing…" : "Revalidate this month"}
          </Button>
        </AlertBanner>
      ) : null}

      {run.period_runs && run.period_runs.length > 1 ? (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <History size={14} className="text-ink-400" />
          <span className="text-ink-500">Runs for {monthLabel(run.period_month)}:</span>
          {run.period_runs.map((r) => (
            <Link key={r.id} href={`/payroll/results?run=${encodeURIComponent(r.id)}`}
              className={`rounded-full border px-2.5 py-1 font-semibold ${r.id === run.id ? "border-brand-400 bg-brand-50 text-brand-800" : "border-ink-200 text-ink-600 hover:bg-ink-50"}`}>
              #{r.run_number} · {r.total_findings} {r.status === "current" ? "· current" : ""}
            </Link>
          ))}
        </div>
      ) : null}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 2xl:grid-cols-6">
        <StatCard label="Employees" value={run.employee_count.toLocaleString("en-IN")} icon={<Users size={20} />} color="brand" />
        <StatCard label="Critical (open)" value={run.critical_count} icon={<XCircle size={20} />} color="red" />
        <StatCard label="Warnings (open)" value={run.warning_count} icon={<AlertTriangle size={20} />} color="yellow" />
        <StatCard label="High Risk" value={levels.HIGH || 0} icon={<Flame size={20} />} color="red" />
        <StatCard label="Failed checks" value={run.total_findings.toLocaleString("en-IN")} icon={<Shield size={20} />} color="blue" />
        <StatCard
          label="Open exposure"
          value={inr(run.open_financial_impact)}
          icon={<Activity size={20} />}
          color="blue"
          sub={`${inr(run.total_financial_impact)} before waivers${exposure?.impact_not_calculated ? ` · ${exposure.impact_not_calculated} not priced` : ""}`}
        />
      </div>

      <CoverageHeadline coverage={coverage} onOpen={() => commitTab("coverage")} />

      <IntegrationPanel period={run.period_month} />

      <div className="flex flex-wrap gap-1 rounded-2xl border border-ink-200/70 bg-ink-50/80 p-1.5 dark:border-white/10 dark:bg-white/[0.04]" role="tablist">
        {tabs.map((t) => (
          <button key={t.id} type="button" role="tab" aria-selected={tab === t.id} onClick={() => commitTab(t.id)}
            className={`flex items-center gap-1.5 whitespace-nowrap rounded-xl px-4 py-2.5 text-sm font-semibold transition-all ${
              tab === t.id ? "bg-white text-ink-900 shadow-soft ring-1 ring-ink-200/80 dark:bg-ink-900 dark:text-white"
                : "text-ink-600 hover:bg-white/70 hover:text-ink-900 dark:text-ink-300"}`}>
            {t.label}
            {t.badge != null && t.badge > 0 && (
              <span className={`rounded-full px-1.5 py-0.5 text-xs font-bold ${t.badgeColor === "red" ? "bg-danger-100 text-danger-700" : "bg-warning-100 text-warning-700"}`}>
                {t.badge.toLocaleString("en-IN")}
              </span>
            )}
          </button>
        ))}
      </div>

      {tab === "overview" && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <div className="rounded-2xl border border-ink-200/70 bg-white p-5 shadow-soft dark:border-white/[0.07] dark:bg-ink-900/70">
            <h3 className="mb-4 flex items-center gap-2 font-display text-base font-semibold text-ink-900 dark:text-white">
              <Shield size={16} className="text-brand-600" /> Risk distribution
            </h3>
            <ResponsiveContainer width="100%" height={220}>
              <PieChart>
                <Pie data={riskDist} cx="50%" cy="50%" outerRadius={80} dataKey="value" nameKey="name"
                  label={({ name, value }) => (Number(value) > 0 ? `${name}: ${value}` : "")}>
                  {riskDist.map((_, i) => <Cell key={i} fill={PIE_COLORS[i]} />)}
                </Pie>
                <Tooltip />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <div className="rounded-2xl border border-ink-200/70 bg-white p-5 shadow-soft dark:border-white/[0.07] dark:bg-ink-900/70">
            <h3 className="mb-4 flex items-center gap-2 font-display text-base font-semibold text-ink-900 dark:text-white">
              <TrendingUp size={16} className="text-brand-600" /> Top rule failures
            </h3>
            {ruleTriggerData.length === 0 ? (
              <p className="mt-8 text-center text-sm text-ink-500">
                No check failed in this run. Which checks ran, and which could not, is shown per employee.
              </p>
            ) : (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={ruleTriggerData} layout="vertical" margin={{ left: 20 }}>
                  <XAxis type="number" tick={{ fontSize: 11, fill: "currentColor" }} />
                  <YAxis dataKey="name" type="category" tick={{ fontSize: 11, fill: "currentColor" }} width={80} />
                  <Tooltip cursor={{ fill: "rgba(99,102,241,0.06)" }} />
                  <Bar dataKey="count" fill="#0284c7" radius={[0, 6, 6, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
          <div className="lg:col-span-2">
            <EmployeeTable runId={run.id} mode="overview" />
          </div>
        </div>
      )}
      {tab === "coverage" && <CoverageTab runId={run.id} coverage={coverage} exposure={exposure} />}
      {tab === "risk" && <EmployeeTable runId={run.id} mode="risk" />}
      {tab === "findings" && <FindingsList runId={run.id} />}
      {tab === "pf" && <EmployeeTable runId={run.id} mode="pf" />}
      {tab === "esic" && <EmployeeTable runId={run.id} mode="esic" />}
      {tab === "ptlwf" && <EmployeeTable runId={run.id} mode="ptlwf" />}
      {tab === "lop" && <FindingsList runId={run.id} rulePrefix="LOP,ATT,ARR,MOM,ADV,TDS" />}
    </div>
  );
}

function ResultsPageSkeleton() {
  return (
    <div className="space-y-8">
      <Skeleton className="h-9 w-72" />
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
