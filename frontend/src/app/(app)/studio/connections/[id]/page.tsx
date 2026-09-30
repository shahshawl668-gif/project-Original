"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Link2, PlayCircle, Plus, RefreshCcw, Undo2 } from "lucide-react";

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
import { HealthBadge, RunLine, fmtTime } from "@/components/studio/RunBits";
import { AUTH_LABEL, OBJECT_LABEL, studioConnApi, studioMapApi, type Connection, type Stream } from "@/lib/studio";
import { cn } from "@/lib/utils";

const FIELD =
  "w-full rounded-lg border border-ink-200 bg-white px-3 py-2 text-sm text-ink-900";
const MANAGE = new Set(["owner", "manager"]);
const WRITE = new Set(["owner", "manager", "analyst"]);

export default function ConnectionPage() {
  const { id } = useParams<{ id: string }>();
  const { entity, activeRole } = useEntity();
  const qc = useQueryClient();
  const canManage = MANAGE.has(activeRole ?? "");
  const canWrite = WRITE.has(activeRole ?? "");
  const q = useQuery({ queryKey: ["studio-connection", entity?.id, id], queryFn: () => studioConnApi.get(id), enabled: !!entity && !!id, retry: false,
    refetchInterval: (query) => (query.state.data?.recent_runs?.some((r) => ["queued", "running"].includes(r.status)) ? 3000 : false) });
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [creds, setCreds] = useState<Record<string, string>>({});
  const [confirm, setConfirm] = useState<{ kind: "disable" } | { kind: "replace" } | { kind: "reset"; stream: Stream } | null>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: ["studio-connection", entity?.id, id] });

  if (q.error) {
    return <div className="space-y-4"><PageHeader eyebrow="PeopleOps Studio" title="Connection" />
      <AlertBanner variant="error" title="This connection could not be opened">It may belong to another company. <Link href="/studio/connections" className="underline">All connections</Link></AlertBanner></div>;
  }
  const c = q.data;
  if (!c) return <Skeleton className="h-96 w-full rounded-2xl" />;

  const act = async (fn: () => Promise<unknown>, done?: string) => {
    setBusy(true);
    try { const out = await fn(); if (done) toast.success(done); await refresh(); return out; }
    catch (e) { toast.error("Refused", { description: e instanceof Error ? e.message : "" }); return null; }
    finally { setBusy(false); }
  };
  const test = async (streamId?: string) => {
    const r = await act(() => studioConnApi.test(c.id, streamId)) as { ok: boolean; message: string } | null;
    if (r) (r.ok ? toast.success : toast.error)(r.ok ? "Connection works" : "Connection failed", { description: r.message });
  };
  const connect = async () => {
    const r = await act(() => studioConnApi.oauthStart(c.id, `${window.location.origin}/studio/connections/oauth`)) as { authorize_url: string } | null;
    if (r) window.location.assign(r.authorize_url);
  };

  return (
    <div className="space-y-5">
      <BackLink fallback="/studio/connections">All connections</BackLink>
      <PageHeader eyebrow="PeopleOps Studio · connection" title={<span className="flex flex-wrap items-center gap-3">{c.name} <HealthBadge health={c.health} />{c.status !== "active" ? <Badge variant="destructive">disabled</Badge> : null}</span>}
        description={`${c.system_kind.replace("_", " ")} · ${c.provider === "rest" ? c.base_url : "file uploads"} · ${c.environment} · inbound: the external system is the source of truth for what it sends`}
        actions={<div className="flex flex-wrap gap-2">
          {c.provider === "rest" && canWrite ? <TestButton size="default" disabled={busy} onClick={() => void test()}>Test connection</TestButton> : null}
          {c.auth_method === "oauth2_authorization_code" && canManage ? <Button disabled={busy} onClick={() => void connect()}><Link2 size={14} /> {c.oauth?.connected ? "Reconnect" : "Connect"}</Button> : null}
          {canManage ? (c.status === "active"
            ? <Button variant="destructive-outline" disabled={busy} onClick={() => setConfirm({ kind: "disable" })}>Disable</Button>
            : <Button variant="outline" disabled={busy} onClick={() => void act(() => studioConnApi.update(c.id, { status: "active" }), "Enabled")}>Enable</Button>) : null}
        </div>} />
      <StudioNav />

      {c.last_error && c.health === "failing" ? <AlertBanner variant="error" title="Last failure">{c.last_error} <span className="block text-xs">{fmtTime(c.last_failure_at)}</span></AlertBanner> : null}
      {c.auth_method === "oauth2_authorization_code" && !c.oauth?.connected ? <AlertBanner variant="warning" title="Not authorised yet">Press Connect and sign in at the provider. No password is entered here.</AlertBanner> : null}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card><CardContent className="space-y-2 py-5 text-sm">
          <h2 className="text-base font-semibold text-ink-900">Authentication</h2>
          <p>{AUTH_LABEL[c.auth_method] ?? c.auth_method}</p>
          {Object.entries(c.auth_config).filter(([k]) => k !== "extra_headers").map(([k, v]) => <p key={k} className="text-xs"><span className="text-ink-500">{k.replace(/_/g, " ")}:</span> <code>{String(v)}</code></p>)}
          {Object.entries(c.secret_hint).map(([k, v]) => <p key={k} className="text-xs"><span className="text-ink-500">{k.replace(/_/g, " ")}:</span> <code>{v ?? "not set"}</code></p>)}
          {c.oauth ? <p className="text-xs">OAuth: {c.oauth.connected ? `connected, token until ${fmtTime(c.oauth.expires_at)}${c.oauth.has_refresh_token ? ", refreshes itself" : ""}` : "not connected"}</p> : null}
          <p className="text-xs text-ink-500">Credentials last changed {fmtTime(c.secret_updated_at)}. They are stored encrypted and never shown again — only masked.</p>
          {canManage && Object.keys(c.secret_hint).length ? (
            <div className="space-y-2 border-t border-ink-100 pt-2">
              <p className="text-xs font-semibold">Rotate credentials</p>
              {Object.keys(c.secret_hint).map((k) => <input key={k} type="password" autoComplete="off" aria-label={`New ${k}`} placeholder={`New ${k.replace(/_/g, " ")}`} className={FIELD} value={creds[k] ?? ""} onChange={(e) => setCreds({ ...creds, [k]: e.target.value })} />)}
              <Button size="sm" variant="destructive-outline" disabled={busy || !Object.values(creds).some(Boolean)} onClick={() => setConfirm({ kind: "replace" })}>Replace credentials</Button>
            </div>
          ) : null}
        </CardContent></Card>
        <Card><CardContent className="space-y-2 py-5 text-sm">
          <h2 className="text-base font-semibold text-ink-900">Health</h2>
          <p>Last test: {fmtTime(c.last_tested_at)} {c.last_test_result ? (c.last_test_result.ok ? "— passed" : `— failed: ${c.last_test_result.message}`) : ""}</p>
          {c.last_test_result?.sample_fields?.length ? <p className="text-xs text-ink-500">Fields seen: {c.last_test_result.sample_fields.join(", ")}</p> : null}
          <p>Last success: {fmtTime(c.last_success_at)}</p>
          <p>Last failure: {fmtTime(c.last_failure_at)}</p>
          <h3 className="pt-2 text-sm font-semibold">Recent syncs</h3>
          {c.recent_runs?.length ? <ul className="divide-y divide-ink-100">{c.recent_runs.map((r) => <RunLine key={r.id} run={r} />)}</ul> : <p className="text-xs text-ink-500">None yet.</p>}
        </CardContent></Card>
      </div>

      <Card><CardContent className="space-y-3 py-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div><h2 className="text-base font-semibold text-ink-900">Streams</h2>
            <p className="text-xs text-ink-500">Each stream is one kind of record: where it is read from, how it is paged, which mapping reads it, and when it runs.</p></div>
          {canManage && !adding && c.provider === "rest" ? <Button onClick={() => setAdding(true)}><Plus size={14} /> Add stream</Button> : null}
        </div>
        {adding ? <StreamForm connection={c} onDone={() => { setAdding(false); void refresh(); }} /> : null}
        {c.streams.length === 0 && !adding ? <p className="text-sm text-ink-500">{c.provider === "rest" ? "No streams yet." : "File connections have no streams: upload files in Data mapping."}</p> : null}
        {c.streams.map((s) => editing === s.id ? (
          <StreamForm key={s.id} connection={c} stream={s} onDone={() => { setEditing(null); void refresh(); }} />
        ) : (
          <div key={s.id} className="rounded-xl border border-ink-200 p-3 text-sm">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <p className="font-semibold">{s.name} <Badge variant="secondary">{OBJECT_LABEL[s.object_type] ?? s.object_type}</Badge> {!s.enabled ? <Badge variant="destructive">off</Badge> : null}</p>
                <p className="text-xs text-ink-500"><code>GET {s.path}</code>{s.records_path ? <> → <code>{s.records_path}</code></> : null} · {s.pagination.type ?? "none"} paging{s.pagination.size ? ` (${s.pagination.size})` : ""} · {s.sync_mode}{s.sync_mode === "incremental" ? ` by ${s.watermark_field} → ?${s.watermark_param}=` : ""}</p>
                <p className="text-xs text-ink-500">Mapping: {s.mapping_key ? `${s.mapping_key}${s.mapping_version ? ` v${s.mapping_version} (pinned)` : " (version in force)"}` : "none — fields read by name"} · {s.import_options.mode} · deletions: {s.import_options.deletions} · period: {s.import_options.period}</p>
                <p className="text-xs text-ink-500">Schedule: {s.schedule.every ? `every ${s.schedule.every} at ${s.schedule.at} ${s.schedule.timezone}${s.schedule.every === "week" ? ` (weekday ${s.schedule.weekday})` : ""} · next ${fmtTime(s.next_run_at)}` : "manual only"} · up to {s.max_attempts} attempts</p>
                <p className="text-xs text-ink-500">Checkpoint: {s.checkpoint.watermark ? <code>{s.checkpoint.watermark}</code> : "none"}{s.checkpoint.at ? ` · committed ${fmtTime(s.checkpoint.at)}` : ""}{s.last_run_id ? <> · <Link className="underline" href={`/studio/runs/${s.last_run_id}`}>last run</Link></> : null}</p>
              </div>
              <div className="flex flex-wrap gap-2">
                {canWrite ? <TestButton disabled={busy} onClick={() => void test(s.id)}>Test</TestButton> : null}
                {canWrite ? <Button size="sm" disabled={busy || c.status !== "active"} onClick={() => void act(() => studioConnApi.syncNow(s.id), "Sync queued")}><PlayCircle size={13} /> Sync now</Button> : null}
                {canManage ? <Button size="sm" variant="ghost" onClick={() => setEditing(s.id)}>Edit</Button> : null}
                {canManage && s.checkpoint.watermark ? <Button size="sm" variant="destructive-outline" disabled={busy} onClick={() => setConfirm({ kind: "reset", stream: s })}><Undo2 size={13} /> Reset checkpoint</Button> : null}
              </div>
            </div>
          </div>
        ))}
        <ConfirmAction
          open={confirm?.kind === "disable"}
          onClose={() => setConfirm(null)}
          title={`Disable ${c.name}?`}
          consequence="Scheduled syncs on every stream stop and Sync now is refused until it is enabled again. Stored records and checkpoints are kept."
          confirmLabel="Disable connection"
          onConfirm={() => act(() => studioConnApi.update(c.id, { status: "disabled" }), "Disabled — schedules stop")}
        />
        <ConfirmAction
          open={confirm?.kind === "replace"}
          onClose={() => setConfirm(null)}
          title="Replace the stored credentials?"
          consequence="The next call uses the new values. The old ones are overwritten and cannot be shown or restored. Test the connection afterwards."
          confirmLabel="Replace credentials"
          onConfirm={() => act(() => studioConnApi.update(c.id, { secrets: creds }), "Credentials replaced").then(() => setCreds({}))}
        />
        <ConfirmAction
          open={confirm?.kind === "reset"}
          onClose={() => setConfirm(null)}
          title={confirm?.kind === "reset" ? `Reset the checkpoint on ${confirm.stream.name}?` : ""}
          consequence="The next sync fetches everything again instead of only what changed. Records already stored are reported unchanged, not duplicated, but the run takes longer."
          confirmLabel="Reset checkpoint"
          onConfirm={() => confirm?.kind === "reset" ? act(() => studioConnApi.resetCheckpoint(confirm.stream.id), "Checkpoint reset") : undefined}
        />
        <p className="text-xs text-ink-500"><RefreshCcw size={11} className="inline" /> The checkpoint moves only when a run stores its records, in the same transaction. A failed run leaves it where it was, so nothing is skipped; replaying stored records reports them unchanged, never duplicated.</p>
      </CardContent></Card>
    </div>
  );
}

function L({ label, children, span }: { label: string; children: React.ReactNode; span?: boolean }) {
  return <label className={cn("text-xs font-semibold text-ink-700", span && "md:col-span-2")}>{label}<div className="mt-1">{children}</div></label>;
}

function StreamForm({ connection, stream, onDone }: { connection: Connection; stream?: Stream; onDone: () => void }) {
  const { entity } = useEntity();
  const mappings = useQuery({ queryKey: ["studio-mappings", entity?.id], queryFn: studioMapApi.list, enabled: !!entity });
  const [f, setF] = useState({
    name: stream?.name ?? "Employees", object_type: stream?.object_type ?? "employee_master", path: stream?.path ?? "/employees",
    records_path: stream?.records_path ?? "data", pagination_type: stream?.pagination.type ?? "page", size: String(stream?.pagination.size ?? 500),
    param: stream?.pagination.param ?? "", size_param: stream?.pagination.size_param ?? "", cursor_path: stream?.pagination.cursor_path ?? "",
    sync_mode: stream?.sync_mode ?? "full", watermark_field: stream?.watermark_field ?? "", watermark_param: stream?.watermark_param ?? "",
    mapping_key: stream?.mapping_key ?? "", mode: stream?.import_options.mode ?? "upsert", deletions: stream?.import_options.deletions ?? "ignore",
    period: stream?.import_options.period ?? "current_month", validate: !!stream?.import_options.validate,
    every: stream?.schedule.every ?? "", at: stream?.schedule.at ?? "02:00", weekday: String(stream?.schedule.weekday ?? 0),
    timezone: stream?.schedule.timezone ?? "Asia/Kolkata", max_attempts: String(stream?.max_attempts ?? 3), enabled: stream?.enabled ?? true,
  });
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setF({ ...f, [k]: e.target.type === "checkbox" ? (e.target as HTMLInputElement).checked : e.target.value });
  const save = async () => {
    setBusy(true);
    const body = {
      name: f.name, object_type: f.object_type, path: f.path, records_path: f.records_path,
      pagination: { type: f.pagination_type, size: Number(f.size), ...(f.param ? { param: f.param } : {}), ...(f.size_param ? { size_param: f.size_param } : {}), ...(f.cursor_path ? { cursor_path: f.cursor_path } : {}) },
      sync_mode: f.sync_mode, watermark_field: f.watermark_field || null, watermark_param: f.watermark_param || null,
      mapping_key: f.mapping_key || null,
      import_options: { mode: f.mode, deletions: f.deletions, period: f.period, validate: f.validate },
      schedule: f.every ? { every: f.every, at: f.at, weekday: Number(f.weekday), timezone: f.timezone } : {},
      max_attempts: Number(f.max_attempts), enabled: f.enabled,
    };
    try {
      if (stream) await studioConnApi.updateStream(stream.id, body); else await studioConnApi.createStream(connection.id, body);
      toast.success("Stream saved");
      onDone();
    } catch (e) {
      toast.error("Not saved", { description: e instanceof Error ? e.message : "" });
    } finally { setBusy(false); }
  };
  const matching = (mappings.data ?? []).filter((m) => m.object_type === f.object_type);
  return (
    <div className="space-y-3 rounded-xl border border-brand-200 bg-brand-50/30 p-4">
      <div className="grid gap-3 md:grid-cols-4">
        <L label="Name"><input className={FIELD} value={f.name} onChange={set("name")} /></L>
        <L label="Records are"><select aria-label="Records are" className={FIELD} value={f.object_type} onChange={set("object_type")}>
          {Object.entries(OBJECT_LABEL).filter(([k]) => k !== "validation").map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></L>
        <L label="Path (GET)"><input className={FIELD} value={f.path} onChange={set("path")} placeholder="/employees" /></L>
        <L label="List is at (dotted path; empty = whole response)"><input className={FIELD} value={f.records_path} onChange={set("records_path")} placeholder="data" /></L>
        <L label="Paging"><select aria-label="Paging" className={FIELD} value={f.pagination_type} onChange={set("pagination_type")}>
          <option value="none">None</option><option value="page">Page number</option><option value="offset">Offset</option><option value="cursor">Cursor</option></select></L>
        {f.pagination_type !== "none" ? <L label="Page size"><input className={FIELD} value={f.size} onChange={set("size")} /></L> : null}
        {f.pagination_type !== "none" ? <L label="Page/offset/cursor parameter"><input className={FIELD} value={f.param} onChange={set("param")} placeholder={f.pagination_type === "cursor" ? "cursor" : f.pagination_type === "offset" ? "offset" : "page"} /></L> : null}
        {f.pagination_type === "cursor" ? <L label="Next cursor is at"><input className={FIELD} value={f.cursor_path} onChange={set("cursor_path")} placeholder="next_cursor" /></L>
          : f.pagination_type !== "none" ? <L label="Size parameter"><input className={FIELD} value={f.size_param} onChange={set("size_param")} placeholder={f.pagination_type === "offset" ? "limit" : "page_size"} /></L> : null}
        <L label="Sync"><select aria-label="Sync" className={FIELD} value={f.sync_mode} onChange={set("sync_mode")}><option value="full">Full — everything each time</option><option value="incremental">Incremental — changes since the checkpoint</option></select></L>
        {f.sync_mode === "incremental" ? <L label="Changed-at field in each record"><input className={FIELD} value={f.watermark_field} onChange={set("watermark_field")} placeholder="updated_at" /></L> : null}
        {f.sync_mode === "incremental" ? <L label="Filter parameter the system accepts"><input className={FIELD} value={f.watermark_param} onChange={set("watermark_param")} placeholder="modified_since" /></L> : null}
        <L label="Mapping"><select aria-label="Mapping" className={FIELD} value={f.mapping_key} onChange={set("mapping_key")}>
          <option value="">None — read fields by name</option>{matching.map((m) => <option key={m.key} value={m.key}>{m.name} ({m.key}){m.in_force ? "" : " — nothing published"}</option>)}</select></L>
        <L label="Upsert or replace"><select aria-label="Upsert or replace" className={FIELD} value={f.mode} onChange={set("mode")}>
          <option value="upsert">Upsert — update matches, add new, keep others</option><option value="replace">Replace — the version becomes the fetch</option></select></L>
        <L label="Records no longer sent"><select aria-label="Records no longer sent" className={FIELD} value={f.deletions} onChange={set("deletions")}>
          <option value="ignore">Ignore</option><option value="report">Report on the run — remove nothing</option><option value="replace">Remove (full sync, declared complete)</option></select></L>
        <L label={f.object_type === "employee_master" ? "Effective from" : "Payroll month"}><select aria-label="Period" className={FIELD} value={["current_month", "previous_month"].includes(f.period) ? f.period : "fixed"}
          onChange={(e) => setF({ ...f, period: e.target.value === "fixed" ? new Date().toISOString().slice(0, 8) + "01" : e.target.value })}>
          <option value="current_month">This month</option><option value="previous_month">Last month</option><option value="fixed">A fixed month</option></select>
          {!["current_month", "previous_month"].includes(f.period) ? <input type="date" className={cn(FIELD, "mt-1")} value={f.period} onChange={set("period")} /> : null}</L>
        <L label="Schedule"><select aria-label="Schedule" className={FIELD} value={f.every} onChange={set("every")}><option value="">Manual only</option><option value="hour">Every hour</option><option value="day">Every day</option><option value="week">Every week</option></select></L>
        {f.every ? <L label={f.every === "hour" ? "At minute (HH:MM, minutes used)" : "At (HH:MM)"}><input className={FIELD} value={f.at} onChange={set("at")} /></L> : null}
        {f.every === "week" ? <L label="Weekday"><select aria-label="Weekday" className={FIELD} value={f.weekday} onChange={set("weekday")}>{["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"].map((d, i) => <option key={d} value={i}>{d}</option>)}</select></L> : null}
        {f.every ? <L label="Time zone"><input className={FIELD} value={f.timezone} onChange={set("timezone")} /></L> : null}
        <L label="Attempts before failing"><input className={FIELD} value={f.max_attempts} onChange={set("max_attempts")} /></L>
      </div>
      <div className="flex flex-wrap items-center gap-4 text-sm">
        {f.object_type === "salary_register" ? <label className="flex items-center gap-1.5"><input type="checkbox" checked={f.validate} onChange={set("validate")} /> Validate when stored</label> : null}
        <label className="flex items-center gap-1.5"><input type="checkbox" checked={f.enabled} onChange={set("enabled")} /> Enabled</label>
      </div>
      <div className="flex gap-2">
        <button type="button" disabled={busy} onClick={() => void save()} className="rounded-lg bg-brand-600 px-3 py-2 text-sm font-semibold text-white">Save stream</button>
        <button type="button" onClick={onDone} className="px-3 py-2 text-sm text-ink-600">Cancel</button>
      </div>
    </div>
  );
}
