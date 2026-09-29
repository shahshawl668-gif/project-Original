"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Globe, Plus, Trash2 } from "lucide-react";

import { useEntity } from "@/context/EntityContext";
import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { StudioNav } from "@/components/studio/StudioNav";
import { HealthBadge, fmtTime } from "@/components/studio/RunBits";
import { AUTH_LABEL, studioConnApi } from "@/lib/studio";
import { cn } from "@/lib/utils";

const FIELD =
  "w-full rounded-lg border border-ink-200 bg-white px-3 py-2 text-sm text-ink-900";
const MANAGE = new Set(["owner", "manager"]);

export default function ConnectionsPage() {
  const { entity, activeRole } = useEntity();
  const canManage = MANAGE.has(activeRole ?? "");
  const list = useQuery({ queryKey: ["studio-connections", entity?.id], queryFn: studioConnApi.list, enabled: !!entity });
  const [creating, setCreating] = useState(false);
  return (
    <div className="space-y-5">
      <PageHeader eyebrow="PeopleOps Studio" title="Connections"
        description="The other systems this company exchanges data with. Data comes in; the external system stays the source of truth for what it sends. PeopleOpsLab never writes back to it." />
      <StudioNav />
      <Destinations canManage={canManage} />
      <Card><CardContent className="space-y-3 py-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-base font-semibold text-ink-900">Connections for {entity?.name}</h2>
          {canManage && !creating ? (
            <button type="button" onClick={() => setCreating(true)} className="inline-flex items-center gap-1.5 rounded-lg bg-brand-600 px-3 py-2 text-sm font-semibold text-white"><Plus size={14} /> New connection</button>
          ) : null}
        </div>
        {creating ? <NewConnection onCancel={() => setCreating(false)} /> : null}
        {list.error ? <AlertBanner variant="error" title="Could not load connections">{(list.error as Error).message}</AlertBanner> : null}
        {!list.data ? <Skeleton className="h-24 w-full" /> : list.data.length === 0 ? (
          <p className="rounded-xl border border-dashed border-ink-200 px-4 py-6 text-center text-sm text-ink-500">
            No connections yet. A connection can fetch from a REST API on a schedule, or receive files you upload through a mapping.
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase tracking-wide text-ink-500"><tr>
              <th className="py-1">Connection</th><th>Kind</th><th>Authentication</th><th>Streams</th><th>Health</th><th>Last success</th><th>Last failure</th></tr></thead>
            <tbody className="divide-y divide-ink-100">
              {list.data.map((c) => (
                <tr key={c.id}>
                  <td className="py-2"><Link href={`/studio/connections/${c.id}`} className="font-medium text-brand-700 hover:underline">{c.name}</Link>
                    <span className="block text-xs text-ink-400">{c.provider === "rest" ? c.base_url : "File uploads"} · {c.environment}{c.status !== "active" ? " · disabled" : ""}</span></td>
                  <td className="text-xs">{c.system_kind.replace("_", " ")}</td>
                  <td className="text-xs">{c.auth_method.replace(/_/g, " ")}</td>
                  <td className="text-xs">{c.streams.length}</td>
                  <td><HealthBadge health={c.health} /></td>
                  <td className="text-xs">{fmtTime(c.last_success_at)}</td>
                  <td className="text-xs">{fmtTime(c.last_failure_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </CardContent></Card>
    </div>
  );
}

function Destinations({ canManage }: { canManage: boolean }) {
  const { entity } = useEntity();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["studio-destinations", entity?.id], queryFn: studioConnApi.destinations, enabled: !!entity });
  const [host, setHost] = useState("");
  const [note, setNote] = useState("");
  const refresh = () => qc.invalidateQueries({ queryKey: ["studio-destinations", entity?.id] });
  const add = async () => {
    try { await studioConnApi.addDestination(host, note || undefined); setHost(""); setNote(""); await refresh(); }
    catch (e) { toast.error("Not added", { description: e instanceof Error ? e.message : "" }); }
  };
  return (
    <Card><CardContent className="space-y-3 py-5">
      <h2 className="flex items-center gap-2 text-base font-semibold text-ink-900"><Globe size={16} /> Allowed destinations</h2>
      <p className="text-xs text-ink-500">Connections and webhooks can reach only these hosts — over HTTPS, and only at public addresses. Internal networks and cloud metadata addresses are always refused, and redirects are never followed.</p>
      {q.data && !q.data.secret_store.available ? (
        <AlertBanner variant="warning" title="Credentials cannot be stored on this server">{q.data.secret_store.note}</AlertBanner>
      ) : null}
      {q.data?.private_destinations_allowed ? (
        <AlertBanner variant="info" title="Development mode">Private and loopback addresses are allowed on this server (STUDIO_ALLOW_PRIVATE_DESTINATIONS). Production refuses them.</AlertBanner>
      ) : null}
      <div className="flex flex-wrap gap-2">
        {(q.data?.hosts ?? []).map((h) => (
          <span key={h.id} className="inline-flex items-center gap-1.5 rounded-full border border-ink-200 px-2.5 py-1 font-mono text-xs">
            {h.host}{h.note ? <span className="font-sans text-ink-400">· {h.note}</span> : null}
            {canManage ? <button type="button" aria-label={`Remove ${h.host}`} onClick={() => void studioConnApi.removeDestination(h.id).then(refresh)}><Trash2 size={11} /></button> : null}
          </span>
        ))}
        {q.data && q.data.hosts.length === 0 ? <span className="text-sm text-ink-500">None yet — nothing can be reached.</span> : null}
      </div>
      {canManage ? (
        <div className="grid gap-2 md:grid-cols-[1fr_1fr_auto]">
          <input aria-label="Host" className={FIELD} placeholder="api.example-hrms.com or *.example-hrms.com" value={host} onChange={(e) => setHost(e.target.value)} />
          <input aria-label="Note" className={FIELD} placeholder="Why (e.g. HRMS production API)" value={note} onChange={(e) => setNote(e.target.value)} />
          <button type="button" disabled={host.trim().length < 3} onClick={() => void add()} className="rounded-lg border border-brand-300 px-3 py-2 text-sm font-semibold text-brand-700 disabled:opacity-40">Allow</button>
        </div>
      ) : null}
    </CardContent></Card>
  );
}

function NewConnection({ onCancel }: { onCancel: () => void }) {
  const router = useRouter();
  const meta = useQuery({ queryKey: ["studio-conn-meta"], queryFn: studioConnApi.meta });
  const [form, setForm] = useState({ name: "", system_kind: "hrms", provider: "rest", environment: "production", base_url: "", auth_method: "api_key_header" });
  const [config, setConfig] = useState<Record<string, string>>({ header: "X-API-Key" });
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const method = meta.data?.auth_methods[form.auth_method] ?? { config: [], secrets: [] };
  const save = async () => {
    setBusy(true);
    try {
      const conn = await studioConnApi.create({ ...form, base_url: form.provider === "rest" ? form.base_url : null,
        auth_method: form.provider === "rest" ? form.auth_method : "none", auth_config: config, secrets });
      toast.success("Connection created");
      router.push(`/studio/connections/${conn.id}`);
    } catch (e) {
      toast.error("Not created", { description: e instanceof Error ? e.message : "" });
      setBusy(false);
    }
  };
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setForm({ ...form, [k]: e.target.value });
  return (
    <div className="space-y-3 rounded-xl border border-brand-200 bg-brand-50/30 p-4">
      <div className="grid gap-3 md:grid-cols-4">
        <label className="text-xs font-semibold text-ink-700 md:col-span-2">Name<input className={cn(FIELD, "mt-1")} value={form.name} onChange={set("name")} placeholder="e.g. HRMS production" /></label>
        <label className="text-xs font-semibold text-ink-700">System<select aria-label="System" className={cn(FIELD, "mt-1")} value={form.system_kind} onChange={set("system_kind")}>
          {(meta.data?.system_kinds ?? ["hrms"]).map((k) => <option key={k} value={k}>{k.replace("_", " ")}</option>)}</select></label>
        <label className="text-xs font-semibold text-ink-700">Environment<select aria-label="Environment" className={cn(FIELD, "mt-1")} value={form.environment} onChange={set("environment")}>
          <option value="production">Production</option><option value="test">Test</option><option value="development">Development</option></select></label>
      </div>
      <div className="grid gap-3 md:grid-cols-[12rem_1fr]">
        <label className="text-xs font-semibold text-ink-700">Type<select aria-label="Type" className={cn(FIELD, "mt-1")} value={form.provider} onChange={set("provider")}>
          <option value="rest">REST API — fetched by PeopleOpsLab</option><option value="file">Files — uploaded through a mapping</option></select></label>
        {form.provider === "rest" ? (
          <label className="text-xs font-semibold text-ink-700">Base URL<input className={cn(FIELD, "mt-1")} value={form.base_url} onChange={set("base_url")} placeholder="https://api.example-hrms.com/v1" /></label>
        ) : <p className="self-end pb-2 text-xs text-ink-500">Nothing is fetched. Files are uploaded in Data mapping with this connection named as their source.</p>}
      </div>
      {form.provider === "rest" ? (
        <>
          <label className="block text-xs font-semibold text-ink-700">Authentication
            <select aria-label="Authentication" className={cn(FIELD, "mt-1")} value={form.auth_method}
              onChange={(e) => { setForm({ ...form, auth_method: e.target.value }); setConfig(e.target.value === "api_key_header" ? { header: "X-API-Key" } : {}); setSecrets({}); }}>
              {Object.keys(meta.data?.auth_methods ?? { none: 1 }).map((m) => <option key={m} value={m}>{AUTH_LABEL[m] ?? m}</option>)}
            </select></label>
          <div className="grid gap-3 md:grid-cols-2">
            {method.config.map((k) => (
              <label key={k} className="text-xs font-semibold text-ink-700">{k.replace(/_/g, " ")}{k === "scope" ? " (optional)" : ""}
                <input className={cn(FIELD, "mt-1")} value={config[k] ?? ""} onChange={(e) => setConfig({ ...config, [k]: e.target.value })} /></label>
            ))}
            {method.secrets.map((k) => (
              <label key={k} className="text-xs font-semibold text-ink-700">{k.replace(/_/g, " ")} — stored encrypted, never shown again
                <input type="password" autoComplete="off" className={cn(FIELD, "mt-1")} value={secrets[k] ?? ""} onChange={(e) => setSecrets({ ...secrets, [k]: e.target.value })} /></label>
            ))}
          </div>
          {form.auth_method === "basic" ? <p className="text-xs text-warning-800">Use a username and password the system issued for integration. Never enter a person&apos;s own account password.</p> : null}
          {form.auth_method === "oauth2_authorization_code" ? <p className="text-xs text-ink-500">After saving, press <strong>Connect</strong> on the connection to sign in at the provider. The provider must allow the redirect address {typeof window !== "undefined" ? `${window.location.origin}/studio/connections/oauth` : "/studio/connections/oauth"}.</p> : null}
        </>
      ) : null}
      <div className="flex gap-2">
        <button type="button" disabled={busy || form.name.trim().length < 2} onClick={() => void save()} className="rounded-lg bg-brand-600 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50">Create connection</button>
        <button type="button" onClick={onCancel} className="px-3 py-2 text-sm text-ink-600">Cancel</button>
      </div>
    </div>
  );
}
