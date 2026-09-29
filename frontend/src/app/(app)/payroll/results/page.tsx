"use client";

import Link from "next/link";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowRight, Download, GitCompare, HelpCircle, ListTodo, RefreshCw, Search, UploadCloud } from "lucide-react";

import { DataTable, FilterSelect, Pagination, type Column, type Sort } from "@/components/data/DataTable";
import { PageHeader } from "@/components/layout/PageHeader";
import { IntegrationPanel } from "@/components/studio/IntegrationPanel";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Drawer } from "@/components/ui/drawer";
import { EmptyState } from "@/components/ui/empty-state";
import { Stat } from "@/components/ui/kpi-card";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";
import { Tabs } from "@/components/ui/tabs";
import { useEntity } from "@/context/EntityContext";
import { saveBlob } from "@/lib/download";
import { count, dateTime, inr, pct, plural } from "@/lib/format";
import { cn } from "@/lib/utils";
import {
  monthLabel, validationApi, OUTCOME_LABEL,
  type CoverageSummary, type ExposureSummary, type Outcome, type RunEmployee, type RunFinding, type ValidationRun,
} from "@/lib/validation";
import { useAdoptPeriod } from "@/lib/workspace";

type Tab = "overview" | "findings" | "coverage" | "risk" | "pf" | "esic" | "ptlwf" | "lop";
const TABS: Tab[] = ["overview", "findings", "coverage", "risk", "pf", "esic", "ptlwf", "lop"];
const PAGE_SIZE = 50;

const SEVERITY_TONE: Record<string, "danger" | "warning" | "info"> = { CRITICAL: "danger", WARNING: "warning", INFO: "info" };
const SEVERITY_LABEL: Record<string, string> = { CRITICAL: "Critical", WARNING: "Warning", INFO: "Info" };
const STATE_LABEL: Record<string, string> = { open: "Open", acknowledged: "In progress", waived: "Waived", resolved: "Resolved" };
const RISK_TONE: Record<string, string> = { HIGH: "bg-danger-500", MEDIUM: "bg-warning-400", LOW: "bg-success-500" };
const RISK_LABEL: Record<string, string> = { HIGH: "High", MEDIUM: "Medium", LOW: "Low" };

function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

/** Filters live in the URL, so going back to the table finds it as it was left. */
function useUrlState() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const get = useCallback((k: string) => params.get(k) ?? "", [params]);
  const set = useCallback(
    (patch: Record<string, string | number | null>) => {
      const p = new URLSearchParams(params.toString());
      for (const [k, v] of Object.entries(patch)) {
        if (v === null || v === "" || v === undefined) p.delete(k);
        else p.set(k, String(v));
      }
      router.replace(`${pathname}?${p.toString()}`, { scroll: false });
    },
    [params, pathname, router],
  );
  return { get, set };
}

const money2 = (n: number | null | undefined) => inr(n, { digits: 2 });

function Impact({ f }: { f: Pick<RunFinding, "impact_calculated" | "financial_impact"> }) {
  return f.impact_calculated && f.financial_impact !== null ? (
    <span className="num">{inr(f.financial_impact)}</span>
  ) : (
    <span className="text-xs italic text-ink-400" title="This check does not price its effect. It is not a ₹0 finding.">Not calculated</span>
  );
}

// ─── Findings ────────────────────────────────────────────────────────────────

function FindingsView({ runId, rulePrefix, prefix = "f" }: { runId: string; rulePrefix?: string; prefix?: string }) {
  const url = useUrlState();
  const k = (s: string) => `${prefix}_${s}`;
  const [search, setSearch] = useState(url.get(k("q")));
  const q = useDebounced(search);
  const filters = {
    severity: url.get(k("sev")),
    rule_id: url.get(k("rule")),
    component: url.get(k("comp")),
    location: url.get(k("loc")),
    state: url.get(k("state")),
    owner: url.get(k("owner")),
  };
  const page = Number(url.get(k("page")) || 1);
  const view = url.get(k("view")) === "grouped" ? "grouped" : "list";
  const sort: Sort = { key: url.get(k("sort")) || "financial_impact", order: (url.get(k("order")) as "asc" | "desc") || "desc" };
  const [open, setOpen] = useState<RunFinding | null>(null);

  useEffect(() => {
    if (q !== url.get(k("q"))) url.set({ [k("q")]: q, [k("page")]: null });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);

  const query = useQuery({
    queryKey: ["run-findings", runId, rulePrefix, q, filters, page, sort],
    queryFn: () => validationApi.findings(runId, {
      page, page_size: PAGE_SIZE, q: q || undefined, rule_prefix: rulePrefix, sort: sort.key, order: sort.order,
      severity: filters.severity || undefined, rule_id: filters.rule_id || undefined, component: filters.component || undefined,
      location: filters.location || undefined, state: filters.state || undefined, owner: filters.owner || undefined,
    }),
    placeholderData: keepPreviousData,
  });
  const data = query.data;
  const active = Object.values(filters).some(Boolean) || !!q;
  const setFilter = (key: string, v: string) => url.set({ [k(key)]: v || null, [k("page")]: null });

  const columns: Column<RunFinding>[] = [
    {
      id: "employee", header: "Employee", pin: true, sortKey: "employee_id",
      cell: (f) => (
        <span className="block max-w-[12rem]">
          <span className="block font-mono text-xs text-ink-500">{f.employee_id}</span>
          <span className="block truncate text-ink-900">{f.employee_name || "—"}</span>
        </span>
      ),
    },
    {
      id: "check", header: "Check", sortKey: "rule_id",
      cell: (f) => (
        <span className="block max-w-[18rem]">
          <span className="font-mono text-xs text-ink-500">{f.rule_id}</span>{" "}
          <span className="text-ink-900">{f.rule_name}</span>
        </span>
      ),
    },
    {
      id: "severity", header: "Severity", sortKey: "severity",
      cell: (f) => <StatusPill tone={SEVERITY_TONE[f.severity] ?? "neutral"}>{SEVERITY_LABEL[f.severity] ?? f.severity}</StatusPill>,
    },
    { id: "component", header: "Component", hideable: true, cell: (f) => f.component ? <span className="text-ink-700">{f.component}</span> : <span className="text-ink-300">—</span> },
    { id: "actual", header: "Actual", numeric: true, hideable: true, cell: (f) => f.actual_value ?? <span className="text-ink-300">—</span> },
    { id: "expected", header: "Expected", numeric: true, hideable: true, cell: (f) => f.expected_value ?? <span className="text-ink-300">—</span> },
    { id: "difference", header: "Difference", numeric: true, hideable: true, cell: (f) => f.difference && f.difference !== "0.00" ? f.difference : <span className="text-ink-300">—</span> },
    { id: "impact", header: "Impact", numeric: true, sortKey: "financial_impact", cell: (f) => <Impact f={f} /> },
    {
      id: "state", header: "Review", hideable: true,
      cell: (f) => (
        <span className="whitespace-nowrap text-xs text-ink-600">
          {f.was_waived ? "Waived" : STATE_LABEL[f.state ?? "open"] ?? f.state}
          {f.occurrence_count && f.occurrence_count > 1 ? <span className="text-ink-400"> · {f.occurrence_count} months</span> : null}
        </span>
      ),
    },
    {
      id: "why", header: <span className="sr-only">Explanation</span>,
      cell: (f) => (
        <Link href={`/payroll/results/why?run=${encodeURIComponent(runId)}&finding=${encodeURIComponent(f.id)}`} className="inline-flex items-center gap-1 whitespace-nowrap text-xs font-medium text-brand-700 hover:underline">
          <HelpCircle size={12} aria-hidden /> Why?
        </Link>
      ),
    },
  ];

  const toolbar = (
    <>
      <div className="relative min-w-[12rem] flex-1 sm:max-w-xs">
        <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-400" aria-hidden />
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Employee or check"
          aria-label="Search findings by employee or check"
          className="h-8 w-full rounded-lg border border-ink-200 bg-white pl-8 pr-2 text-[13px] focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20"
        />
      </div>
      <FilterSelect label="Severity" allLabel="Any severity" value={filters.severity} onChange={(v) => setFilter("sev", v)}
        options={["CRITICAL", "WARNING", "INFO"].map((s) => ({ value: s, label: SEVERITY_LABEL[s] }))} />
      <FilterSelect label="Check" allLabel="Any check" value={filters.rule_id} onChange={(v) => setFilter("rule", v)}
        options={(data?.rules ?? []).map((r) => ({ value: r.rule_id, label: `${r.rule_id} · ${r.rule_name} (${r.count})` }))} />
      {data?.components?.length ? (
        <FilterSelect label="Component" allLabel="Any component" value={filters.component} onChange={(v) => setFilter("comp", v)}
          options={data.components.map((c) => ({ value: c.component, label: `${c.component} (${c.count})` }))} />
      ) : null}
      {data?.locations?.length ? (
        <FilterSelect label="Location" allLabel="Any location" value={filters.location} onChange={(v) => setFilter("loc", v)}
          options={data.locations.map((c) => ({ value: c.location, label: `${c.location} (${c.count})` }))} />
      ) : null}
      <FilterSelect label="Review state" allLabel="Any review state" value={filters.state} onChange={(v) => setFilter("state", v)}
        options={Object.entries(STATE_LABEL).map(([value, label]) => ({ value, label }))} />
      <FilterSelect label="Owner" allLabel="Any owner" value={filters.owner} onChange={(v) => setFilter("owner", v)}
        options={[{ value: "me", label: "Assigned to me" }, { value: "none", label: "Unassigned" }]} />
      {active ? (
        <button type="button" className="text-xs font-medium text-brand-700 hover:underline" onClick={() => {
          setSearch("");
          url.set({ [k("sev")]: null, [k("rule")]: null, [k("comp")]: null, [k("loc")]: null, [k("state")]: null, [k("owner")]: null, [k("q")]: null, [k("page")]: null });
        }}>Clear filters</button>
      ) : null}
      <div className="ml-auto flex rounded-lg border border-ink-200 p-0.5 text-xs" role="group" aria-label="Layout">
        {(["list", "grouped"] as const).map((v) => (
          <button key={v} type="button" aria-pressed={view === v} onClick={() => url.set({ [k("view")]: v === "list" ? null : v })}
            className={cn("rounded-md px-2 py-1", view === v ? "bg-ink-900 text-white" : "text-ink-600 hover:bg-ink-50")}>
            {v === "list" ? "Each finding" : "Grouped by check"}
          </button>
        ))}
      </div>
    </>
  );

  if (view === "grouped") {
    const groups = data?.rules ?? [];
    return (
      <div className="space-y-2">
        <DataTable
          id="run-findings-grouped"
          caption="Findings grouped by check"
          columns={[
            { id: "check", header: "Check", pin: true, cell: (r) => <span><span className="font-mono text-xs text-ink-500">{r.rule_id}</span> <span className="text-ink-900">{r.rule_name}</span></span> },
            { id: "severity", header: "Severity", cell: (r) => <StatusPill tone={SEVERITY_TONE[r.severity] ?? "neutral"}>{SEVERITY_LABEL[r.severity] ?? r.severity}</StatusPill> },
            { id: "count", header: "Findings", numeric: true, cell: (r) => count(r.count) },
            { id: "employees", header: "Employees", numeric: true, cell: (r) => count(r.employees ?? null) },
            { id: "impact", header: "Impact", numeric: true, cell: (r) => r.financial_impact === null || r.financial_impact === undefined ? <span className="text-xs italic text-ink-400">Not priced</span> : inr(r.financial_impact) },
            { id: "open", header: <span className="sr-only">Show</span>, cell: () => <span className="inline-flex items-center gap-1 text-xs font-medium text-brand-700">Show <ArrowRight size={12} aria-hidden /></span> },
          ]}
          rows={groups}
          rowKey={(r) => r.rule_id}
          loading={query.isLoading}
          refreshing={query.isFetching && !query.isLoading}
          onRowOpen={(r) => url.set({ [k("rule")]: r.rule_id, [k("view")]: null, [k("page")]: null })}
          rowLabel={(r) => `Show ${r.count} findings for ${r.rule_id} ${r.rule_name}`}
          toolbar={toolbar}
          empty="No check failed in this run. That is not a statement that every check ran — see Coverage."
          footer={<p className="text-xs text-ink-500">{plural(groups.length, "check")} with findings. Groups describe the whole run; filters other than the view apply to the list.</p>}
          minWidth="40rem"
        />
      </div>
    );
  }

  return (
    <>
      <DataTable
        id="run-findings"
        caption="Findings in this run"
        columns={columns}
        rows={data?.items}
        rowKey={(f) => f.id}
        loading={query.isLoading}
        refreshing={query.isFetching && !query.isLoading}
        error={query.isError ? <AlertBanner variant="error" title="Findings could not be loaded" details={(query.error as Error)?.message}>Try again in a moment.</AlertBanner> : undefined}
        onRowOpen={setOpen}
        rowLabel={(f) => `${f.rule_id} ${f.rule_name} for ${f.employee_name ?? f.employee_id}`}
        sort={sort}
        onSort={(s) => url.set({ [k("sort")]: s.key, [k("order")]: s.order, [k("page")]: null })}
        toolbar={toolbar}
        empty={active ? "No findings match these filters." : "No check failed in this run. That is not a statement that every check ran — see Coverage."}
        footer={data ? <Pagination page={data.page} pages={data.pages} total={data.total} pageSize={PAGE_SIZE} onPage={(p) => url.set({ [k("page")]: p })} noun="findings" /> : null}
        minWidth="64rem"
      />
      <FindingDrawer runId={runId} finding={open} onClose={() => setOpen(null)} />
    </>
  );
}

function FindingDrawer({ runId, finding: f, onClose }: { runId: string; finding: RunFinding | null; onClose: () => void }) {
  return (
    <Drawer
      open={!!f}
      onClose={onClose}
      title={f ? `${f.rule_id} · ${f.rule_name}` : ""}
      description={f ? `${f.employee_name ?? "—"} · ${f.employee_id}` : undefined}
      footer={f ? (
        <>
          <Button variant="outline" asChild><Link href={`/payroll/employee/${encodeURIComponent(f.employee_id)}?run=${encodeURIComponent(runId)}`}>Employee</Link></Button>
          <Button asChild><Link href={`/payroll/results/why?run=${encodeURIComponent(runId)}&finding=${encodeURIComponent(f.id)}`} data-autofocus>Why this result? <ArrowRight size={14} /></Link></Button>
        </>
      ) : null}
    >
      {f ? (
        <div className="space-y-4 text-[13px]">
          <div className="flex flex-wrap items-center gap-2">
            <StatusPill tone={SEVERITY_TONE[f.severity] ?? "neutral"}>{SEVERITY_LABEL[f.severity] ?? f.severity}</StatusPill>
            <Badge variant="secondary">{f.was_waived ? "Waived" : STATE_LABEL[f.state ?? "open"] ?? f.state}</Badge>
            {f.component ? <Badge variant="outline">{f.component}</Badge> : null}
            {f.occurrence_count && f.occurrence_count > 1 ? <span className="text-xs text-ink-500">Seen in {f.occurrence_count} months</span> : null}
          </div>
          {f.reason ? <p className="leading-relaxed text-ink-800">{f.reason}</p> : null}
          <dl className="grid grid-cols-2 gap-3 rounded-lg border border-ink-200 p-3">
            <div><dt className="text-xs text-ink-500">Actual</dt><dd className="num font-medium text-ink-900">{f.actual_value ?? "—"}</dd></div>
            <div><dt className="text-xs text-ink-500">Expected</dt><dd className="num font-medium text-ink-900">{f.expected_value ?? "—"}</dd></div>
            <div><dt className="text-xs text-ink-500">Difference</dt><dd className="num font-medium text-ink-900">{f.difference ?? "—"}</dd></div>
            <div><dt className="text-xs text-ink-500">Impact</dt><dd className="font-medium text-ink-900"><Impact f={f} /></dd></div>
          </dl>
          {f.suggested_fix ? (
            <div className="rounded-lg bg-brand-50 px-3 py-2.5 text-ink-800">
              <p className="text-xs font-medium text-brand-800">Suggested correction</p>
              <p className="mt-0.5 leading-relaxed">{f.suggested_fix}</p>
            </div>
          ) : null}
          <p className="text-xs text-ink-500">
            The full explanation shows the source row, the inputs, each calculation step, the tolerance, the rule version and the review history.
          </p>
        </div>
      ) : null}
    </Drawer>
  );
}

// ─── Employees ───────────────────────────────────────────────────────────────

type EmployeeMode = "overview" | "risk" | "pf" | "esic" | "ptlwf" | "unverifiable";

function EmployeeView({ runId, mode }: { runId: string; mode: EmployeeMode }) {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [level, setLevel] = useState<"" | "HIGH" | "MEDIUM" | "LOW">("");
  const [open, setOpen] = useState<RunEmployee | null>(null);
  const q = useDebounced(search);
  const computed = mode === "pf" || mode === "esic" || mode === "ptlwf" || mode === "risk";
  useEffect(() => setPage(1), [q, level, runId]);
  const query = useQuery({
    queryKey: ["run-employees", runId, mode, page, q, level],
    queryFn: () => validationApi.employees(runId, {
      page, page_size: PAGE_SIZE, q: q || undefined, risk_level: level || undefined,
      sort: mode === "overview" || mode === "risk" ? "risk_score" : "employee_id",
      order: mode === "overview" || mode === "risk" ? "desc" : "asc",
      include_computed: computed, only_unverifiable: mode === "unverifiable",
    }),
    placeholderData: keepPreviousData,
  });
  const data = query.data;

  if (data && !data.employee_results_recorded) {
    return (
      <AlertBanner variant="info" title="Per-employee results were not recorded for this run">
        This run was made before per-employee results were kept. Its findings are still on the Findings tab; revalidate the month to see employee detail.
      </AlertBanner>
    );
  }

  const identity: Column<RunEmployee> = {
    id: "employee", header: "Employee", pin: true,
    cell: (r) => (
      <span className="block max-w-[13rem]">
        <span className="block font-mono text-xs text-ink-500">{r.employee_id}</span>
        <span className="block truncate text-ink-900">{r.employee_name || "—"}</span>
      </span>
    ),
  };
  const risk: Column<RunEmployee> = {
    id: "risk", header: "Risk",
    cell: (r) => (
      <span className="inline-flex items-center gap-1.5 text-xs text-ink-700">
        <span className={cn("h-2 w-2 rounded-full", RISK_TONE[r.risk_level])} aria-hidden />
        {RISK_LABEL[r.risk_level]} <span className="num text-ink-400">{r.risk_score}</span>
      </span>
    ),
  };
  const c = (r: RunEmployee) => r.computed as (RunEmployee["computed"] & Record<string, unknown>) | undefined;
  const cols: Record<EmployeeMode, Column<RunEmployee>[]> = {
    overview: [
      identity, risk,
      { id: "dept", header: "Department", hideable: true, cell: (r) => r.department ?? <span className="text-ink-300">—</span> },
      { id: "loc", header: "Location", hideable: true, cell: (r) => r.work_state ?? <span className="text-ink-300">—</span> },
      {
        id: "checks", header: "Outcome",
        cell: (r) => r.failed_checks > 0 ? (
          <span className={cn("text-xs font-medium", r.critical_count ? "text-danger-700" : "text-warning-800")}>{plural(r.failed_checks, "failed check")}</span>
        ) : r.cannot_validate_checks ? (
          <span className="text-xs text-warning-800" title="Nothing failed, but some checks could not be performed for want of an input.">No failures · {r.cannot_validate_checks} not checked</span>
        ) : (
          <span className="text-xs text-ink-600" title="No check failed. The employee view shows which checks ran.">No failures</span>
        ),
      },
      { id: "gross", header: "Gross", numeric: true, hideable: true, cell: (r) => inr(r.gross) },
      { id: "net", header: "Net pay", numeric: true, hideable: true, defaultHidden: true, cell: (r) => inr(r.net_pay) },
      { id: "impact", header: "Impact", numeric: true, cell: (r) => r.financial_impact ? inr(r.financial_impact) : r.failed_checks ? <span className="text-xs italic text-ink-400">Not priced</span> : <span className="text-ink-300">—</span> },
    ],
    risk: [
      identity, risk,
      { id: "breakdown", header: "What drives the score", cell: (r) => <span className="text-xs text-ink-600">{r.computed && "score_breakdown" in r.computed ? Object.entries((r.computed as unknown as { score_breakdown: Record<string, number> }).score_breakdown).filter(([, v]) => v > 0).map(([k2, v]) => `${k2} ${v}`).join(" · ") || "—" : "—"}</span> },
    ],
    pf: [
      identity,
      { id: "wage", header: "PF wage", numeric: true, cell: (r) => money2(r.computed?.pf_wage) },
      { id: "type", header: "Type", cell: (r) => r.computed?.pf_type ?? "—" },
      { id: "emp", header: "Employee PF", numeric: true, cell: (r) => money2(r.computed?.pf_amount_employee) },
      { id: "er", header: "Employer PF", numeric: true, cell: (r) => money2(r.computed?.pf_amount_employer) },
      { id: "eps", header: "EPS", numeric: true, hideable: true, cell: (r) => money2(r.computed?.pf_breakup?.eps) },
      { id: "epf", header: "EPF", numeric: true, hideable: true, cell: (r) => money2(r.computed?.pf_breakup?.epf) },
      { id: "edli", header: "EDLI + admin", numeric: true, hideable: true, cell: (r) => r.computed?.pf_breakup ? money2(r.computed.pf_breakup.edli + r.computed.pf_breakup.admin) : "—" },
    ],
    esic: [
      identity,
      { id: "wage", header: "ESIC wage", numeric: true, cell: (r) => money2(c(r)?.esic_wage as number | null) },
      { id: "elig", header: "Covered", cell: (r) => (c(r)?.esic_eligible ? "Yes" : "Exempt") },
      { id: "emp", header: "Employee ESIC", numeric: true, cell: (r) => (c(r)?.esic_eligible ? money2(c(r)?.esic_employee as number | null) : "—") },
      { id: "er", header: "Employer ESIC", numeric: true, cell: (r) => (c(r)?.esic_eligible ? money2(c(r)?.esic_employer as number | null) : "—") },
    ],
    ptlwf: [
      identity,
      { id: "pts", header: "PT state", cell: (r) => (c(r)?.pt_applicable_state as string) || "—" },
      { id: "pt", header: "PT due", numeric: true, cell: (r) => (c(r)?.pt_due ? money2(c(r)?.pt_due as number) : "Nil") },
      { id: "lwfs", header: "LWF state", cell: (r) => (c(r)?.lwf_applicable_state as string) || "—" },
      { id: "lwfe", header: "LWF employee", numeric: true, cell: (r) => (c(r)?.lwf_employee ? money2(c(r)?.lwf_employee as number) : "—") },
      { id: "lwfr", header: "LWF employer", numeric: true, cell: (r) => (c(r)?.lwf_employer ? money2(c(r)?.lwf_employer as number) : "—") },
    ],
    unverifiable: [
      identity,
      { id: "cv", header: "Could not validate", numeric: true, cell: (r) => <span className="text-warning-800">{plural(r.cannot_validate_checks ?? 0, "check")}</span> },
      { id: "failed", header: "Failed", numeric: true, cell: (r) => count(r.failed_checks) },
    ],
  };

  return (
    <>
      <DataTable
        id={`run-employees-${mode}`}
        caption="Employees in this run"
        columns={cols[mode]}
        rows={data?.items}
        rowKey={(r) => r.employee_id}
        loading={query.isLoading}
        refreshing={query.isFetching && !query.isLoading}
        error={query.isError ? <AlertBanner variant="error" title="Employees could not be loaded" details={(query.error as Error)?.message}>Try again in a moment.</AlertBanner> : undefined}
        onRowOpen={setOpen}
        rowLabel={(r) => `${r.employee_name ?? ""} ${r.employee_id}`}
        toolbar={
          <>
            <div className="relative min-w-[12rem] flex-1 sm:max-w-xs">
              <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-400" aria-hidden />
              <input type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Employee ID or name" aria-label="Search employees"
                className="h-8 w-full rounded-lg border border-ink-200 bg-white pl-8 pr-2 text-[13px] focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20" />
            </div>
            {mode === "overview" || mode === "risk" ? (
              <FilterSelect label="Risk level" allLabel="Any risk" value={level} onChange={(v) => setLevel(v as typeof level)}
                options={(["HIGH", "MEDIUM", "LOW"] as const).map((l) => ({ value: l, label: `${RISK_LABEL[l]}${data?.risk_levels?.[l] != null ? ` (${data.risk_levels[l]})` : ""}` }))} />
            ) : null}
          </>
        }
        empty={q || level ? "No employees match these filters." : "No employees in this view."}
        footer={data ? <Pagination page={data.page} pages={data.pages} total={data.total} pageSize={PAGE_SIZE} onPage={setPage} noun="employees" /> : null}
      />
      <EmployeeDrawer runId={runId} employee={open} onClose={() => setOpen(null)} />
    </>
  );
}

function EmployeeDrawer({ runId, employee, onClose }: { runId: string; employee: RunEmployee | null; onClose: () => void }) {
  const findings = useQuery({
    queryKey: ["run-findings", runId, "employee", employee?.employee_id],
    queryFn: () => validationApi.findings(runId, { employee_id: employee!.employee_id, page_size: 20 }),
    enabled: !!employee,
  });
  const e = employee;
  return (
    <Drawer
      open={!!e}
      onClose={onClose}
      title={e ? e.employee_name || e.employee_id : ""}
      description={e ? [e.employee_id, e.department, e.work_state].filter(Boolean).join(" · ") : undefined}
      footer={e ? <Button asChild><Link href={`/payroll/employee/${encodeURIComponent(e.employee_id)}?run=${encodeURIComponent(runId)}`} data-autofocus>Full employee view <ArrowRight size={14} /></Link></Button> : null}
    >
      {e ? (
        <div className="space-y-4 text-[13px]">
          <dl className="grid grid-cols-2 gap-3 rounded-lg border border-ink-200 p-3">
            <div><dt className="text-xs text-ink-500">Gross</dt><dd className="num font-medium">{inr(e.gross)}</dd></div>
            <div><dt className="text-xs text-ink-500">Net pay</dt><dd className="num font-medium">{inr(e.net_pay)}</dd></div>
            <div><dt className="text-xs text-ink-500">Checks passed</dt><dd className="num font-medium">{count(e.passed_checks)}</dd></div>
            <div><dt className="text-xs text-ink-500">Could not validate</dt><dd className="num font-medium">{count(e.cannot_validate_checks)}</dd></div>
            <div><dt className="text-xs text-ink-500">Failed</dt><dd className="num font-medium">{count(e.failed_checks)}</dd></div>
            <div><dt className="text-xs text-ink-500">Risk</dt><dd className="font-medium">{RISK_LABEL[e.risk_level]} · <span className="num">{e.risk_score}</span></dd></div>
          </dl>
          <div>
            <p className="mb-1.5 text-xs font-medium text-ink-500">Findings</p>
            {findings.isLoading ? <Skeleton className="h-16 w-full" /> : findings.data?.items.length ? (
              <ul className="divide-y divide-ink-100 rounded-lg border border-ink-200">
                {findings.data.items.map((f) => (
                  <li key={f.id} className="px-3 py-2">
                    <div className="flex items-center gap-2">
                      <StatusPill tone={SEVERITY_TONE[f.severity] ?? "neutral"}>{SEVERITY_LABEL[f.severity]}</StatusPill>
                      <span className="min-w-0 flex-1 truncate text-ink-900">{f.rule_name}</span>
                      <Link className="text-xs font-medium text-brand-700 hover:underline" href={`/payroll/results/why?run=${encodeURIComponent(runId)}&finding=${encodeURIComponent(f.id)}`}>Why?</Link>
                    </div>
                    <p className="mt-0.5 text-xs text-ink-500">Actual {f.actual_value ?? "—"} · expected {f.expected_value ?? "—"} · <Impact f={f} /></p>
                  </li>
                ))}
              </ul>
            ) : <p className="text-xs text-ink-500">No failed checks for this employee. The full view lists which checks ran and which could not.</p>}
          </div>
        </div>
      ) : null}
    </Drawer>
  );
}

// ─── Coverage ────────────────────────────────────────────────────────────────

const OUTCOMES: Outcome[] = ["passed", "failed", "cannot_validate", "not_applicable", "disabled"];
const OUTCOME_BAR: Record<Outcome, string> = {
  passed: "bg-success-500", failed: "bg-danger-500", cannot_validate: "bg-warning-400", not_applicable: "bg-ink-200", disabled: "bg-ink-100",
};
const OUTCOME_TEXT: Record<Outcome, string> = {
  passed: "text-success-700", failed: "text-danger-700", cannot_validate: "text-warning-800", not_applicable: "text-ink-500", disabled: "text-ink-400",
};

/** Outcomes beside the issues, never merged into them: "no failures" means nothing if nothing ran. */
function OutcomeStrip({ coverage, onOpen }: { coverage: CoverageSummary | null; onOpen: () => void }) {
  if (!coverage) {
    return (
      <AlertBanner variant="info" title="Coverage was not recorded for this run">
        This run predates per-check outcomes. Revalidate the month to see which checks could and could not be performed.
      </AlertBanner>
    );
  }
  const sum = OUTCOMES.reduce((a, o) => a + coverage.totals[o], 0) || 1;
  const material = coverage.material_cannot_validate;
  return (
    <section aria-label="Check outcomes" className={cn("rounded-xl border bg-white px-4 py-3 shadow-soft", material ? "border-warning-200" : "border-ink-200")}>
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
        <div>
          <p className="text-xs text-ink-500">Coverage</p>
          <p className="num text-lg font-semibold text-ink-900">{pct(coverage.coverage_pct)}</p>
        </div>
        <div className="min-w-[14rem] flex-1">
          <div className="flex h-2 overflow-hidden rounded-full bg-ink-100" aria-hidden>
            {OUTCOMES.map((o) => (coverage.totals[o] ? <div key={o} className={OUTCOME_BAR[o]} style={{ width: `${(coverage.totals[o] / sum) * 100}%` }} /> : null))}
          </div>
          <dl className="mt-1.5 flex flex-wrap gap-x-4 gap-y-0.5 text-xs">
            {OUTCOMES.map((o) => (
              <div key={o} className="flex items-center gap-1.5">
                <span className={cn("h-2 w-2 rounded-sm", OUTCOME_BAR[o])} aria-hidden />
                <dt className="text-ink-500">{OUTCOME_LABEL[o]}</dt>
                <dd className={cn("num font-medium", OUTCOME_TEXT[o])}>{count(coverage.totals[o])}</dd>
              </div>
            ))}
          </dl>
        </div>
        <button type="button" onClick={onOpen} className="text-xs font-medium text-brand-700 hover:underline">
          {material ? `${plural(material, "statutory check")} could not be performed — see why` : "Coverage by check"}
        </button>
      </div>
    </section>
  );
}

function CoverageTab({ runId, coverage, exposure }: { runId: string; coverage: CoverageSummary | null; exposure: ExposureSummary | null }) {
  const [show, setShow] = useState<"gaps" | "all">("gaps");
  if (!coverage) return <OutcomeStrip coverage={null} onOpen={() => undefined} />;
  const rules = coverage.rules.filter((r) => (show === "all" ? true : r.counts.cannot_validate > 0 || r.counts.failed > 0));
  const missing = Object.entries(coverage.missing_inputs);
  return (
    <div className="space-y-4">
      <p className="max-w-3xl text-[13px] leading-relaxed text-ink-600">
        Every check reaches one of five outcomes for every employee. <b>Cannot validate</b> means an input the check needs was not supplied — it is never counted as a pass. Coverage is the share of applicable checks that reached a verdict.
      </p>
      {missing.length ? (
        <div className="rounded-xl border border-warning-200 bg-warning-50 p-4">
          <h3 className="text-[13px] font-semibold text-warning-900">Inputs that were missing</h3>
          <ul className="mt-1.5 grid gap-1 text-xs text-warning-900 sm:grid-cols-2">
            {missing.map(([label, n]) => <li key={label}><b>{label}</b> — missing for {plural(n, "check")}</li>)}
          </ul>
        </div>
      ) : null}
      {exposure ? (
        <p className="text-xs text-ink-500">
          Exposure {inr(exposure.gross)} counts each underlying error once
          {exposure.overlap_excluded ? `; ${inr(exposure.overlap_excluded)} reported by overlapping checks was not added twice` : ""}
          {exposure.impact_not_calculated ? `; ${plural(exposure.impact_not_calculated, "finding")} have no calculated impact and are not in the total` : ""}.
        </p>
      ) : null}
      <DataTable
        id="coverage-by-check"
        caption="Outcomes by check"
        columns={[
          {
            id: "check", header: "Check", pin: true,
            cell: (r) => (
              <span>
                <span className="font-mono text-xs text-ink-500">{r.rule_id}</span> <span className="text-ink-900">{r.name}</span>
                {r.material ? <Badge variant="secondary" className="ml-2">Statutory</Badge> : null}
                {!r.runs_in_validation ? <span className="ml-2 text-xs text-ink-400">runs outside validation</span> : null}
              </span>
            ),
          },
          ...OUTCOMES.map((o) => ({
            id: o, header: OUTCOME_LABEL[o], numeric: true,
            cell: (r: CoverageSummary["rules"][number]) => <span className={r.counts[o] ? OUTCOME_TEXT[o] : "text-ink-300"}>{count(r.counts[o])}</span>,
          })),
        ]}
        rows={rules}
        rowKey={(r) => r.rule_id}
        toolbar={
          <div className="flex rounded-lg border border-ink-200 p-0.5 text-xs" role="group" aria-label="Show checks">
            {(["gaps", "all"] as const).map((v) => (
              <button key={v} type="button" aria-pressed={show === v} onClick={() => setShow(v)}
                className={cn("rounded-md px-2 py-1", show === v ? "bg-ink-900 text-white" : "text-ink-600 hover:bg-ink-50")}>
                {v === "gaps" ? "Failures or gaps" : `All ${coverage.rules.length} checks`}
              </button>
            ))}
          </div>
        }
        empty="Every applicable check reached a verdict and none failed."
        minWidth="56rem"
        maxHeight="32rem"
      />
      {coverage.totals.cannot_validate > 0 ? (
        <div className="space-y-2">
          <h3 className="text-[13px] font-semibold text-ink-900">Employees with checks that could not be performed</h3>
          <EmployeeView runId={runId} mode="unverifiable" />
        </div>
      ) : null}
    </div>
  );
}

// ─── Overview charts (no chart library: two bars do not need one) ────────────

function RiskBar({ levels }: { levels: Record<string, number> }) {
  const order = ["HIGH", "MEDIUM", "LOW"];
  const total = order.reduce((a, l) => a + (levels[l] || 0), 0);
  return (
    <section className="rounded-xl border border-ink-200 bg-white p-4 shadow-soft" aria-labelledby="risk-h">
      <h3 id="risk-h" className="text-[13px] font-semibold text-ink-900">Risk distribution</h3>
      <p className="text-xs text-ink-500">Employees in this run, by risk level</p>
      {total === 0 ? <p className="mt-4 text-xs text-ink-500">No employee results recorded.</p> : (
        <>
          <div className="mt-3 flex h-2.5 overflow-hidden rounded-full bg-ink-100" aria-hidden>
            {order.map((l) => (levels[l] ? <div key={l} className={RISK_TONE[l]} style={{ width: `${(levels[l] / total) * 100}%` }} /> : null))}
          </div>
          <dl className="mt-3 grid grid-cols-3 gap-2">
            {order.map((l) => (
              <div key={l}>
                <dt className="flex items-center gap-1.5 text-xs text-ink-500"><span className={cn("h-2 w-2 rounded-full", RISK_TONE[l])} aria-hidden />{RISK_LABEL[l]}</dt>
                <dd className="num text-lg font-semibold text-ink-900">{count(levels[l] || 0)}</dd>
              </div>
            ))}
          </dl>
        </>
      )}
    </section>
  );
}

function TopChecks({ rules, onPick }: { rules: { rule_id: string; rule_name: string; count: number; severity: string }[]; onPick: (rule: string) => void }) {
  const top = rules.slice(0, 6);
  const max = Math.max(1, ...top.map((r) => r.count));
  return (
    <section className="rounded-xl border border-ink-200 bg-white p-4 shadow-soft" aria-labelledby="top-h">
      <h3 id="top-h" className="text-[13px] font-semibold text-ink-900">Most frequent failures</h3>
      <p className="text-xs text-ink-500">Findings per check in this run</p>
      {top.length === 0 ? <p className="mt-4 text-xs text-ink-500">No check failed in this run. Which checks ran is on the Coverage tab.</p> : (
        <ul className="mt-3 space-y-1.5">
          {top.map((r) => (
            <li key={r.rule_id}>
              <button type="button" onClick={() => onPick(r.rule_id)} className="group w-full text-left" aria-label={`${r.rule_id} ${r.rule_name}: ${r.count} findings. Show them`}>
                <div className="flex items-baseline justify-between gap-3 text-xs">
                  <span className="truncate text-ink-700 group-hover:text-ink-900"><span className="font-mono text-ink-500">{r.rule_id}</span> {r.rule_name}</span>
                  <span className="num font-medium text-ink-900">{count(r.count)}</span>
                </div>
                <div className="mt-1 h-1.5 rounded-full bg-ink-100">
                  <div className={cn("h-full rounded-full", r.severity === "CRITICAL" ? "bg-danger-500" : r.severity === "WARNING" ? "bg-warning-400" : "bg-brand-400")} style={{ width: `${(r.count / max) * 100}%` }} />
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ─── Page ────────────────────────────────────────────────────────────────────

function PayrollResultsContent() {
  const { entity, activeRole } = useEntity();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const url = useUrlState();
  const runParam = searchParams.get("run");
  const tabParam = searchParams.get("tab") as Tab | null;
  const tab: Tab = tabParam && TABS.includes(tabParam) ? tabParam : "overview";
  const [exportBusy, setExportBusy] = useState(false);
  const [revalidating, setRevalidating] = useState(false);

  // No run named: open the most recent current run for this company.
  const latest = useQuery({
    queryKey: ["latest-current-run", entity?.id],
    queryFn: () => validationApi.runs({ include_superseded: false, limit: 1 }),
    enabled: !runParam && !!entity,
  });
  useEffect(() => {
    if (!runParam && latest.data?.length) {
      // Keep whatever else the link asked for (a tab, a filter).
      const p = new URLSearchParams(searchParams.toString());
      p.set("run", latest.data[0].id);
      router.replace(`${pathname}?${p.toString()}`, { scroll: false });
    }
  }, [runParam, latest.data, pathname, router, searchParams]);

  const runQ = useQuery({ queryKey: ["run", runParam], queryFn: () => validationApi.run(runParam!), enabled: !!runParam, retry: false });
  const summaryQ = useQuery({ queryKey: ["run-findings-summary", runParam], queryFn: () => validationApi.findings(runParam!, { page_size: 1 }), enabled: !!runParam });
  const levelsQ = useQuery({ queryKey: ["run-levels", runParam], queryFn: () => validationApi.employees(runParam!, { page_size: 1 }), enabled: !!runParam });
  const run: ValidationRun | undefined = runQ.data;
  useAdoptPeriod(run?.period_month);

  const levels = useMemo(() => levelsQ.data?.risk_levels ?? {}, [levelsQ.data]);
  const setTab = (id: string) => url.set({ tab: id === "overview" ? null : id });

  const download = async () => {
    if (!run) return;
    setExportBusy(true);
    try {
      saveBlob(await validationApi.exportRun(run.id), `validation-${run.period_month.slice(0, 7)}-run${run.run_number}.xlsx`);
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

  if (!runParam && latest.data && latest.data.length === 0) {
    return (
      <div className="space-y-5">
        <PageHeader title="Validation results" description="Each validation is kept as a run on the server. Nothing has been validated for this company yet." />
        <EmptyState
          title="No validation runs yet"
          description="Upload a register and queue its validation. If one is already running, follow it from Validation runs."
          action={<div className="flex gap-2"><Button asChild><Link href="/payroll/upload"><UploadCloud size={14} /> Upload a register</Link></Button><Button asChild variant="outline"><Link href="/payroll/validation">Validation runs</Link></Button></div>}
        />
      </div>
    );
  }

  if (runQ.isError || latest.isError) {
    return (
      <div className="space-y-5">
        <PageHeader title="Validation results" />
        <AlertBanner variant="error" title="This run could not be opened" details={((runQ.error ?? latest.error) as Error)?.message}>
          It may belong to another company, or the link may be wrong. <Link href="/payroll/results" className="font-medium underline">Open the latest run</Link>
        </AlertBanner>
      </div>
    );
  }

  if (!run) {
    return (
      <div className="space-y-5">
        <Skeleton className="h-8 w-80" />
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-24 rounded-xl" />)}</div>
        <Skeleton className="h-16 w-full rounded-xl" />
        <Skeleton className="h-80 w-full rounded-xl" />
      </div>
    );
  }

  const fresh = run.freshness;
  const superseded = run.status === "superseded";
  const coverage = (run.summary?.coverage as CoverageSummary | undefined) ?? null;
  const exposure = (run.summary?.exposure as ExposureSummary | undefined) ?? null;
  const previous = run.period_runs?.find((r) => r.run_number < run.run_number) ?? null;
  const runLink = (extra: string) => `/payroll/results?run=${encodeURIComponent(run.id)}${extra}`;

  return (
    <div className="space-y-5">
      <PageHeader
        title={`${monthLabel(run.period_month)} · run ${run.run_number}`}
        description={
          <>
            {plural(run.employee_count, "employee")}
            {run.upload ? <> · {run.upload.filename ?? "register"} (revision {run.upload.revision})</> : null}
            {run.finished_at ? <> · validated {dateTime(run.finished_at)}</> : null}
            {run.engine_version ? <> · engine {run.engine_version}</> : null}
          </>
        }
        meta={
          <>
            <StatusPill tone={superseded ? "neutral" : fresh?.revalidation_required ? "warning" : "info"}>
              {superseded ? "Superseded" : fresh?.revalidation_required ? "Current · out of date" : "Current run"}
            </StatusPill>
            {run.period_runs && run.period_runs.length > 1 ? (
              <nav aria-label="Runs for this month" className="flex flex-wrap items-center gap-1">
                {run.period_runs.map((r) => (
                  <Link key={r.id} href={`/payroll/results?run=${encodeURIComponent(r.id)}${tab !== "overview" ? `&tab=${tab}` : ""}`}
                    aria-current={r.id === run.id ? "page" : undefined}
                    className={cn("num rounded-md border px-1.5 py-0.5 text-xs", r.id === run.id ? "border-brand-300 bg-brand-50 text-brand-800" : "border-ink-200 text-ink-600 hover:bg-ink-50")}>
                    Run {r.run_number} · {count(r.total_findings)}
                  </Link>
                ))}
              </nav>
            ) : null}
          </>
        }
        actions={
          <>
            <Button variant="outline" disabled={exportBusy} onClick={() => void download()}><Download size={14} /> {exportBusy ? "Preparing…" : "Excel"}</Button>
            {previous ? (
              <Button variant="outline" asChild>
                <Link href={`/payroll/runs/compare?base=${encodeURIComponent(previous.id)}&target=${encodeURIComponent(run.id)}`}><GitCompare size={14} /> Compare with run {previous.run_number}</Link>
              </Button>
            ) : null}
            <Button asChild><Link href="/payroll/issues"><ListTodo size={14} /> Work the issues</Link></Button>
          </>
        }
      />

      {superseded ? (
        <AlertBanner variant="info" title={`Run ${run.run_number} has been superseded`}>
          It is kept exactly as it was reported.{" "}
          {run.superseded_by_run_id ? <Link className="font-medium underline" href={`/payroll/results?run=${encodeURIComponent(run.superseded_by_run_id)}`}>Open the run that replaced it</Link> : null}
        </AlertBanner>
      ) : fresh?.revalidation_required ? (
        <AlertBanner
          variant="warning"
          title="Inputs changed since this run — its results no longer describe the month"
          action={activeRole !== "viewer" ? <Button size="sm" disabled={revalidating} onClick={() => void revalidate()}><RefreshCw size={13} /> {revalidating ? "Queuing…" : "Revalidate"}</Button> : null}
        >
          <ul className="list-disc pl-4">{fresh.changes.map((c) => <li key={c.input}>{c.detail}</li>)}</ul>
        </AlertBanner>
      ) : null}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        <Stat label="Employees" value={run.employee_count} qualifier="in this run" />
        <Stat label="Critical, open" value={run.critical_count} tone={run.critical_count ? "danger" : "neutral"} qualifier="after waivers" href={runLink("&tab=findings&f_sev=CRITICAL")} />
        <Stat label="Warnings, open" value={run.warning_count} tone={run.warning_count ? "warning" : "neutral"} qualifier="after waivers" href={runLink("&tab=findings&f_sev=WARNING")} />
        <Stat
          label="Open exposure"
          value={run.open_financial_impact === null ? null : inr(run.open_financial_impact)}
          qualifier={<>{inr(run.total_financial_impact)} before waivers{exposure?.impact_not_calculated ? ` · ${plural(exposure.impact_not_calculated, "finding")} not priced` : ""}</>}
        />
        <Stat
          label="High-risk employees"
          value={levels.HIGH ?? null}
          tone={levels.HIGH ? "danger" : "neutral"}
          qualifier="by risk score"
          href={runLink("&tab=risk")}
          className="col-span-2 md:col-span-1"
        />
      </div>

      <OutcomeStrip coverage={coverage} onOpen={() => setTab("coverage")} />

      <Tabs
        label="Result views"
        value={tab}
        onChange={setTab}
        items={[
          { id: "overview", label: "Overview" },
          { id: "findings", label: "Findings", count: run.total_findings },
          { id: "coverage", label: "Coverage", count: coverage?.material_cannot_validate || null },
          { id: "risk", label: "Employees by risk" },
          { id: "pf", label: "PF" },
          { id: "esic", label: "ESIC" },
          { id: "ptlwf", label: "PT / LWF" },
          { id: "lop", label: "LOP & arrears" },
        ]}
      />

      <div role="tabpanel" aria-label={tab}>
        {tab === "overview" && (
          <div className="space-y-4">
            <div className="grid items-start gap-4 lg:grid-cols-[2fr_3fr]">
              <RiskBar levels={levels} />
              <TopChecks rules={summaryQ.data?.rules ?? []} onPick={(rule) => url.set({ tab: "findings", f_rule: rule, f_page: null })} />
            </div>
            <EmployeeView runId={run.id} mode="overview" />
            <IntegrationPanel period={run.period_month} />
          </div>
        )}
        {tab === "findings" && <FindingsView runId={run.id} />}
        {tab === "coverage" && <CoverageTab runId={run.id} coverage={coverage} exposure={exposure} />}
        {tab === "risk" && <EmployeeView runId={run.id} mode="risk" />}
        {tab === "pf" && <EmployeeView runId={run.id} mode="pf" />}
        {tab === "esic" && <EmployeeView runId={run.id} mode="esic" />}
        {tab === "ptlwf" && <EmployeeView runId={run.id} mode="ptlwf" />}
        {tab === "lop" && <FindingsView runId={run.id} rulePrefix="LOP,ATT,ARR,MOM,ADV,TDS" prefix="l" />}
      </div>
    </div>
  );
}

export default function ResultsPage() {
  return (
    <Suspense fallback={<Skeleton className="h-[28rem] w-full rounded-xl" />}>
      <PayrollResultsContent />
    </Suspense>
  );
}
