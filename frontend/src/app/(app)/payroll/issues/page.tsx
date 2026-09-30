"use client";

import Link from "next/link";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { AlertTriangle, Download, MessageSquare, Paperclip, Repeat, Search } from "lucide-react";

import { DataTable, FilterSelect, Pagination, type Column } from "@/components/data/DataTable";
import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Button } from "@/components/ui/button";
import { Drawer } from "@/components/ui/drawer";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill, type StatusTone } from "@/components/ui/status-pill";
import { useEntity } from "@/context/EntityContext";
import { saveBlob } from "@/lib/download";
import { count, date, dateTime, inr, plural } from "@/lib/format";
import {
  ISSUE_STATE_LABEL, issuesApi,
  type Assignee, type Issue, type IssueDetail, type IssuePage, type IssueState, type WorklistParams,
} from "@/lib/issues";
import { cn } from "@/lib/utils";
import { monthLabel } from "@/lib/validation";

/**
 * Issues — the findings worklist.
 *
 * A run says what was wrong in one upload; this page is where it gets fixed.
 * Findings are grouped by fingerprint across months, so each carries its own
 * owner, due date, comments, evidence and decision history, and the same issue
 * recurring for the fifth month is visibly not the same as a new one.
 *
 * Filters live in the URL: a link from the Control Centre or a results page
 * arrives already filtered, and coming back to the list finds it as it was.
 */

const PAGE_SIZE = 50;
const WRITE_ROLES = new Set(["owner", "manager", "analyst"]);
const FIELD = "h-8 rounded-lg border border-ink-200 bg-white px-2.5 text-[13px] text-ink-900";
const SEVERITY_TONE: Record<string, StatusTone> = { CRITICAL: "danger", WARNING: "warning", INFO: "info" };
const SEVERITY_LABEL: Record<string, string> = { CRITICAL: "Critical", WARNING: "Warning", INFO: "Info" };
const STATE_TONE: Record<IssueState, StatusTone> = { open: "danger", acknowledged: "info", waived: "neutral", resolved: "success" };
const STATES: IssueState[] = ["open", "acknowledged", "waived", "resolved"];

function ImpactCell({ i }: { i: Pick<Issue, "impact_calculated" | "last_financial_impact"> }) {
  return i.impact_calculated ? (
    <span className="num">{inr(i.last_financial_impact)}</span>
  ) : (
    <span className="text-xs italic text-ink-500" title="This check does not price its effect. It is not a ₹0 finding.">Not calculated</span>
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

function IssuesContent() {
  const { entity, activeRole } = useEntity();
  const qc = useQueryClient();
  const canWrite = WRITE_ROLES.has(activeRole ?? "");
  const router = useRouter();
  const pathname = usePathname();
  const sp = useSearchParams();

  const params: WorklistParams = useMemo(() => ({
    state: (sp.get("state") ?? "active") as WorklistParams["state"],
    severity: sp.get("severity") || undefined,
    rule_id: sp.get("rule_id") || undefined,
    owner: sp.get("owner") || undefined,
    overdue: sp.get("overdue") === "true" || undefined,
    recurring: sp.get("recurring") === "true" || undefined,
    sort: (sp.get("sort") as WorklistParams["sort"]) || "priority",
    page: Number(sp.get("page") || 1),
  }), [sp]);
  const set = useCallback((patch: Record<string, string | number | boolean | null | undefined>, keepPage = false) => {
    const p = new URLSearchParams(sp.toString());
    for (const [k, v] of Object.entries(patch)) {
      if (v === undefined || v === null || v === "" || v === false) p.delete(k);
      else p.set(k, String(v));
    }
    if (!keepPage) p.delete("page");
    router.replace(`${pathname}${p.toString() ? `?${p.toString()}` : ""}`, { scroll: false });
  }, [sp, pathname, router]);

  const [search, setSearch] = useState(sp.get("q") ?? "");
  const q = useDebounced(search);
  useEffect(() => {
    if ((sp.get("q") ?? "") !== q) set({ q });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState<string | null>(null);

  const list = useQuery<IssuePage>({
    queryKey: ["issues", entity?.id, { ...params, q }],
    queryFn: () => issuesApi.worklist({ ...params, q, page_size: PAGE_SIZE }),
    enabled: !!entity,
    placeholderData: keepPreviousData,
  });
  const assignees = useQuery<Assignee[]>({
    queryKey: ["issue-assignees", entity?.id],
    queryFn: () => issuesApi.assignees(),
    enabled: !!entity,
  });

  // Selection is per result set: a filter change clears it, so a bulk action
  // never reaches rows the reader can no longer see.
  useEffect(() => { setSelected(new Set()); }, [params, q]);
  const refresh = () => qc.invalidateQueries({ queryKey: ["issues", entity?.id] });

  const data = list.data;
  const filtered = !!(params.severity || params.rule_id || params.owner || params.overdue || params.recurring || q || params.state !== "active");

  const columns: Column<Issue>[] = [
    {
      id: "employee", header: "Employee", pin: true,
      cell: (i) => (
        <span className="block max-w-[12rem]">
          <span className="block font-mono text-xs text-ink-500">{i.employee_id}</span>
          <span className="block truncate text-ink-900">{i.employee_name ?? "—"}</span>
        </span>
      ),
    },
    {
      id: "check", header: "Check",
      cell: (i) => (
        <span className="block max-w-[18rem]">
          <span className="font-mono text-xs text-ink-500">{i.rule_id}</span> <span className="text-ink-900">{i.rule_name}</span>
        </span>
      ),
    },
    { id: "severity", header: "Severity", cell: (i) => <StatusPill tone={SEVERITY_TONE[i.severity] ?? "neutral"}>{SEVERITY_LABEL[i.severity] ?? i.severity}</StatusPill> },
    {
      id: "state", header: "State",
      cell: (i) => (
        <span className="block">
          <StatusPill tone={STATE_TONE[i.state]}>{ISSUE_STATE_LABEL[i.state]}</StatusPill>
          {i.state === "waived" && i.waived_until ? <span className="mt-0.5 block text-xs text-ink-500">until {date(i.waived_until)}</span> : null}
          {i.waiver_open_ended ? <span className="mt-0.5 block text-xs font-medium text-warning-800" title="Waived before every waiver had to end. Waive again with an end date, or reopen.">No end date — review</span> : null}
        </span>
      ),
    },
    {
      id: "seen", header: "Seen", hideable: true,
      cell: (i) => i.occurrence_count > 1
        ? <span className="inline-flex items-center gap-1 whitespace-nowrap text-xs font-medium text-warning-800"><Repeat size={12} aria-hidden /> {i.occurrence_count} months</span>
        : <span className="whitespace-nowrap text-xs text-ink-600">{monthLabel(i.first_seen_period)}</span>,
    },
    { id: "impact", header: "Impact", numeric: true, cell: (i) => <ImpactCell i={i} /> },
    { id: "owner", header: "Owner", hideable: true, cell: (i) => i.owner_email ? <span className="block max-w-[12rem] truncate text-xs text-ink-700" title={i.owner_email}>{i.owner_email}</span> : <span className="text-xs text-ink-500">Unassigned</span> },
    {
      id: "due", header: "Due", hideable: true,
      cell: (i) => <span className={cn("whitespace-nowrap text-xs", i.overdue ? "font-medium text-danger-700" : "text-ink-600")}>{i.due_date ? date(i.due_date) : "—"}{i.overdue ? " · overdue" : ""}</span>,
    },
    {
      id: "activity", header: <span className="sr-only">Comments and evidence</span>,
      cell: (i) => (
        <span className="inline-flex items-center gap-2 text-xs text-ink-500">
          {i.comment_count ? <span className="inline-flex items-center gap-0.5" title={plural(i.comment_count, "comment")}><MessageSquare size={12} aria-hidden />{i.comment_count}</span> : null}
          {i.attachment_count ? <span className="inline-flex items-center gap-0.5" title={plural(i.attachment_count, "file")}><Paperclip size={12} aria-hidden />{i.attachment_count}</span> : null}
        </span>
      ),
    },
  ];

  return (
    <div className="space-y-5">
      <PageHeader
        title="Issues"
        description="Every finding still to be worked, across months — with an owner, a due date, comments, evidence and the decisions taken on it."
      />

      {data ? (
        <nav aria-label="Issue states" className="flex flex-wrap items-center gap-1.5">
          {[
            { key: "active", label: "Open and in progress", n: (data.counts.open ?? 0) + (data.counts.acknowledged ?? 0), on: params.state === "active" && !params.overdue && params.owner !== "none" },
            ...STATES.map((s) => ({ key: s, label: ISSUE_STATE_LABEL[s], n: data.counts[s] ?? 0, on: params.state === s })),
          ].map((c) => (
            <button key={c.key} type="button" aria-pressed={c.on} onClick={() => set({ state: c.key === "active" ? null : c.key, overdue: null, owner: null })}
              className={cn("inline-flex h-8 items-center gap-1.5 rounded-lg border px-2.5 text-[13px]", c.on ? "border-ink-900 bg-ink-900 text-white" : "border-ink-200 bg-white text-ink-700 hover:bg-ink-50")}>
              {c.label} <span className={cn("num text-xs", c.on ? "text-white/80" : "text-ink-500")}>{count(c.n)}</span>
            </button>
          ))}
          <span className="mx-1 h-5 w-px bg-ink-200" aria-hidden />
          <button type="button" aria-pressed={!!params.overdue} onClick={() => set({ state: null, overdue: !params.overdue })}
            className={cn("inline-flex h-8 items-center gap-1.5 rounded-lg border px-2.5 text-[13px]", params.overdue ? "border-danger-600 bg-danger-600 text-white" : "border-ink-200 bg-white text-ink-700 hover:bg-ink-50")}>
            Overdue <span className="num text-xs">{count(data.overdue)}</span>
          </button>
          <button type="button" aria-pressed={params.owner === "none"} onClick={() => set({ state: null, owner: params.owner === "none" ? null : "none" })}
            className={cn("inline-flex h-8 items-center gap-1.5 rounded-lg border px-2.5 text-[13px]", params.owner === "none" ? "border-ink-900 bg-ink-900 text-white" : "border-ink-200 bg-white text-ink-700 hover:bg-ink-50")}>
            Unassigned <span className="num text-xs">{count(data.unassigned)}</span>
          </button>
        </nav>
      ) : (
        // Holds the chips' height while counts load, so the table does not jump down when they arrive.
        <div className="flex h-8 gap-1.5" aria-hidden>{[148, 72, 96, 84, 72].map((w, i) => <div key={i} className="h-8 animate-pulse-soft rounded-lg bg-ink-100" style={{ width: w }} />)}</div>
      )}

      {canWrite && selected.size > 0 ? (
        <BulkBar
          fingerprints={Array.from(selected)}
          total={data?.total ?? 0}
          assignees={assignees.data ?? []}
          onClear={() => setSelected(new Set())}
          onDone={() => { setSelected(new Set()); void refresh(); }}
        />
      ) : null}

      <DataTable
        id="issues"
        caption="Issues worklist"
        columns={columns}
        rows={data?.items}
        rowKey={(i) => i.fingerprint}
        loading={list.isLoading}
        refreshing={list.isFetching && !list.isLoading}
        error={list.isError ? <AlertBanner variant="error" title="Issues could not be loaded" details={(list.error as Error)?.message}>Try again in a moment.</AlertBanner> : undefined}
        onRowOpen={(i) => setOpen(i.fingerprint)}
        rowLabel={(i) => `${i.rule_id} ${i.rule_name} for ${i.employee_name ?? i.employee_id}`}
        selectable={canWrite}
        selected={selected}
        onSelectedChange={setSelected}
        toolbar={
          <>
            <div className="relative min-w-[12rem] flex-1 sm:max-w-xs">
              <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-500" aria-hidden />
              <input type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Employee or check" aria-label="Search issues"
                className="h-8 w-full rounded-lg border border-ink-200 bg-white pl-8 pr-2 text-[13px] focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20" />
            </div>
            <FilterSelect label="Severity" allLabel="Any severity" value={params.severity ?? ""} onChange={(v) => set({ severity: v })}
              options={["CRITICAL", "WARNING", "INFO"].map((s) => ({ value: s, label: SEVERITY_LABEL[s] }))} />
            <FilterSelect label="Check" allLabel="Any check" value={params.rule_id ?? ""} onChange={(v) => set({ rule_id: v })}
              options={(data?.rules ?? []).map((r) => ({ value: r.rule_id, label: `${r.rule_id} · ${r.rule_name} (${r.count})` }))} />
            <FilterSelect label="Owner" allLabel="Anyone" value={params.owner ?? ""} onChange={(v) => set({ owner: v })}
              options={[{ value: "me", label: "Assigned to me" }, { value: "none", label: "Unassigned" }, ...(assignees.data ?? []).map((a) => ({ value: a.user_id, label: a.email }))]} />
            <label className="inline-flex items-center gap-1.5 text-xs text-ink-700">
              <input type="checkbox" className="accent-brand-600" checked={!!params.recurring} onChange={(e) => set({ recurring: e.target.checked })} />
              Recurring (3+ months)
            </label>
            <label className="inline-flex items-center gap-1.5 text-xs text-ink-500">
              Sort
              <select aria-label="Sort" className={FIELD} value={params.sort} onChange={(e) => set({ sort: e.target.value === "priority" ? null : e.target.value })}>
                <option value="priority">Worst first</option>
                <option value="due_date">Due soonest</option>
                <option value="impact">Largest impact</option>
                <option value="last_seen">Most recent</option>
              </select>
            </label>
            {filtered ? (
              <button type="button" className="text-xs font-medium text-brand-700 hover:underline" onClick={() => { setSearch(""); router.replace(pathname, { scroll: false }); }}>
                Reset
              </button>
            ) : null}
          </>
        }
        empty={
          <>
            No issues match these filters. This lists findings from validation runs; a month that was never validated has none to show —{" "}
            <Link className="underline" href="/control-centre">see the Control Centre</Link>.
          </>
        }
        footer={data ? <Pagination page={data.page} pages={data.pages} total={data.total} pageSize={PAGE_SIZE} onPage={(p) => set({ page: p }, true)} noun="issues" /> : null}
        minWidth="70rem"
      />

      <IssuePanel fingerprint={open} canWrite={canWrite} assignees={assignees.data ?? []} onClose={() => setOpen(null)} onChanged={() => void refresh()} />
    </div>
  );
}

function BulkBar({ fingerprints, total, assignees, onDone, onClear }: {
  fingerprints: string[]; total: number; assignees: Assignee[]; onDone: () => void; onClear: () => void;
}) {
  const [mode, setMode] = useState<"none" | "waive" | "assign" | "resolve">("none");
  const [reason, setReason] = useState("");
  const [until, setUntil] = useState("");
  const [owner, setOwner] = useState("");
  const [due, setDue] = useState("");
  const [busy, setBusy] = useState(false);

  // Outcomes are shown as the server confirms them — never assumed.
  const run = async (fn: () => ReturnType<typeof issuesApi.bulk>) => {
    setBusy(true);
    try {
      const out = await fn();
      toast.success(`${plural(out.updated, "issue")} updated`, {
        description: out.skipped.length ? `${out.skipped.length} skipped: ${out.skipped[0].reason}` : undefined,
      });
      onDone();
    } catch (e) {
      toast.error("Not applied", { description: e instanceof Error ? e.message : "" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <section aria-label="Bulk actions" className="space-y-3 rounded-xl border border-brand-200 bg-brand-50/60 px-3 py-2.5 text-[13px]">
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-ink-800" aria-live="polite">
          <b>{plural(fingerprints.length, "issue")} selected</b>
          <span className="text-ink-500"> on this page, of {count(total)} matching</span>
        </p>
        <button type="button" className="text-xs text-brand-700 hover:underline" onClick={onClear}>Clear</button>
        <span className="mx-1 h-5 w-px bg-brand-200" aria-hidden />
        <Button size="sm" variant="outline" disabled={busy}
          onClick={() => void run(() => issuesApi.bulk(fingerprints, { action: "decision", state: "acknowledged" }))}>
          Mark in progress
        </Button>
        <Button size="sm" variant="outline" aria-pressed={mode === "resolve"} onClick={() => setMode("resolve")}>Resolve…</Button>
        <Button size="sm" variant="outline" aria-pressed={mode === "waive"} onClick={() => setMode("waive")}>Waive…</Button>
        <Button size="sm" variant="outline" aria-pressed={mode === "assign"} onClick={() => setMode("assign")}>Assign…</Button>
      </div>
      {mode === "waive" || mode === "resolve" ? (
        <div className="flex flex-wrap items-end gap-2">
          <label className="min-w-[18rem] flex-1 text-xs text-ink-700">
            {mode === "waive" ? "Reason — required, recorded on every selected issue" : "Why these are resolved — required"}
            <input className={cn(FIELD, "mt-1 w-full")} value={reason} onChange={(e) => setReason(e.target.value)} />
          </label>
          {mode === "waive" ? (
            <label className="text-xs text-ink-700">
              Waived until (90 days if blank)
              <input type="date" className={cn(FIELD, "mt-1 block")} value={until} onChange={(e) => setUntil(e.target.value)} />
            </label>
          ) : null}
          <Button size="sm" disabled={busy || !reason.trim()}
            onClick={() => void run(() => issuesApi.bulk(fingerprints, {
              action: "decision", state: mode === "waive" ? "waived" : "resolved",
              reason, waived_until: mode === "waive" ? until || null : null,
            }))}>
            {mode === "waive" ? "Waive" : "Resolve"} {plural(fingerprints.length, "issue")}
          </Button>
        </div>
      ) : null}
      {mode === "assign" ? (
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-xs text-ink-700">
            Owner
            <select className={cn(FIELD, "mt-1 block")} value={owner} onChange={(e) => setOwner(e.target.value)}>
              <option value="">Unassigned</option>
              {assignees.map((a) => <option key={a.user_id} value={a.user_id}>{a.email}</option>)}
            </select>
          </label>
          <label className="text-xs text-ink-700">
            Due
            <input type="date" className={cn(FIELD, "mt-1 block")} value={due} onChange={(e) => setDue(e.target.value)} />
          </label>
          <Button size="sm" disabled={busy}
            onClick={() => void run(() => issuesApi.bulk(fingerprints, { action: "assign", owner_user_id: owner || null, due_date: due || null }))}>
            Assign {plural(fingerprints.length, "issue")}
          </Button>
        </div>
      ) : null}
    </section>
  );
}

function IssuePanel({ fingerprint, canWrite, assignees, onClose, onChanged }: {
  fingerprint: string | null; canWrite: boolean; assignees: Assignee[]; onClose: () => void; onChanged: () => void;
}) {
  const { entity } = useEntity();
  const qc = useQueryClient();
  const key = ["issue", entity?.id, fingerprint];
  const detail = useQuery<IssueDetail>({ queryKey: key, queryFn: () => issuesApi.detail(fingerprint!), enabled: !!fingerprint });
  const [comment, setComment] = useState("");
  const [reason, setReason] = useState("");
  const [until, setUntil] = useState("");
  const [busy, setBusy] = useState(false);
  const [owner, setOwner] = useState<string>("");
  const [due, setDue] = useState<string>("");

  const f = detail.data?.finding;
  useEffect(() => {
    if (f) { setOwner(f.owner_user_id ?? ""); setDue(f.due_date ?? ""); }
  }, [f]);
  useEffect(() => { setComment(""); setReason(""); setUntil(""); }, [fingerprint]);

  const act = async (fn: () => Promise<unknown>, done: string) => {
    setBusy(true);
    try {
      await fn();
      toast.success(done);
      setComment(""); setReason(""); setUntil("");
      await qc.invalidateQueries({ queryKey: key });
      onChanged();
    } catch (e) {
      toast.error("Not saved", { description: e instanceof Error ? e.message : "" });
    } finally {
      setBusy(false);
    }
  };

  const decisions = useMemo(() => (f ? ([
    { state: "acknowledged", label: "Mark in progress", needs: false },
    { state: "resolved", label: "Resolve", needs: true },
    { state: "waived", label: "Waive", needs: true },
    { state: "open", label: "Reopen", needs: false },
  ] as { state: IssueState; label: string; needs: boolean }[]).filter((d) => d.state !== f.state) : []), [f]);

  return (
    <Drawer
      open={!!fingerprint}
      onClose={onClose}
      width="lg"
      title={f?.rule_name ?? "Loading…"}
      description={f ? <><span className="font-mono">{f.rule_id}</span> · {f.employee_name ?? "—"} · <span className="font-mono">{f.employee_id}</span></> : null}
    >
      {!f ? (
        detail.isError ? <AlertBanner variant="error" title="This issue could not be loaded">{(detail.error as Error)?.message}</AlertBanner> : <Skeleton className="h-64 w-full" />
      ) : (
        <div className="space-y-6 text-[13px]">
          <div className="flex flex-wrap items-center gap-2">
            <StatusPill tone={STATE_TONE[f.state]}>{ISSUE_STATE_LABEL[f.state]}</StatusPill>
            <StatusPill tone={SEVERITY_TONE[f.severity] ?? "neutral"}>{SEVERITY_LABEL[f.severity] ?? f.severity}</StatusPill>
            {f.overdue ? <span className="inline-flex items-center gap-1 text-xs font-medium text-danger-700"><AlertTriangle size={12} aria-hidden /> Overdue</span> : null}
          </div>
          <dl className="grid grid-cols-2 gap-3 rounded-lg border border-ink-200 p-3">
            <div><dt className="text-xs text-ink-500">First seen</dt><dd className="font-medium text-ink-900">{monthLabel(f.first_seen_period)}</dd></div>
            <div><dt className="text-xs text-ink-500">Last seen</dt><dd className="font-medium text-ink-900">{monthLabel(f.last_seen_period)} · {plural(f.occurrence_count, "month")}</dd></div>
            <div><dt className="text-xs text-ink-500">Impact (last run)</dt><dd className="font-medium text-ink-900"><ImpactCell i={f} /></dd></div>
            {f.waiver_reason ? <div><dt className="text-xs text-ink-500">Waiver</dt><dd className="text-ink-900">{f.waiver_reason}{f.waived_until ? ` (until ${date(f.waived_until)})` : ""}</dd></div> : null}
          </dl>
          <Link href={`/payroll/employee/${encodeURIComponent(f.employee_id)}`} className="inline-block text-xs font-medium text-brand-700 hover:underline">
            Open the employee in the latest run
          </Link>

          <section className="space-y-2" aria-labelledby="owner-h">
            <h3 id="owner-h" className="text-[13px] font-semibold text-ink-900">Owner and due date</h3>
            <div className="flex flex-wrap items-end gap-2">
              <label className="text-xs text-ink-600">Owner
                <select className={cn(FIELD, "mt-1 block")} disabled={!canWrite} value={owner} onChange={(e) => setOwner(e.target.value)}>
                  <option value="">Unassigned</option>
                  {assignees.map((a) => <option key={a.user_id} value={a.user_id}>{a.email}</option>)}
                </select>
              </label>
              <label className="text-xs text-ink-600">Due
                <input type="date" className={cn(FIELD, "mt-1 block")} disabled={!canWrite} value={due} onChange={(e) => setDue(e.target.value)} />
              </label>
              {canWrite ? (
                <Button size="sm" variant="outline" disabled={busy}
                  onClick={() => void act(() => issuesApi.assign(fingerprint!, { owner_user_id: owner || null, due_date: due || null }), "Assignment saved")}>
                  Save
                </Button>
              ) : null}
            </div>
          </section>

          {canWrite ? (
            <section className="space-y-2" aria-labelledby="decision-h">
              <h3 id="decision-h" className="text-[13px] font-semibold text-ink-900">Decision</h3>
              <label className="block text-xs text-ink-600">Reason (required to resolve or waive)
                <input className={cn(FIELD, "mt-1 w-full")} value={reason} onChange={(e) => setReason(e.target.value)} />
              </label>
              <label className="block text-xs text-ink-600">
                Waive until — a waiver always expires; 90 days if left blank
                <input type="date" className={cn(FIELD, "mt-1 block")} value={until} onChange={(e) => setUntil(e.target.value)} />
              </label>
              <div className="flex flex-wrap gap-2">
                {decisions.map((d) => (
                  <Button key={d.state} size="sm" variant={d.state === "resolved" ? "default" : "outline"}
                    disabled={busy || (d.needs && !reason.trim())}
                    onClick={() => void act(() => issuesApi.decide(fingerprint!, {
                      state: d.state, reason: reason || null, waived_until: d.state === "waived" ? until || null : null,
                    }), `${d.label} — saved`)}>
                    {d.label}
                  </Button>
                ))}
              </div>
            </section>
          ) : null}

          <section className="space-y-2" aria-labelledby="comments-h">
            <h3 id="comments-h" className="text-[13px] font-semibold text-ink-900">Comments</h3>
            {detail.data!.comments.length === 0 ? <p className="text-xs text-ink-500">No comments yet.</p> : (
              <ul className="space-y-2">
                {detail.data!.comments.map((c) => (
                  <li key={c.id} className="rounded-lg bg-ink-50 px-3 py-2">
                    <p className="whitespace-pre-wrap text-ink-800">{c.body}</p>
                    <p className="mt-1 text-xs text-ink-500">{c.author_email} · {dateTime(c.created_at)}</p>
                  </li>
                ))}
              </ul>
            )}
            {canWrite ? (
              <div className="flex gap-2">
                <label className="sr-only" htmlFor="new-comment">Add a comment</label>
                <textarea id="new-comment" className="min-h-[2.5rem] flex-1 rounded-lg border border-ink-200 px-2.5 py-1.5 text-[13px]" rows={2} placeholder="Add a comment" value={comment} onChange={(e) => setComment(e.target.value)} />
                <Button size="sm" disabled={busy || !comment.trim()} onClick={() => void act(() => issuesApi.comment(fingerprint!, comment), "Comment added")}>Post</Button>
              </div>
            ) : null}
          </section>

          <section className="space-y-2" aria-labelledby="evidence-h">
            <h3 id="evidence-h" className="text-[13px] font-semibold text-ink-900">Evidence</h3>
            {detail.data!.attachments.length === 0 ? <p className="text-xs text-ink-500">No files attached.</p> : (
              <ul className="divide-y divide-ink-100 rounded-lg border border-ink-200">
                {detail.data!.attachments.map((a) => (
                  <li key={a.id} className="flex items-center justify-between gap-2 px-3 py-2 text-xs">
                    <span className="min-w-0 truncate">{a.filename} · {a.size < 1024 ? `${a.size} bytes` : `${Math.round(a.size / 1024).toLocaleString("en-IN")} KB`} · {a.uploaded_by_email}</span>
                    <button type="button" className="inline-flex items-center gap-1 font-medium text-brand-700 hover:underline"
                      onClick={async () => {
                        try { saveBlob(await issuesApi.download(fingerprint!, a.id), a.filename); } catch (e) { toast.error("Download failed", { description: e instanceof Error ? e.message : "" }); }
                      }}>
                      <Download size={12} aria-hidden /> Download
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {canWrite ? (
              <label className="block text-xs text-ink-600">
                Attach a file (PDF, image, spreadsheet, CSV or text; up to 5 MB)
                <input type="file" className="mt-1 block text-xs" disabled={busy} accept=".pdf,.png,.jpg,.jpeg,.xlsx,.xls,.csv,.txt"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) void act(() => issuesApi.attach(fingerprint!, file), "File attached");
                    e.target.value = "";
                  }} />
              </label>
            ) : null}
          </section>

          <section className="space-y-1" aria-labelledby="history-h">
            <h3 id="history-h" className="text-[13px] font-semibold text-ink-900">History</h3>
            {detail.data!.history.length === 0 ? <p className="text-xs text-ink-500">No decisions yet.</p> : (
              <ol className="space-y-1.5 border-l border-ink-200 pl-3 text-xs text-ink-600">
                {detail.data!.history.map((h) => (
                  <li key={h.id}>
                    <span className="text-ink-900">
                      {h.from_state === h.to_state
                        ? `Updated — still ${(ISSUE_STATE_LABEL[h.to_state as IssueState] ?? h.to_state).toLowerCase()}`
                        : `${h.from_state ? ISSUE_STATE_LABEL[h.from_state as IssueState] ?? h.from_state : "New"} → ${ISSUE_STATE_LABEL[h.to_state as IssueState] ?? h.to_state}`}
                    </span>
                    {" "}by {h.actor_email ?? "the system"} · {dateTime(h.created_at)}
                    {h.reason ? <span className="block text-ink-500">{h.reason}</span> : null}
                  </li>
                ))}
              </ol>
            )}
          </section>
        </div>
      )}
    </Drawer>
  );
}

export default function IssuesPage() {
  return (
    <Suspense fallback={<Skeleton className="h-96 w-full rounded-xl" />}>
      <IssuesContent />
    </Suspense>
  );
}
