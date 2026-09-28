"use client";

import Link from "next/link";
import { Suspense, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  AlertTriangle, CalendarClock, ChevronLeft, ChevronRight, Download, Loader2, MessageSquare,
  Paperclip, Repeat, Search, UserRound, X,
} from "lucide-react";

import { useEntity } from "@/context/EntityContext";
import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  ISSUE_STATE_LABEL, issuesApi,
  type Assignee, type Issue, type IssueDetail, type IssuePage, type IssueState, type WorklistParams,
} from "@/lib/issues";
import { inr, monthLabel } from "@/lib/validation";
import { cn } from "@/lib/utils";

/**
 * Issues — the findings worklist.
 *
 * A run says what was wrong in one upload; this page is where it gets fixed.
 * Findings are grouped by fingerprint across months, so each carries its own
 * owner, due date, comments, evidence and decision history, and the same issue
 * recurring for the fifth month is visibly not the same as a new one.
 */

const PAGE_SIZE = 50;
const WRITE_ROLES = new Set(["owner", "manager", "analyst"]);
const FIELD =
  "rounded-lg border border-ink-200 bg-white px-2.5 py-1.5 text-sm text-ink-900 dark:border-white/10 dark:bg-white/[0.04] dark:text-white";
const SEV: Record<string, string> = {
  CRITICAL: "bg-danger-100 text-danger-800 dark:bg-danger-500/15 dark:text-danger-200",
  WARNING: "bg-warning-100 text-warning-800 dark:bg-warning-500/15 dark:text-warning-200",
  INFO: "bg-sky-100 text-sky-800 dark:bg-sky-500/15 dark:text-sky-200",
};
const STATE_TONE: Record<IssueState, string> = {
  open: "bg-danger-50 text-danger-700 dark:bg-danger-500/10 dark:text-danger-300",
  acknowledged: "bg-brand-50 text-brand-700 dark:bg-brand-500/10 dark:text-brand-300",
  waived: "bg-ink-100 text-ink-700 dark:bg-white/10 dark:text-ink-200",
  resolved: "bg-success-50 text-success-700 dark:bg-success-500/10 dark:text-success-300",
};

const impactText = (i: Issue) =>
  i.impact_calculated ? inr(i.last_financial_impact, 0) : "Not calculated";

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
  const [params, setParams] = useState<WorklistParams>({ state: "active", sort: "priority", page: 1 });
  const [search, setSearch] = useState("");
  const q = useDebounced(search);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState<string | null>(null);

  const listKey = ["issues", entity?.id, { ...params, q }];
  const list = useQuery<IssuePage>({
    queryKey: listKey,
    queryFn: () => issuesApi.worklist({ ...params, q, page_size: PAGE_SIZE }),
    enabled: !!entity,
  });
  const assignees = useQuery<Assignee[]>({
    queryKey: ["issue-assignees", entity?.id],
    queryFn: () => issuesApi.assignees(),
    enabled: !!entity,
  });

  useEffect(() => { setSelected(new Set()); }, [params, q, entity?.id]);

  const set = (patch: Partial<WorklistParams>) => setParams((p) => ({ ...p, page: 1, ...patch }));
  const refresh = () => qc.invalidateQueries({ queryKey: ["issues", entity?.id] });

  const data = list.data;
  const items = data?.items ?? [];
  const allSelected = items.length > 0 && items.every((i) => selected.has(i.fingerprint));

  return (
    <div className="space-y-6">
      <PageHeader
        title="Issues"
        description="Every finding still to be worked, across months — with an owner, a due date, comments, evidence and the decisions taken on it."
      />

      {data ? (
        <div className="flex flex-wrap gap-2 text-xs">
          {(["open", "acknowledged", "waived", "resolved"] as IssueState[]).map((s) => (
            <button key={s} type="button" onClick={() => set({ state: s })}
              className={cn("rounded-full px-3 py-1 font-semibold", STATE_TONE[s],
                params.state === s && "ring-2 ring-current")}>
              {ISSUE_STATE_LABEL[s]} {data.counts[s] ?? 0}
            </button>
          ))}
          <button type="button" onClick={() => set({ state: "active", overdue: !params.overdue })}
            className={cn("rounded-full bg-warning-50 px-3 py-1 font-semibold text-warning-800 dark:bg-warning-500/10 dark:text-warning-200",
              params.overdue && "ring-2 ring-current")}>
            Overdue {data.overdue}
          </button>
          <button type="button" onClick={() => set({ state: "active", owner: params.owner === "none" ? undefined : "none" })}
            className={cn("rounded-full bg-ink-100 px-3 py-1 font-semibold text-ink-700 dark:bg-white/10 dark:text-ink-200",
              params.owner === "none" && "ring-2 ring-current")}>
            Unassigned {data.unassigned}
          </button>
        </div>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-56 flex-1">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
          <input className={cn(FIELD, "w-full py-2 pl-9")} placeholder="Search employee or rule…" value={search}
            onChange={(e) => setSearch(e.target.value)} aria-label="Search issues" />
        </div>
        <select className={FIELD} aria-label="State" value={params.state ?? ""}
          onChange={(e) => set({ state: e.target.value as WorklistParams["state"] })}>
          <option value="active">Open and in progress</option>
          <option value="">All states</option>
          {(["open", "acknowledged", "waived", "resolved"] as IssueState[]).map((s) => (
            <option key={s} value={s}>{ISSUE_STATE_LABEL[s]}</option>
          ))}
        </select>
        <select className={FIELD} aria-label="Severity" value={params.severity ?? ""}
          onChange={(e) => set({ severity: e.target.value || undefined })}>
          <option value="">Any severity</option>
          <option value="CRITICAL">Critical</option>
          <option value="WARNING">Warning</option>
          <option value="INFO">Info</option>
        </select>
        <select className={FIELD} aria-label="Rule" value={params.rule_id ?? ""}
          onChange={(e) => set({ rule_id: e.target.value || undefined })}>
          <option value="">Any rule</option>
          {(data?.rules ?? []).map((r) => (
            <option key={r.rule_id} value={r.rule_id}>{r.rule_id} · {r.rule_name} ({r.count})</option>
          ))}
        </select>
        <select className={FIELD} aria-label="Owner" value={params.owner ?? ""}
          onChange={(e) => set({ owner: e.target.value || undefined })}>
          <option value="">Anyone</option>
          <option value="me">Assigned to me</option>
          <option value="none">Unassigned</option>
          {(assignees.data ?? []).map((a) => <option key={a.user_id} value={a.user_id}>{a.email}</option>)}
        </select>
        <label className="flex items-center gap-1.5 text-xs text-ink-600 dark:text-ink-300">
          <input type="checkbox" checked={!!params.recurring} onChange={(e) => set({ recurring: e.target.checked })} />
          Recurring (3+ months)
        </label>
        <select className={FIELD} aria-label="Sort" value={params.sort}
          onChange={(e) => set({ sort: e.target.value as WorklistParams["sort"] })}>
          <option value="priority">Worst first</option>
          <option value="due_date">Due soonest</option>
          <option value="impact">Largest impact</option>
          <option value="last_seen">Most recent</option>
        </select>
      </div>

      {canWrite && selected.size > 0 ? (
        <BulkBar fingerprints={Array.from(selected)} assignees={assignees.data ?? []}
          onDone={() => { setSelected(new Set()); void refresh(); }} />
      ) : null}

      {list.error ? (
        <AlertBanner variant="error" title="Could not load issues">
          {list.error instanceof Error ? list.error.message : "Try again."}
        </AlertBanner>
      ) : !data ? (
        <Skeleton className="h-72 w-full rounded-2xl" />
      ) : items.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-ink-200 px-6 py-12 text-center text-sm text-ink-500 dark:border-white/10">
          No issues match these filters. This lists findings from validation runs; a month that was never
          validated has none to show — see <Link className="underline" href="/payroll/results">Results</Link> for coverage.
        </div>
      ) : (
        <div className="overflow-hidden rounded-2xl border border-ink-200/70 bg-white shadow-soft dark:border-white/[0.07] dark:bg-ink-900/70">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-ink-50/80 text-[11px] uppercase tracking-[0.12em] text-ink-500 dark:bg-white/[0.03] dark:text-ink-300">
                <tr>
                  {canWrite ? (
                    <th className="w-10 px-3 py-2.5">
                      <input type="checkbox" aria-label="Select all on this page" checked={allSelected}
                        onChange={(e) => setSelected(e.target.checked ? new Set(items.map((i) => i.fingerprint)) : new Set())} />
                    </th>
                  ) : null}
                  {["Employee", "Check", "State", "Seen", "Impact", "Owner", "Due", ""].map((h) => (
                    <th key={h} className="px-3 py-2.5 text-left font-semibold">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-100 dark:divide-white/[0.05]">
                {items.map((i) => (
                  <tr key={i.fingerprint} className="hover:bg-ink-50/60 dark:hover:bg-white/[0.04]">
                    {canWrite ? (
                      <td className="px-3 py-2.5">
                        <input type="checkbox" aria-label={`Select ${i.employee_id} ${i.rule_id}`}
                          checked={selected.has(i.fingerprint)}
                          onChange={(e) => setSelected((prev) => {
                            const next = new Set(prev);
                            if (e.target.checked) next.add(i.fingerprint); else next.delete(i.fingerprint);
                            return next;
                          })} />
                      </td>
                    ) : null}
                    <td className="px-3 py-2.5">
                      <span className="font-mono text-xs text-ink-500">{i.employee_id}</span>
                      <span className="block text-ink-800 dark:text-ink-100">{i.employee_name ?? "—"}</span>
                    </td>
                    <td className="px-3 py-2.5">
                      <span className={cn("mr-1.5 rounded px-1.5 py-0.5 font-mono text-[11px] font-semibold", SEV[i.severity])}>{i.rule_id}</span>
                      <span className="text-ink-700 dark:text-ink-200">{i.rule_name}</span>
                    </td>
                    <td className="px-3 py-2.5">
                      <span className={cn("rounded-full px-2 py-0.5 text-xs font-semibold", STATE_TONE[i.state])}>{ISSUE_STATE_LABEL[i.state]}</span>
                      {i.state === "waived" && i.waived_until ? (
                        <span className="block text-[11px] text-ink-500">until {i.waived_until}</span>
                      ) : null}
                      {i.waiver_open_ended ? (
                        <span className="block text-[11px] font-semibold text-warning-700" title="Waived before every waiver had to end. Waive it again with an end date, or reopen it.">
                          no end date — review
                        </span>
                      ) : null}
                    </td>
                    <td className="px-3 py-2.5 text-xs text-ink-600 dark:text-ink-300">
                      {i.occurrence_count > 1 ? (
                        <span className="inline-flex items-center gap-1 font-semibold text-warning-700"><Repeat size={12} /> {i.occurrence_count} months</span>
                      ) : monthLabel(i.first_seen_period)}
                    </td>
                    <td className={cn("px-3 py-2.5 tabular-nums", !i.impact_calculated && "text-xs italic text-ink-500")}>{impactText(i)}</td>
                    <td className="px-3 py-2.5 text-xs text-ink-600 dark:text-ink-300">{i.owner_email ?? <span className="text-ink-400">Unassigned</span>}</td>
                    <td className={cn("px-3 py-2.5 text-xs", i.overdue ? "font-semibold text-danger-700" : "text-ink-600 dark:text-ink-300")}>
                      {i.due_date ?? "—"}{i.overdue ? " · overdue" : ""}
                    </td>
                    <td className="px-3 py-2.5 text-right">
                      <button type="button" onClick={() => setOpen(i.fingerprint)}
                        className="inline-flex items-center gap-1 text-xs font-semibold text-brand-700 hover:underline dark:text-brand-300">
                        {i.comment_count ? <><MessageSquare size={12} />{i.comment_count}</> : null}
                        {i.attachment_count ? <><Paperclip size={12} />{i.attachment_count}</> : null}
                        Open
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {data && data.pages > 1 ? (
        <div className="flex items-center justify-between text-sm">
          <span className="text-ink-500">Page {data.page} of {data.pages} · {data.total.toLocaleString("en-IN")} issues</span>
          <div className="flex gap-2">
            <Button type="button" variant="outline" disabled={data.page <= 1} aria-label="Previous page"
              onClick={() => setParams((p) => ({ ...p, page: (p.page ?? 1) - 1 }))}><ChevronLeft size={15} /></Button>
            <Button type="button" variant="outline" disabled={data.page >= data.pages} aria-label="Next page"
              onClick={() => setParams((p) => ({ ...p, page: (p.page ?? 1) + 1 }))}><ChevronRight size={15} /></Button>
          </div>
        </div>
      ) : null}

      {open ? (
        <IssuePanel fingerprint={open} canWrite={canWrite} assignees={assignees.data ?? []}
          onClose={() => setOpen(null)} onChanged={() => void refresh()} />
      ) : null}
    </div>
  );
}

function BulkBar({ fingerprints, assignees, onDone }: {
  fingerprints: string[]; assignees: Assignee[]; onDone: () => void;
}) {
  const [mode, setMode] = useState<"none" | "waive" | "assign" | "resolve">("none");
  const [reason, setReason] = useState("");
  const [until, setUntil] = useState("");
  const [owner, setOwner] = useState("");
  const [due, setDue] = useState("");
  const [busy, setBusy] = useState(false);

  const run = async (fn: () => ReturnType<typeof issuesApi.bulk>) => {
    setBusy(true);
    try {
      const out = await fn();
      toast.success(`${out.updated} issue(s) updated`, {
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
    <div className="space-y-3 rounded-2xl border border-brand-200 bg-brand-50/60 p-3 text-sm dark:border-brand-500/30 dark:bg-brand-500/10">
      <div className="flex flex-wrap items-center gap-2">
        <strong className="text-ink-800 dark:text-white">{fingerprints.length} selected</strong>
        <Button type="button" variant="outline" disabled={busy}
          onClick={() => void run(() => issuesApi.bulk(fingerprints, { action: "decision", state: "acknowledged" }))}>
          Mark in progress
        </Button>
        <Button type="button" variant="outline" onClick={() => setMode("resolve")}>Resolve…</Button>
        <Button type="button" variant="outline" onClick={() => setMode("waive")}>Waive…</Button>
        <Button type="button" variant="outline" onClick={() => setMode("assign")}>Assign…</Button>
      </div>
      {mode === "waive" || mode === "resolve" ? (
        <div className="flex flex-wrap items-end gap-2">
          <label className="min-w-72 flex-1 text-xs text-ink-700 dark:text-ink-200">
            {mode === "waive" ? "Reason (required, applies to every selected issue)" : "Why these are resolved (required)"}
            <input className={cn(FIELD, "mt-1 w-full")} value={reason} onChange={(e) => setReason(e.target.value)} />
          </label>
          {mode === "waive" ? (
            <label className="text-xs text-ink-700 dark:text-ink-200">
              Waived until (default 90 days)
              <input type="date" className={cn(FIELD, "mt-1 block")} value={until} onChange={(e) => setUntil(e.target.value)} />
            </label>
          ) : null}
          <Button type="button" disabled={busy || !reason.trim()}
            onClick={() => void run(() => issuesApi.bulk(fingerprints, {
              action: "decision", state: mode === "waive" ? "waived" : "resolved",
              reason, waived_until: mode === "waive" ? until || null : null,
            }))}>
            Apply to {fingerprints.length}
          </Button>
        </div>
      ) : null}
      {mode === "assign" ? (
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-xs text-ink-700 dark:text-ink-200">
            Owner
            <select className={cn(FIELD, "mt-1 block")} value={owner} onChange={(e) => setOwner(e.target.value)}>
              <option value="">Unassigned</option>
              {assignees.map((a) => <option key={a.user_id} value={a.user_id}>{a.email}</option>)}
            </select>
          </label>
          <label className="text-xs text-ink-700 dark:text-ink-200">
            Due
            <input type="date" className={cn(FIELD, "mt-1 block")} value={due} onChange={(e) => setDue(e.target.value)} />
          </label>
          <Button type="button" disabled={busy}
            onClick={() => void run(() => issuesApi.bulk(fingerprints, { action: "assign", owner_user_id: owner || null, due_date: due || null }))}>
            Assign {fingerprints.length}
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function IssuePanel({ fingerprint, canWrite, assignees, onClose, onChanged }: {
  fingerprint: string; canWrite: boolean; assignees: Assignee[]; onClose: () => void; onChanged: () => void;
}) {
  const { entity } = useEntity();
  const qc = useQueryClient();
  const key = ["issue", entity?.id, fingerprint];
  const detail = useQuery<IssueDetail>({ queryKey: key, queryFn: () => issuesApi.detail(fingerprint) });
  const [comment, setComment] = useState("");
  const [reason, setReason] = useState("");
  const [until, setUntil] = useState("");
  const [busy, setBusy] = useState(false);
  const [owner, setOwner] = useState<string | null>(null);
  const [due, setDue] = useState<string | null>(null);

  const f = detail.data?.finding;
  useEffect(() => {
    if (f) { setOwner(f.owner_user_id ?? ""); setDue(f.due_date ?? ""); }
  }, [f]);

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

  const download = async (id: string, name: string) => {
    try {
      const blob = await issuesApi.download(fingerprint, id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = name; a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      toast.error("Download failed", { description: e instanceof Error ? e.message : "" });
    }
  };

  const decisions = useMemo(() => (f ? ([
    { state: "acknowledged", label: "Mark in progress", needs: false },
    { state: "resolved", label: "Resolve", needs: true },
    { state: "waived", label: "Waive", needs: true },
    { state: "open", label: "Reopen", needs: false },
  ] as { state: IssueState; label: string; needs: boolean }[]).filter((d) => d.state !== f.state) : []), [f]);

  // Rendered into <body>: the page sits inside an animated (transformed)
  // wrapper, and a fixed element inside a transform is positioned against it
  // rather than the viewport.
  return createPortal(
    <div className="fixed inset-0 z-[70] flex justify-end bg-ink-950/30" role="dialog" aria-modal="true" aria-label="Issue detail"
      onClick={onClose}>
      <div className="h-full w-full max-w-xl overflow-y-auto bg-white p-5 shadow-2xl dark:bg-ink-900" onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <p className="font-mono text-xs text-ink-500">{f?.rule_id} · {f?.employee_id}</p>
            <h2 className="text-lg font-semibold text-ink-900 dark:text-white">{f?.rule_name ?? "Loading…"}</h2>
            {f ? <p className="text-sm text-ink-600 dark:text-ink-300">{f.employee_name ?? "—"}</p> : null}
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded-lg p-1 text-ink-500 hover:bg-ink-100 dark:hover:bg-white/10"><X size={18} /></button>
        </div>

        {!f ? <Loader2 className="animate-spin text-ink-400" /> : (
          <div className="space-y-5 text-sm">
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5">
              <dt className="text-ink-500">State</dt><dd><span className={cn("rounded-full px-2 py-0.5 text-xs font-semibold", STATE_TONE[f.state])}>{ISSUE_STATE_LABEL[f.state]}</span></dd>
              <dt className="text-ink-500">Severity</dt><dd>{f.severity}</dd>
              <dt className="text-ink-500">First seen</dt><dd>{monthLabel(f.first_seen_period)}</dd>
              <dt className="text-ink-500">Last seen</dt><dd>{monthLabel(f.last_seen_period)} · {f.occurrence_count} month(s)</dd>
              <dt className="text-ink-500">Impact</dt><dd className={!f.impact_calculated ? "italic text-ink-500" : ""}>{f.impact_calculated ? inr(f.last_financial_impact, 2) : "Impact not calculated"}</dd>
              {f.waiver_reason ? (<><dt className="text-ink-500">Waiver</dt><dd>{f.waiver_reason}{f.waived_until ? ` (until ${f.waived_until})` : ""}</dd></>) : null}
            </dl>
            <Link href={`/payroll/employee/${encodeURIComponent(f.employee_id)}`} className="text-xs font-semibold text-brand-700 hover:underline dark:text-brand-300">
              Open the employee in the latest run
            </Link>

            <section className="space-y-2">
              <h3 className="flex items-center gap-2 font-semibold text-ink-900 dark:text-white"><UserRound size={14} /> Owner and due date</h3>
              <div className="flex flex-wrap items-end gap-2">
                <select className={FIELD} aria-label="Owner" disabled={!canWrite} value={owner ?? ""} onChange={(e) => setOwner(e.target.value)}>
                  <option value="">Unassigned</option>
                  {assignees.map((a) => <option key={a.user_id} value={a.user_id}>{a.email}</option>)}
                </select>
                <input type="date" aria-label="Due date" className={FIELD} disabled={!canWrite} value={due ?? ""} onChange={(e) => setDue(e.target.value)} />
                {canWrite ? (
                  <Button type="button" variant="outline" disabled={busy}
                    onClick={() => void act(() => issuesApi.assign(fingerprint, { owner_user_id: owner || null, due_date: due || null }), "Assignment saved")}>
                    <CalendarClock size={14} /> Save
                  </Button>
                ) : null}
              </div>
              {f.overdue ? <p className="flex items-center gap-1 text-xs font-semibold text-danger-700"><AlertTriangle size={12} /> Overdue</p> : null}
            </section>

            {canWrite ? (
              <section className="space-y-2">
                <h3 className="font-semibold text-ink-900 dark:text-white">Decision</h3>
                <input className={cn(FIELD, "w-full")} placeholder="Reason (required to resolve or waive)" value={reason} onChange={(e) => setReason(e.target.value)} />
                <label className="block text-xs text-ink-600 dark:text-ink-300">
                  Waive until (a waiver always expires — 90 days if left blank)
                  <input type="date" className={cn(FIELD, "mt-1 block")} value={until} onChange={(e) => setUntil(e.target.value)} />
                </label>
                <div className="flex flex-wrap gap-2">
                  {decisions.map((d) => (
                    <Button key={d.state} type="button" variant={d.state === "resolved" ? "default" : "outline"}
                      disabled={busy || (d.needs && !reason.trim())}
                      onClick={() => void act(() => issuesApi.decide(fingerprint, {
                        state: d.state, reason: reason || null, waived_until: d.state === "waived" ? until || null : null,
                      }), `${d.label} — saved`)}>
                      {d.label}
                    </Button>
                  ))}
                </div>
              </section>
            ) : null}

            <section className="space-y-2">
              <h3 className="flex items-center gap-2 font-semibold text-ink-900 dark:text-white"><MessageSquare size={14} /> Comments</h3>
              {detail.data!.comments.length === 0 ? <p className="text-xs text-ink-500">No comments yet.</p> : (
                <ul className="space-y-2">
                  {detail.data!.comments.map((c) => (
                    <li key={c.id} className="rounded-lg bg-ink-50 px-3 py-2 dark:bg-white/[0.04]">
                      <p className="whitespace-pre-wrap text-ink-800 dark:text-ink-100">{c.body}</p>
                      <p className="mt-1 text-[11px] text-ink-500">{c.author_email} · {c.created_at ? new Date(c.created_at).toLocaleString("en-IN") : ""}</p>
                    </li>
                  ))}
                </ul>
              )}
              {canWrite ? (
                <div className="flex gap-2">
                  <textarea className={cn(FIELD, "flex-1")} rows={2} placeholder="Add a comment" value={comment} onChange={(e) => setComment(e.target.value)} />
                  <Button type="button" disabled={busy || !comment.trim()}
                    onClick={() => void act(() => issuesApi.comment(fingerprint, comment), "Comment added")}>Post</Button>
                </div>
              ) : null}
            </section>

            <section className="space-y-2">
              <h3 className="flex items-center gap-2 font-semibold text-ink-900 dark:text-white"><Paperclip size={14} /> Evidence</h3>
              {detail.data!.attachments.length === 0 ? <p className="text-xs text-ink-500">No files attached.</p> : (
                <ul className="space-y-1">
                  {detail.data!.attachments.map((a) => (
                    <li key={a.id} className="flex items-center justify-between gap-2 text-xs">
                      <span className="min-w-0 truncate">{a.filename} · {a.size < 1024 ? `${a.size} bytes` : `${Math.round(a.size / 1024).toLocaleString("en-IN")} KB`} · {a.uploaded_by_email}</span>
                      <button type="button" className="inline-flex items-center gap-1 font-semibold text-brand-700 dark:text-brand-300"
                        onClick={() => void download(a.id, a.filename)}><Download size={12} /> Download</button>
                    </li>
                  ))}
                </ul>
              )}
              {canWrite ? (
                <label className="block text-xs text-ink-600 dark:text-ink-300">
                  Attach a file (PDF, image, spreadsheet, CSV or text; up to 5 MB)
                  <input type="file" className="mt-1 block text-xs" disabled={busy}
                    accept=".pdf,.png,.jpg,.jpeg,.xlsx,.xls,.csv,.txt"
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (file) void act(() => issuesApi.attach(fingerprint, file), "File attached");
                      e.target.value = "";
                    }} />
                </label>
              ) : null}
            </section>

            <section className="space-y-1">
              <h3 className="font-semibold text-ink-900 dark:text-white">History</h3>
              {detail.data!.history.length === 0 ? <p className="text-xs text-ink-500">No decisions yet.</p> : (
                <ul className="space-y-1 text-xs text-ink-600 dark:text-ink-300">
                  {detail.data!.history.map((h) => (
                    <li key={h.id}>
                      {h.created_at ? new Date(h.created_at).toLocaleString("en-IN") : "—"} · {h.from_state ?? "new"} → {h.to_state}
                      {" "}by {h.actor_email ?? "the system"}{h.reason ? ` — ${h.reason}` : ""}
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}

export default function IssuesPage() {
  return (
    <Suspense fallback={<Skeleton className="h-96 w-full rounded-2xl" />}>
      <IssuesContent />
    </Suspense>
  );
}
