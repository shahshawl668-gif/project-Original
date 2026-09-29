"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Copy, Inbox, Plus, RotateCcw, Send, TriangleAlert } from "lucide-react";

import { useEntity } from "@/context/EntityContext";
import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { StudioNav } from "@/components/studio/StudioNav";
import { fmtTime } from "@/components/studio/RunBits";
import { OBJECT_LABEL, studioHookApi, studioMapApi, type Webhook } from "@/lib/studio";
import { cn } from "@/lib/utils";

const FIELD =
  "w-full rounded-lg border border-ink-200 bg-white px-3 py-2 text-sm text-ink-900";
const MANAGE = new Set(["owner", "manager"]);

const VERIFY_SNIPPET = `# Python — verify a PeopleOpsLab webhook before trusting it
import hmac, hashlib, time

def verify(header: str, secret: str, raw_body: bytes, tolerance=300) -> bool:
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    sigs = [p.split("=", 1)[1] for p in header.split(",") if p.startswith("v1=")]
    ts = int(parts["t"])
    if abs(time.time() - ts) > tolerance:
        return False
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + raw_body, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, s) for s in sigs)

# Then de-duplicate on the X-PeopleOpsLab-Event-Id header: delivery is at least once.`;

function ShownOnce({ label, value, onClose }: { label: string; value: string; onClose: () => void }) {
  return (
    <div role="alert" className="space-y-2 rounded-xl border-2 border-warning-300 bg-warning-50 p-4 text-sm text-warning-950">
      <p className="flex items-center gap-2 font-semibold"><TriangleAlert size={16} /> {label} — shown once</p>
      <div className="flex items-center gap-2">
        <code data-testid="shown-once" className="min-w-0 flex-1 break-all rounded bg-white px-2 py-1.5 font-mono text-xs text-ink-900">{value}</code>
        <button type="button" onClick={() => void navigator.clipboard.writeText(value).then(() => toast.success("Copied"))} className="inline-flex items-center gap-1 rounded-lg border border-warning-400 px-2 py-1.5 text-xs font-semibold"><Copy size={12} /> Copy</button>
      </div>
      <button type="button" onClick={onClose} className="rounded-lg bg-warning-600 px-3 py-1.5 text-xs font-semibold text-white">I have stored it</button>
    </div>
  );
}

export default function WebhooksPage() {
  const { activeRole } = useEntity();
  const canManage = MANAGE.has(activeRole ?? "");
  return (
    <div className="space-y-5">
      <PageHeader eyebrow="PeopleOps Studio" title="Webhooks"
        description="Events out to your systems, records in from them. Every call is signed. Delivery is at least once: the same event may arrive more than once, so de-duplicate on its id. Payloads carry identifiers and states, never pay — read detail through the integration API." />
      <StudioNav />
      <Outbound canManage={canManage} />
      <InboundPanel canManage={canManage} />
      <Card><CardContent className="space-y-2 py-5">
        <h2 className="text-base font-semibold text-ink-900">Verifying a signature</h2>
        <p className="text-xs text-ink-500">Header <code>X-PeopleOpsLab-Signature: t=&lt;unix seconds&gt;,v1=&lt;hex&gt;</code>, where hex is HMAC-SHA256 of <code>&lt;t&gt;.&lt;raw body&gt;</code> with the webhook&apos;s secret. During a secret rotation a second <code>v1</code> is included until the overlap ends. Inbound endpoints expect exactly the same scheme from you, plus a unique <code>X-PeopleOpsLab-Event-Id</code>.</p>
        <pre className="overflow-x-auto rounded-lg bg-ink-900 p-3 text-[11px] text-ink-100">{VERIFY_SNIPPET}</pre>
      </CardContent></Card>
    </div>
  );
}

function Outbound({ canManage }: { canManage: boolean }) {
  const { entity } = useEntity();
  const qc = useQueryClient();
  const hooks = useQuery({ queryKey: ["studio-webhooks", entity?.id], queryFn: studioHookApi.list, enabled: !!entity });
  const catalogue = useQuery({ queryKey: ["studio-webhook-events"], queryFn: studioHookApi.catalogue });
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ name: "", url: "", events: ["import.completed", "validation.completed"] as string[] });
  const [secret, setSecret] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const deliveries = useQuery({ queryKey: ["studio-deliveries", entity?.id, open, filter], queryFn: () => studioHookApi.deliveries(open ?? undefined, filter || undefined), enabled: !!entity && !!open,
    refetchInterval: (q) => (q.state.data?.items.some((d) => d.status === "pending") ? 3000 : false) });
  const refresh = async () => { await qc.invalidateQueries({ queryKey: ["studio-webhooks", entity?.id] }); await qc.invalidateQueries({ queryKey: ["studio-deliveries", entity?.id] }); };
  const act = async (fn: () => Promise<unknown>, done: string) => {
    try { await fn(); toast.success(done); await refresh(); } catch (e) { toast.error("Refused", { description: e instanceof Error ? e.message : "" }); }
  };
  const create = async () => {
    try { const h = await studioHookApi.create(form); setSecret(h.secret); setCreating(false); await refresh(); }
    catch (e) { toast.error("Not created", { description: e instanceof Error ? e.message : "" }); }
  };
  const rotate = async (h: Webhook) => {
    const hours = window.prompt("Keep signing with the old secret too for how many hours while your receiver switches? (0–168)", "24");
    if (hours === null) return;
    try { const r = await studioHookApi.rotate(h.id, Number(hours)); setSecret(r.secret); await refresh(); }
    catch (e) { toast.error("Refused", { description: e instanceof Error ? e.message : "" }); }
  };
  return (
    <Card><CardContent className="space-y-3 py-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div><h2 className="flex items-center gap-2 text-base font-semibold text-ink-900"><Send size={16} /> Outbound</h2>
          <p className="text-xs text-ink-500">Retries after 1 min, 5 min, 30 min, 2 h, 6 h, 12 h, 24 h; after the last attempt a delivery waits in the failed queue for a replay. Destinations must be on the allowed list (Connections).</p></div>
        {canManage && !creating ? <button type="button" onClick={() => setCreating(true)} className="inline-flex items-center gap-1.5 rounded-lg bg-brand-600 px-3 py-2 text-sm font-semibold text-white"><Plus size={14} /> New webhook</button> : null}
      </div>
      {secret ? <ShownOnce label="Signing secret" value={secret} onClose={() => setSecret(null)} /> : null}
      {creating ? (
        <div className="space-y-3 rounded-xl border border-brand-200 p-4">
          <div className="grid gap-3 md:grid-cols-2">
            <input aria-label="Webhook name" className={FIELD} placeholder="Name, e.g. Finance system" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            <input aria-label="Webhook URL" className={FIELD} placeholder="https://finance.example.com/hooks/peopleopslab" value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} />
          </div>
          <div className="grid gap-1.5 md:grid-cols-2">
            {(catalogue.data?.events ?? []).map((ev) => (
              <label key={ev.type} className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" checked={form.events.includes(ev.type)}
                onChange={() => setForm({ ...form, events: form.events.includes(ev.type) ? form.events.filter((x) => x !== ev.type) : [...form.events, ev.type] })} />
                <span><code className="text-xs">{ev.type}</code><span className="block text-xs text-ink-500">{ev.description}</span></span></label>
            ))}
          </div>
          <div className="flex gap-2"><button type="button" disabled={!form.name || !form.url || !form.events.length} onClick={() => void create()} className="rounded-lg bg-brand-600 px-3 py-2 text-sm font-semibold text-white disabled:opacity-40">Create</button>
            <button type="button" onClick={() => setCreating(false)} className="px-3 py-2 text-sm text-ink-600">Cancel</button></div>
        </div>
      ) : null}
      {!hooks.data ? <Skeleton className="h-16 w-full" /> : hooks.data.length === 0 ? <p className="text-sm text-ink-500">No outbound webhooks.</p> : hooks.data.map((h) => (
        <div key={h.id} className="rounded-xl border border-ink-200 p-3 text-sm">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <p className="font-semibold">{h.name} <Badge variant={h.status === "active" ? "success" : "secondary"}>{h.status}</Badge>{h.deliveries.failed ? <Badge variant="destructive" className="ml-1">{h.deliveries.failed} failed</Badge> : null}</p>
              <p className="break-all font-mono text-xs text-ink-500">{h.url}</p>
              <p className="text-xs text-ink-500">{h.events.join(", ")} · payload {h.payload_version} · last delivery {fmtTime(h.last_delivery_at)} {h.last_delivery_status ?? ""}</p>
              <p className="text-xs text-ink-500">{Object.entries(h.deliveries).map(([k, v]) => `${v} ${k}`).join(" · ") || "nothing sent yet"}</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <button type="button" onClick={() => setOpen(open === h.id ? null : h.id)} className="rounded-lg border border-ink-200 px-2.5 py-1 text-xs">{open === h.id ? "Hide deliveries" : "Deliveries"}</button>
              {canManage ? <>
                <button type="button" onClick={() => void act(() => studioHookApi.test(h.id), "Test event queued")} className="rounded-lg border border-ink-200 px-2.5 py-1 text-xs">Send test</button>
                <button type="button" onClick={() => void rotate(h)} className="rounded-lg border border-ink-200 px-2.5 py-1 text-xs">Rotate secret</button>
                {h.deliveries.failed ? <button type="button" onClick={() => void act(() => studioHookApi.replayFailed(h.id), "Failed deliveries queued again")} className="inline-flex items-center gap-1 rounded-lg bg-brand-600 px-2.5 py-1 text-xs font-semibold text-white"><RotateCcw size={11} /> Replay failed</button> : null}
                <button type="button" onClick={() => void act(() => studioHookApi.update(h.id, { status: h.status === "active" ? "disabled" : "active" }), "Updated")} className="rounded-lg border border-ink-200 px-2.5 py-1 text-xs">{h.status === "active" ? "Disable" : "Enable"}</button>
              </> : null}
            </div>
          </div>
          {open === h.id ? (
            <div className="mt-3 space-y-2">
              <select aria-label="Delivery status" className="rounded-lg border border-ink-200 px-2 py-1 text-xs" value={filter} onChange={(e) => setFilter(e.target.value)}>
                <option value="">All</option><option value="pending">Pending</option><option value="delivered">Delivered</option><option value="failed">Failed queue</option><option value="replayed">Replayed</option></select>
              {!deliveries.data ? <Skeleton className="h-10 w-full" /> : deliveries.data.items.length === 0 ? <p className="text-xs text-ink-500">None.</p> : (
                <table className="w-full text-xs"><thead className="text-left uppercase text-ink-500"><tr><th className="py-1">Event</th><th>Status</th><th>Attempts</th><th>Last answer</th><th>Next attempt</th><th /></tr></thead>
                  <tbody className="divide-y divide-ink-100">{deliveries.data.items.map((d) => (
                    <tr key={d.id}><td className="py-1"><code>{d.event_type}</code><span className="block font-mono text-ink-400">{d.event_id.slice(0, 8)}{d.replay_of_id ? " · replay" : ""}</span></td>
                      <td><Badge variant={d.status === "delivered" ? "success" : d.status === "failed" ? "destructive" : "secondary"}>{d.status}</Badge></td>
                      <td>{d.attempts}</td><td>{d.last_status_code ?? "—"} {d.last_error ?? ""}{d.last_response_ms !== null ? ` · ${d.last_response_ms} ms` : ""}</td>
                      <td>{fmtTime(d.next_attempt_at)}</td>
                      <td className="text-right">{canManage && d.status !== "pending" ? <button type="button" className="underline" onClick={() => void act(() => studioHookApi.replay(d.id), "Replay queued")}>Replay</button> : null}</td></tr>))}</tbody></table>
              )}
            </div>
          ) : null}
        </div>
      ))}
    </CardContent></Card>
  );
}

function InboundPanel({ canManage }: { canManage: boolean }) {
  const { entity } = useEntity();
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["studio-inbound", entity?.id], queryFn: studioHookApi.inbound, enabled: !!entity });
  const mappings = useQuery({ queryKey: ["studio-mappings", entity?.id], queryFn: studioMapApi.list, enabled: !!entity });
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ name: "", object_type: "employee_master", mapping_key: "", period: new Date().toISOString().slice(0, 7) });
  const [shown, setShown] = useState<{ url: string; secret: string } | null>(null);
  const [receiptsFor, setReceiptsFor] = useState<string | null>(null);
  const receipts = useQuery({ queryKey: ["studio-receipts", receiptsFor], queryFn: () => studioHookApi.receipts(receiptsFor!), enabled: !!receiptsFor });
  const create = async () => {
    const period = `${form.period}-01`;
    const options = form.object_type === "employee_master" ? { effective_from: period } : form.object_type === "ctc" ? {} : { period_month: period };
    try {
      const ep = await studioHookApi.createInbound({ name: form.name, object_type: form.object_type, mapping_key: form.mapping_key || null, options });
      setShown({ url: ep.url, secret: ep.secret });
      setCreating(false);
      await qc.invalidateQueries({ queryKey: ["studio-inbound", entity?.id] });
    } catch (e) { toast.error("Not created", { description: e instanceof Error ? e.message : "" }); }
  };
  return (
    <Card><CardContent className="space-y-3 py-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div><h2 className="flex items-center gap-2 text-base font-semibold text-ink-900"><Inbox size={16} /> Inbound</h2>
          <p className="text-xs text-ink-500">A signed URL another system pushes records to. Each call becomes an import run with the endpoint&apos;s mapping; a repeated event id is answered as a duplicate and imports nothing.</p></div>
        {canManage && !creating ? <button type="button" onClick={() => setCreating(true)} className="inline-flex items-center gap-1.5 rounded-lg bg-brand-600 px-3 py-2 text-sm font-semibold text-white"><Plus size={14} /> New endpoint</button> : null}
      </div>
      {shown ? <><ShownOnce label="Signing secret" value={shown.secret} onClose={() => setShown(null)} /><p className="break-all text-xs">URL: <code>{shown.url}</code></p></> : null}
      {creating ? (
        <div className="grid gap-2 rounded-xl border border-brand-200 p-3 md:grid-cols-5">
          <input aria-label="Endpoint name" className={FIELD} placeholder="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <select aria-label="Imports" className={FIELD} value={form.object_type} onChange={(e) => setForm({ ...form, object_type: e.target.value, mapping_key: "" })}>
            {Object.entries(OBJECT_LABEL).filter(([k]) => k !== "validation").map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
          <select aria-label="Mapping" className={FIELD} value={form.mapping_key} onChange={(e) => setForm({ ...form, mapping_key: e.target.value })}>
            <option value="">No mapping</option>{(mappings.data ?? []).filter((m) => m.object_type === form.object_type).map((m) => <option key={m.key} value={m.key}>{m.name}</option>)}</select>
          {form.object_type !== "ctc" ? <input aria-label="Default month" type="month" className={FIELD} value={form.period} onChange={(e) => setForm({ ...form, period: e.target.value })} /> : <span />}
          <button type="button" disabled={form.name.length < 2} onClick={() => void create()} className="rounded-lg bg-brand-600 px-3 py-2 text-sm font-semibold text-white disabled:opacity-40">Create</button>
        </div>
      ) : null}
      {!list.data ? <Skeleton className="h-12 w-full" /> : list.data.length === 0 ? <p className="text-sm text-ink-500">No inbound endpoints.</p> : (
        <table className="w-full text-sm"><thead className="text-left text-xs text-ink-500"><tr><th className="py-1">Endpoint</th><th>Imports</th><th>Last call</th><th>Status</th><th /></tr></thead>
          <tbody className="divide-y divide-ink-100">{list.data.map((ep) => (
            <tr key={ep.id}><td className="py-2">{ep.name}<span className="block break-all font-mono text-[11px] text-ink-400">{ep.url}</span></td>
              <td className="text-xs">{OBJECT_LABEL[ep.action.object_type]}{ep.action.mapping_key ? ` via ${ep.action.mapping_key}` : ""}</td>
              <td className="text-xs">{fmtTime(ep.last_received_at)}</td>
              <td><Badge variant={ep.status === "active" ? "success" : "secondary"}>{ep.status}</Badge></td>
              <td className="text-right text-xs"><button type="button" className="underline" onClick={() => setReceiptsFor(receiptsFor === ep.id ? null : ep.id)}>Calls</button>
                {canManage ? <button type="button" className="ml-2 underline" onClick={() => void studioHookApi.updateInbound(ep.id, ep.status === "active" ? "disabled" : "active").then(() => qc.invalidateQueries({ queryKey: ["studio-inbound", entity?.id] }))}>{ep.status === "active" ? "Disable" : "Enable"}</button> : null}</td></tr>))}</tbody></table>
      )}
      {receiptsFor && receipts.data ? (
        <ul className="text-xs">{receipts.data.length === 0 ? <li className="text-ink-500">No calls yet.</li> : receipts.data.map((r) => (
          <li key={r.id}><code>{r.event_id}</code> · {fmtTime(r.received_at)} {r.run_id ? <Link className="underline" href={`/studio/runs/${r.run_id}`}>run</Link> : null}</li>))}</ul>
      ) : null}
    </CardContent></Card>
  );
}
