"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowDown, ArrowUp, Ban, FlaskConical, PlayCircle, Plus, Save, Send, Trash2 } from "lucide-react";

import { useEntity } from "@/context/EntityContext";
import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { BackLink } from "@/components/layout/BackLink";
import { ConfirmAction, TestButton } from "@/components/studio/Controls";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { StudioNav } from "@/components/studio/StudioNav";
import { RunLine, fmtTime } from "@/components/studio/RunBits";
import { issuesApi } from "@/lib/issues";
import {
  studioConnApi,
  studioFlowApi,
  studioHookApi,
  type DryRun,
  type WorkflowAction,
  type WorkflowCatalogue,
  type WorkflowDefinition,
} from "@/lib/studio";
import { cn } from "@/lib/utils";

const FIELD =
  "w-full rounded-lg border border-ink-200 bg-white px-2.5 py-1.5 text-sm text-ink-900";
const MANAGE = new Set(["owner", "manager"]);
const WRITE = new Set(["owner", "manager", "analyst"]);

/** Fields a condition can test, by trigger — what that event's data holds. */
const EVENT_FIELDS: Record<string, string[]> = {
  "import.completed": ["data.object_type", "data.kind", "data.status", "data.counts.received", "data.counts.rejected", "data.period_month", "data.batch_id"],
  "inputs.ready": ["data.period_month", "data.inputs.register", "data.inputs.master", "data.inputs.attendance"],
  "validation.completed": ["data.period_month", "data.run_id"],
  "validation.failed": ["data.period_month", "data.error_code"],
  "finding.state_changed": ["data.rule_id", "data.from", "data.to"],
  "period.submitted": ["data.period_month", "data.state"],
  "period.signed_off": ["data.period_month", "data.state"],
  "period.reopened": ["data.period_month", "data.state"],
  "inbound.received": ["data.endpoint_id", "data.run_id"],
};
const SAMPLE: Record<string, Record<string, unknown>> = {
  "import.completed": { data: { object_type: "employee_master", kind: "sync", status: "partially_completed", counts: { received: 120, rejected: 3 }, period_month: "2026-06-01" } },
  "inputs.ready": { data: { period_month: "2026-06-01", inputs: { register: 120, master: 118 } } },
  "validation.completed": { data: { period_month: "2026-06-01", run_id: "(a run id)" } },
  "validation.failed": { data: { period_month: "2026-06-01", error_code: "empty_register" } },
  "finding.state_changed": { data: { rule_id: "STAT-001", from: "open", to: "acknowledged" } },
  "period.signed_off": { data: { period_month: "2026-06-01", state: "signed_off" } },
};
const PERIODS = [["context", "The month the trigger names"], ["current_month", "This month"], ["previous_month", "Last month"]];

export default function WorkflowBuilderPage() {
  const { id } = useParams<{ id: string }>();
  const { entity, activeRole } = useEntity();
  const qc = useQueryClient();
  const canWrite = WRITE.has(activeRole ?? "");
  const canManage = MANAGE.has(activeRole ?? "");
  const q = useQuery({ queryKey: ["studio-workflow", entity?.id, id], queryFn: () => studioFlowApi.get(id), enabled: !!entity && !!id, retry: false,
    refetchInterval: (query) => (query.state.data?.recent_runs?.some((r) => ["queued", "running"].includes(r.status)) ? 3000 : false) });
  const cat = useQuery({ queryKey: ["studio-flow-catalogue", entity?.id], queryFn: studioFlowApi.catalogue, enabled: !!entity });
  const [def, setDef] = useState<WorkflowDefinition | null>(null);
  const [limits, setLimits] = useState({ max_runs_per_hour: 20, timeout_minutes: 120 });
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState<"publish" | "disable" | null>(null);
  const [month, setMonth] = useState("");
  const [sample, setSample] = useState("");
  const [dry, setDry] = useState<DryRun | null>(null);

  useEffect(() => {
    if (q.data) {
      setDef(q.data.definition);
      setLimits({ max_runs_per_hour: q.data.max_runs_per_hour, timeout_minutes: q.data.timeout_minutes });
    }
  }, [q.data]);
  useEffect(() => { if (def) setSample(JSON.stringify(SAMPLE[def.trigger.type] ?? { data: {} }, null, 2)); }, [def?.trigger.type]); // eslint-disable-line react-hooks/exhaustive-deps

  if (q.error) return <AlertBanner variant="error" title="This workflow could not be opened">It may belong to another company. <Link className="underline" href="/studio/workflows">All workflows</Link></AlertBanner>;
  const w = q.data;
  if (!w || !def || !cat.data) return <Skeleton className="h-96 w-full rounded-2xl" />;
  const editable = canWrite;

  const act = async <T,>(fn: () => Promise<T>, done: string): Promise<T | null> => {
    setBusy(true);
    try { const out = await fn(); toast.success(done); await qc.invalidateQueries({ queryKey: ["studio-workflow", entity?.id, id] }); return out; }
    catch (e) { toast.error("Refused", { description: e instanceof Error ? e.message : "" }); return null; }
    finally { setBusy(false); }
  };
  const save = () => act(() => studioFlowApi.update(w.id, { definition: def, ...limits }), "Saved");
  const setActions = (key: "actions" | "on_failure", list: WorkflowAction[]) => setDef({ ...def, [key]: list });
  const runDry = async () => {
    try {
      const parsed = sample.trim() ? JSON.parse(sample) : null;
      setDry(await studioFlowApi.dryRun(def, parsed, month ? `${month}-01` : undefined));
    } catch (e) { toast.error("Dry run refused", { description: e instanceof Error ? e.message : "" }); }
  };

  return (
    <div className="space-y-5">
      <BackLink fallback="/studio/workflows">All workflows</BackLink>
      <PageHeader eyebrow="PeopleOps Studio · workflow"
        title={<span className="flex flex-wrap items-center gap-3">{w.name}
          <Badge variant={w.status === "active" ? "success" : w.status === "draft" ? "warning" : "secondary"}>{w.status}</Badge>
          {w.active_version ? <span className="font-mono text-base text-ink-500">v{w.active_version} in force</span> : null}
          {w.has_changes && w.active_version ? <Badge variant="warning">unpublished changes</Badge> : null}</span>}
        description={w.description ?? undefined}
        actions={<div className="flex flex-wrap gap-2">
          {editable ? <Button variant="outline" disabled={busy} onClick={() => void save()}><Save size={14} /> Save draft</Button> : null}
          {canManage ? <Button disabled={busy} onClick={() => setConfirm("publish")}><Send size={14} /> Publish</Button> : null}
          {canManage && w.active_version ? (w.status === "active"
            ? <Button variant="destructive-outline" disabled={busy} onClick={() => setConfirm("disable")}>Disable</Button>
            : <Button variant="outline" disabled={busy} onClick={() => void act(() => studioFlowApi.enable(w.id, true), "Enabled")}>Enable</Button>) : null}
        </div>} />
      <StudioNav />
      <ConfirmAction
        open={confirm === "publish"}
        onClose={() => setConfirm(null)}
        tone="primary"
        title={`Publish ${w.name} as version ${(w.active_version ?? 0) + 1}?`}
        consequence={<>The editor&apos;s current definition is saved, checked again, and put in force, and the workflow is enabled: from now its trigger starts runs with this version. Where your organisation requires it, the publisher must be someone other than the last editor.</>}
        confirmLabel="Publish and enable"
        onConfirm={() => act(async () => { await studioFlowApi.update(w.id, { definition: def, ...limits }); return studioFlowApi.publish(w.id); }, "Published — now in force")}
      />
      <ConfirmAction
        open={confirm === "disable"}
        onClose={() => setConfirm(null)}
        title={`Disable ${w.name}?`}
        consequence="Its trigger stops starting runs, and a schedule is cleared, until it is enabled again. The published version is kept."
        confirmLabel="Disable workflow"
        onConfirm={() => act(() => studioFlowApi.enable(w.id, false), "Disabled")}
      />

      {w.last_skip ? <AlertBanner variant="warning" title={`Last skipped ${fmtTime(w.last_skip.at)}`}>{w.last_skip.reason}</AlertBanner> : null}
      {!w.active_version ? <AlertBanner variant="info" title="Draft">Nothing runs until an owner or manager publishes it. Publishing re-checks every stream, webhook and person it names.</AlertBanner> : null}

      <Card><CardContent className="space-y-3 py-5">
        <h2 className="text-base font-semibold text-ink-900">1 · When</h2>
        <select aria-label="Trigger" disabled={!editable} className={cn(FIELD, "max-w-md")} value={def.trigger.type}
          onChange={(e) => setDef({ ...def, trigger: { type: e.target.value, ...(e.target.value === "schedule" ? { schedule: { every: "day", at: "07:00", timezone: "Asia/Kolkata" } } : {}), ...(e.target.value === "inputs.ready" ? { required: ["register", "master"] } : {}) } })}>
          {Object.entries(cat.data.triggers).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        {def.trigger.type === "schedule" ? <ScheduleEditor value={def.trigger.schedule ?? {}} disabled={!editable} onChange={(schedule) => setDef({ ...def, trigger: { ...def.trigger, schedule } })} /> : null}
        {def.trigger.type === "inputs.ready" ? (
          <Checks label="Ready when present" options={cat.data.inputs} value={def.trigger.required ?? []} disabled={!editable} onChange={(required) => setDef({ ...def, trigger: { ...def.trigger, required } })} />
        ) : null}
        {w.next_run_at ? <p className="text-xs text-ink-500">Next run {fmtTime(w.next_run_at)}.</p> : null}
      </CardContent></Card>

      <Card><CardContent className="space-y-3 py-5">
        <div className="flex items-center justify-between"><h2 className="text-base font-semibold text-ink-900">2 · Only if</h2>
          {editable && EVENT_FIELDS[def.trigger.type] ? <button type="button" onClick={() => setDef({ ...def, conditions: [...def.conditions, { field: EVENT_FIELDS[def.trigger.type][0], op: "eq", value: "" }] })} className="inline-flex items-center gap-1 rounded-lg border border-brand-300 px-2.5 py-1 text-xs text-brand-700"><Plus size={12} /> Condition</button> : null}</div>
        {def.conditions.length === 0 ? <p className="text-sm text-ink-500">Always — every time the trigger happens.</p> : null}
        <datalist id="event-fields">{(EVENT_FIELDS[def.trigger.type] ?? []).map((f) => <option key={f} value={f} />)}</datalist>
        {def.conditions.map((c, i) => (
          <div key={i} className="grid gap-2 md:grid-cols-[1fr_10rem_1fr_auto]">
            <input list="event-fields" aria-label="Condition field" disabled={!editable} className={FIELD} value={c.field} onChange={(e) => setDef({ ...def, conditions: def.conditions.map((x, j) => (j === i ? { ...x, field: e.target.value } : x)) })} />
            <select aria-label="Operator" disabled={!editable} className={FIELD} value={c.op} onChange={(e) => setDef({ ...def, conditions: def.conditions.map((x, j) => (j === i ? { ...x, op: e.target.value } : x)) })}>
              {cat.data.ops.map((o) => <option key={o} value={o}>{o.replace("_", " ")}</option>)}</select>
            <input aria-label="Value" disabled={!editable || ["present", "absent"].includes(c.op)} className={FIELD} value={String(c.value ?? "")} onChange={(e) => setDef({ ...def, conditions: def.conditions.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)) })} placeholder={["in", "not_in"].includes(c.op) ? "a, b, c" : "value"} />
            {editable ? <button type="button" aria-label={`Remove condition ${i + 1}`} className="inline-flex h-7 w-7 items-center justify-center rounded-md text-ink-600 hover:bg-ink-100 hover:text-ink-900 disabled:opacity-30" onClick={() => setDef({ ...def, conditions: def.conditions.filter((_, j) => j !== i) })}><Trash2 size={14} /></button> : <span />}
          </div>
        ))}
        <p className="text-xs text-ink-500">A value that cannot be compared (text against a number, or missing) makes the condition false — never true by accident.</p>
      </CardContent></Card>

      <StepsEditor title="3 · Do, in order" catalogue={cat.data} steps={def.actions} editable={editable} onChange={(l) => setActions("actions", l)} />
      <StepsEditor title="If a step fails" catalogue={cat.data} steps={def.on_failure} editable={editable} failureBranch onChange={(l) => setActions("on_failure", l)} />

      <Card><CardContent className="grid gap-3 py-5 md:grid-cols-3">
        <label className="text-xs font-semibold text-ink-700">At most this many runs per hour<input disabled={!editable} className={cn(FIELD, "mt-1")} value={limits.max_runs_per_hour} onChange={(e) => setLimits({ ...limits, max_runs_per_hour: Number(e.target.value) || 1 })} /></label>
        <label className="text-xs font-semibold text-ink-700">Whole run times out after (minutes)<input disabled={!editable} className={cn(FIELD, "mt-1")} value={limits.timeout_minutes} onChange={(e) => setLimits({ ...limits, timeout_minutes: Number(e.target.value) || 5 })} /></label>
        <div className="text-xs text-ink-500"><Ban size={12} className="inline" /> Not available to any workflow: {Object.entries(cat.data.not_available).map(([k, v]) => <span key={k} className="block">{k.replace(/_/g, " ")} — {v}</span>)}</div>
      </CardContent></Card>

      <Card><CardContent className="space-y-3 py-5">
        <h2 className="flex items-center gap-2 text-base font-semibold text-ink-900"><FlaskConical size={16} /> Dry run and run now</h2>
        <div className="grid gap-3 md:grid-cols-[1fr_12rem]">
          <label className="text-xs font-semibold text-ink-700">Sample event (what the trigger would carry)
            <textarea aria-label="Sample event" className={cn(FIELD, "mt-1 h-28 font-mono text-xs")} value={sample} onChange={(e) => setSample(e.target.value)} /></label>
          <div className="space-y-2">
            <label className="block text-xs font-semibold text-ink-700">Month<input type="month" aria-label="Month" className={cn(FIELD, "mt-1")} value={month} onChange={(e) => setMonth(e.target.value)} /></label>
            <TestButton className="w-full" onClick={() => void runDry()}>Dry run — changes nothing</TestButton>
            {canManage && w.status === "active" ? <button type="button" disabled={busy} onClick={() => void act(() => studioFlowApi.run(w.id, month ? `${month}-01` : undefined), "Run started")} className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg bg-brand-600 px-3 py-1.5 text-sm font-semibold text-white"><PlayCircle size={14} /> Run now (v{w.active_version})</button> : null}
          </div>
        </div>
        {dry ? (
          <div className="rounded-xl border border-ink-200 p-3 text-sm" data-testid="dry-run">
            <p className="font-semibold">{dry.would_run ? "It would run." : "It would not run: a condition is false."}</p>
            {dry.conditions.map((c, i) => <p key={i} className="text-xs">{c.holds ? "✓" : "✗"} {c.field} {c.op} {String(c.value ?? "")} — the event has <code>{JSON.stringify(c.actual)}</code></p>)}
            <ol className="mt-2 list-decimal space-y-1 pl-5 text-xs">{dry.steps.map((s) => (
              <li key={s.step}>{s.label}{s.period ? ` · ${s.period.slice(0, 7)}` : ""}{s.stream ? ` · stream ${s.stream}` : ""}{s.owner ? ` · to ${s.owner}` : ""}
                {s.recipients ? ` · to ${s.recipients.join(", ") || "nobody"}` : ""}{s.title ? ` · “${s.title}”` : ""}
                {s.warning ? <span className="block text-warning-800">{s.warning}</span> : null}</li>))}</ol>
            {dry.failure_branch.length ? <p className="mt-1 text-xs text-ink-500">If a step fails: {dry.failure_branch.join(", ")}.</p> : null}
          </div>
        ) : null}
      </CardContent></Card>

      <Card><CardContent className="py-5">
        <h2 className="text-base font-semibold text-ink-900">Runs</h2>
        {w.recent_runs?.length ? <ul className="divide-y divide-ink-100">{w.recent_runs.map((r) => <RunLine key={r.id} run={r} />)}</ul> : <p className="text-sm text-ink-500">Not run yet.</p>}
      </CardContent></Card>
    </div>
  );
}

function Checks({ label, options, value, disabled, onChange }: { label: string; options: readonly string[]; value: string[]; disabled?: boolean; onChange: (v: string[]) => void }) {
  return (
    <div className="text-xs"><span className="font-semibold text-ink-700">{label}</span>
      <div className="mt-1 flex flex-wrap gap-3">{options.map((o) => (
        <label key={o} className="flex items-center gap-1"><input type="checkbox" disabled={disabled} checked={value.includes(o)} onChange={() => onChange(value.includes(o) ? value.filter((x) => x !== o) : [...value, o])} /> {o.replace(/_/g, " ")}</label>))}</div></div>
  );
}

function ScheduleEditor({ value, disabled, onChange }: { value: Record<string, unknown>; disabled?: boolean; onChange: (v: Record<string, unknown>) => void }) {
  return (
    <div className="grid gap-2 md:grid-cols-4">
      <select aria-label="Every" disabled={disabled} className={FIELD} value={String(value.every ?? "day")} onChange={(e) => onChange({ ...value, every: e.target.value })}>
        <option value="hour">Every hour</option><option value="day">Every day</option><option value="week">Every week</option></select>
      <input aria-label="At" disabled={disabled} className={FIELD} value={String(value.at ?? "07:00")} onChange={(e) => onChange({ ...value, at: e.target.value })} />
      {value.every === "week" ? <select aria-label="Weekday" disabled={disabled} className={FIELD} value={String(value.weekday ?? 0)} onChange={(e) => onChange({ ...value, weekday: Number(e.target.value) })}>
        {["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"].map((d, i) => <option key={d} value={i}>{d}</option>)}</select> : <span />}
      <input aria-label="Time zone" disabled={disabled} className={FIELD} value={String(value.timezone ?? "Asia/Kolkata")} onChange={(e) => onChange({ ...value, timezone: e.target.value })} />
    </div>
  );
}

function StepsEditor({ title, catalogue, steps, editable, failureBranch, onChange }: {
  title: string; catalogue: WorkflowCatalogue; steps: WorkflowAction[]; editable: boolean; failureBranch?: boolean; onChange: (l: WorkflowAction[]) => void;
}) {
  const types = Object.entries(catalogue.actions).filter(([, a]) => !failureBranch || a.failure_branch);
  const set = (i: number, patch: Partial<WorkflowAction>) => onChange(steps.map((s, j) => (j === i ? { ...s, ...patch } : s)));
  const move = (i: number, d: number) => { const next = [...steps]; const [x] = next.splice(i, 1); next.splice(i + d, 0, x); onChange(next); };
  return (
    <Card><CardContent className="space-y-3 py-5">
      <div className="flex items-center justify-between"><h2 className="text-base font-semibold text-ink-900">{title}</h2>
        {editable ? <button type="button" onClick={() => onChange([...steps, { type: failureBranch ? "notify" : types[0][0], params: failureBranch ? { roles: ["owner"], title: "{{workflow}} failed", severity: "error" } : {} }])} className="inline-flex items-center gap-1 rounded-lg border border-brand-300 px-2.5 py-1 text-xs text-brand-700"><Plus size={12} /> Step</button> : null}</div>
      {steps.length === 0 ? <p className="text-sm text-ink-500">{failureBranch ? "Nothing — the run fails and says which step and why." : "No steps."}</p> : null}
      {steps.map((s, i) => (
        <div key={i} className="space-y-2 rounded-xl border border-ink-200 p-3" data-testid={failureBranch ? "failure-step" : "step"}>
          <div className="grid gap-2 md:grid-cols-[2rem_1fr_1fr_6rem_7rem_auto]">
            <span className="pt-1.5 text-sm font-semibold text-ink-500">{i + 1}</span>
            <select aria-label="Action" disabled={!editable} className={FIELD} value={s.type} onChange={(e) => set(i, { type: e.target.value, params: {} })}>
              {types.map(([k, a]) => <option key={k} value={k}>{a.label}</option>)}</select>
            <input aria-label="Step label" disabled={!editable} className={FIELD} value={s.label ?? ""} onChange={(e) => set(i, { label: e.target.value })} placeholder="Label (optional)" />
            <label className="text-[11px] text-ink-500">Retries<input aria-label="Retries" disabled={!editable} className={FIELD} value={s.retries ?? 0} onChange={(e) => set(i, { retries: Number(e.target.value) || 0 })} /></label>
            <label className="text-[11px] text-ink-500">Timeout (min)<input aria-label="Timeout" disabled={!editable} className={FIELD} value={s.timeout_minutes ?? 60} onChange={(e) => set(i, { timeout_minutes: Number(e.target.value) || 60 })} /></label>
            {editable ? <span className="flex items-start gap-1 pt-1">
              <button type="button" aria-label={`Move step ${i + 1} up`} className="inline-flex h-7 w-7 items-center justify-center rounded-md text-ink-600 hover:bg-ink-100 hover:text-ink-900 disabled:opacity-30" disabled={i === 0} onClick={() => move(i, -1)}><ArrowUp size={14} /></button>
              <button type="button" aria-label={`Move step ${i + 1} down`} className="inline-flex h-7 w-7 items-center justify-center rounded-md text-ink-600 hover:bg-ink-100 hover:text-ink-900 disabled:opacity-30" disabled={i === steps.length - 1} onClick={() => move(i, 1)}><ArrowDown size={14} /></button>
              <button type="button" aria-label={`Remove step ${i + 1}`} className="inline-flex h-7 w-7 items-center justify-center rounded-md text-ink-600 hover:bg-ink-100 hover:text-danger-700 disabled:opacity-30" onClick={() => onChange(steps.filter((_, j) => j !== i))}><Trash2 size={14} /></button></span> : <span />}
          </div>
          <p className="text-xs text-ink-500">{catalogue.actions[s.type]?.help}</p>
          <ParamsEditor action={s} catalogue={catalogue} disabled={!editable} onChange={(params) => set(i, { params })} />
        </div>
      ))}
    </CardContent></Card>
  );
}

function ParamsEditor({ action, catalogue, disabled, onChange }: { action: WorkflowAction; catalogue: WorkflowCatalogue; disabled: boolean; onChange: (p: Record<string, unknown>) => void }) {
  const { entity } = useEntity();
  const p = action.params ?? {};
  const set = (k: string, v: unknown) => onChange({ ...p, [k]: v });
  const conns = useQuery({ queryKey: ["studio-connections", entity?.id], queryFn: studioConnApi.list, enabled: !!entity && action.type === "sync" });
  const hooks = useQuery({ queryKey: ["studio-webhooks", entity?.id], queryFn: studioHookApi.list, enabled: !!entity && action.type === "webhook" });
  const people = useQuery({ queryKey: ["finding-assignees", entity?.id], queryFn: issuesApi.assignees, enabled: !!entity && ["assign_findings", "notify", "report"].includes(action.type) });
  const streams = useMemo(() => (conns.data ?? []).flatMap((c) => c.streams.map((s) => ({ id: s.id, label: `${c.name} · ${s.name}` }))), [conns.data]);
  const period = (
    <label className="text-xs font-semibold text-ink-700">Month<select aria-label="Step month" disabled={disabled} className={cn(FIELD, "mt-1")} value={String(p.period ?? "context")} onChange={(e) => set("period", e.target.value)}>
      {PERIODS.map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
  );
  if (action.type === "sync") return (
    <div className="grid gap-2 md:grid-cols-2">
      <select aria-label="Stream" disabled={disabled} className={FIELD} value={String(p.stream_id ?? "")} onChange={(e) => set("stream_id", e.target.value)}>
        <option value="">Choose a stream</option>{streams.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}</select>
      <label className="flex items-center gap-1.5 text-xs"><input type="checkbox" disabled={disabled} checked={!!p.fail_on_rejections} onChange={(e) => set("fail_on_rejections", e.target.checked)} /> Fail the workflow if any record is rejected (otherwise it continues, marked partial)</label>
    </div>
  );
  if (action.type === "check_readiness") return (
    <div className="grid gap-2 md:grid-cols-[1fr_16rem]"><Checks label="Required" options={catalogue.inputs} value={(p.required as string[]) ?? ["register", "master"]} disabled={disabled} onChange={(v) => set("required", v)} />{period}</div>
  );
  if (action.type === "start_validation") return (
    <div className="grid gap-2 md:grid-cols-[16rem_1fr]">{period}
      <label className="flex items-center gap-1.5 self-end pb-2 text-xs"><input type="checkbox" disabled={disabled} checked={!!p.fail_on_critical} onChange={(e) => set("fail_on_critical", e.target.checked)} /> Take the failure branch if validation finds critical findings</label></div>
  );
  if (action.type === "assign_findings") return (
    <div className="grid gap-2 md:grid-cols-4">
      <select aria-label="Owner" disabled={disabled} className={FIELD} value={String(p.owner_user_id ?? "")} onChange={(e) => set("owner_user_id", e.target.value)}>
        <option value="">Assign to…</option>{(people.data ?? []).map((a) => <option key={a.user_id} value={a.user_id}>{a.email}</option>)}</select>
      <label className="text-xs text-ink-500">Due in days<input aria-label="Due in days" disabled={disabled} className={FIELD} value={String(p.due_in_days ?? 5)} onChange={(e) => set("due_in_days", Number(e.target.value) || 0)} /></label>
      <Checks label="Severities" options={catalogue.severities} value={(p.severities as string[]) ?? ["CRITICAL", "WARNING"]} disabled={disabled} onChange={(v) => set("severities", v)} />
      {period}
    </div>
  );
  if (action.type === "notify" || action.type === "report") return (
    <div className="grid gap-2 md:grid-cols-2">
      <Checks label="Roles" options={catalogue.roles} value={(p.roles as string[]) ?? []} disabled={disabled} onChange={(v) => set("roles", v)} />
      <label className="text-xs font-semibold text-ink-700">People<select multiple aria-label="People" disabled={disabled} className={cn(FIELD, "mt-1 h-16")} value={(p.user_ids as string[]) ?? []}
        onChange={(e) => set("user_ids", Array.from(e.target.selectedOptions).map((o) => o.value))}>
        {(people.data ?? []).map((a) => <option key={a.user_id} value={a.user_id}>{a.email}</option>)}</select></label>
      <input aria-label="Notification title" disabled={disabled} className={FIELD} value={String(p.title ?? "")} onChange={(e) => set("title", e.target.value)} placeholder="Title — {{period}}, {{workflow}}, {{counts.rejected}}" />
      <select aria-label="Severity" disabled={disabled} className={FIELD} value={String(p.severity ?? "info")} onChange={(e) => set("severity", e.target.value)}>
        <option value="info">Information</option><option value="warning">Warning</option><option value="error">Error</option></select>
      <textarea aria-label="Notification message" disabled={disabled} className={cn(FIELD, "h-14 md:col-span-2")} value={String(p.body ?? "")} onChange={(e) => set("body", e.target.value)} placeholder="Message (optional). Values in {{double braces}} are filled in; nothing is evaluated." />
      {action.type === "report" ? <select aria-label="Report" disabled={disabled} className={FIELD} value={String(p.report ?? "")} onChange={(e) => set("report", e.target.value)}>
        <option value="">Which report</option>{Object.entries(catalogue.reports).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select> : null}
      {action.type === "report" ? <p className="self-center text-xs text-ink-500">A link, not an attachment: the page checks each reader&apos;s own access.</p> : null}
    </div>
  );
  if (action.type === "webhook") return (
    <div className="grid gap-2 md:grid-cols-2">
      <select aria-label="Webhook" disabled={disabled} className={FIELD} value={String(p.webhook_id ?? "")} onChange={(e) => set("webhook_id", e.target.value)}>
        <option value="">Choose a webhook</option>{(hooks.data ?? []).map((h) => <option key={h.id} value={h.id}>{h.name}</option>)}</select>
      <input aria-label="Webhook message" disabled={disabled} className={FIELD} value={String(p.message ?? "")} onChange={(e) => set("message", e.target.value)} placeholder="Short message (ids only are sent besides this)" />
    </div>
  );
  return null;
}
