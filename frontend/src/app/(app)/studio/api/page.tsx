"use client";

import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { KeyRound, Plus, RotateCcw, ShieldOff } from "lucide-react";

import { useEntity } from "@/context/EntityContext";
import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Markdown } from "@/components/studio/Markdown";
import { StudioNav } from "@/components/studio/StudioNav";
import { ConfirmAction, CopyButton, SecretOnce } from "@/components/studio/Controls";
import { fmtTime } from "@/components/studio/RunBits";
import {
  integrationBaseUrl,
  studioApi,
  studioReleaseApi,
  type Credential,
  type IssuedCredential,
  type OpenApi,
  type OpenApiOperation,
  type ServiceAccount,
} from "@/lib/studio";
import { cn } from "@/lib/utils";

const FIELD =
  "w-full rounded-lg border border-ink-200 bg-white px-3 py-2 text-sm text-ink-900";
const MANAGE = new Set(["owner", "manager"]);

const PRESETS: { label: string; scopes: string[] }[] = [
  { label: "Send data", scopes: ["imports:write", "imports:read"] },
  { label: "Send data and validate", scopes: ["imports:write", "imports:read", "validation:run", "validation:read"] },
  { label: "Read results and BI", scopes: ["validation:read", "bi:read", "signoff:read"] },
];

export default function ApiCentrePage() {
  const { activeRole, entity } = useEntity();
  const canManage = MANAGE.has(activeRole ?? "");
  return (
    <div className="space-y-5">
      <PageHeader title="API Centre"
        description="Machine identities for the systems that send you data, the keys they use, and the documented, versioned integration API they call." />
      <StudioNav />
      {entity && <AlertBanner variant="info" title={`API setup for ${entity.name}`}>
        The API address is shared by the platform. Your key names its allowed companies, and each request is checked against that list. For a client integration, create a separate service account limited to this company and send its company ID. A different URL alone would not provide data isolation.
      </AlertBanner>}
      {canManage ? <Accounts key={entity?.id} /> : (
        <AlertBanner variant="info" title="Service accounts and keys are managed by owners and managers">
          You can read the documentation below and see every run in Run history.
        </AlertBanner>
      )}
      <Docs />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Service accounts and keys
// ---------------------------------------------------------------------------
function Accounts() {
  const { entity } = useEntity();
  const qc = useQueryClient();
  const accounts = useQuery({ queryKey: ["studio-accounts", entity?.id], queryFn: studioApi.accounts, enabled: !!entity });
  const [creating, setCreating] = useState(false);
  const [issued, setIssued] = useState<IssuedCredential | null>(null);
  const refresh = () => Promise.all([
    qc.invalidateQueries({ queryKey: ["studio-accounts", entity?.id] }),
    qc.invalidateQueries({ queryKey: ["studio-overview", entity?.id] }),
  ]);

  return (
    <Card><CardContent className="space-y-4 py-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="flex items-center gap-2 text-base font-semibold text-ink-900"><KeyRound size={16} /> Service accounts and keys</h2>
          <p className="text-xs text-ink-500">A service account is a machine, not a person: it cannot sign in, and it can only do what its scopes allow in the companies it names. It can never publish rules, waive or resolve findings, or sign off a month.</p>
        </div>
        {!creating ? (
          <Button onClick={() => setCreating(true)}><Plus size={14} /> New service account</Button>
        ) : null}
      </div>
      {issued ? <IssuedKey issued={issued} onClose={() => setIssued(null)} /> : null}
      {creating ? <NewAccount onCancel={() => setCreating(false)} onCreated={async (a) => {
        setCreating(false);
        await refresh();
        try {
          setIssued(await studioApi.issueKey(a.id, { label: "Initial key", expires_in_days: 90 }));
          await refresh();
        } catch (e) {
          toast.error("Account created, but no key was issued", { description: e instanceof Error ? e.message : "" });
        }
      }} /> : null}
      {accounts.error ? <AlertBanner variant="error" title="Could not load service accounts">{(accounts.error as Error).message}</AlertBanner> : null}
      {!accounts.data ? <Skeleton className="h-24 w-full" /> : accounts.data.length === 0 ? (
        <p className="rounded-xl border border-dashed border-ink-200 px-4 py-6 text-center text-sm text-ink-500">
          No service accounts for this company yet. Create one for each system that will send data — one per system, so a key can be revoked without stopping the others.
        </p>
      ) : (
        <div className="space-y-3">{accounts.data.map((a) => <AccountCard key={a.id} account={a} onIssued={setIssued} onChanged={refresh} />)}</div>
      )}
    </CardContent></Card>
  );
}

function IssuedKey({ issued, onClose }: { issued: IssuedCredential; onClose: () => void }) {
  return (
    <SecretOnce title="API key" value={issued.key} testId="issued-key" onClose={onClose}>
      Store it in the sending system&apos;s secret store. PeopleOpsLab keeps only a fingerprint; nobody here can show it to you later. If it is lost, rotate it.
      {" "}Prefix <code>{issued.prefix}</code> · expires {new Date(issued.expires_at).toLocaleDateString("en-IN")}.
    </SecretOnce>
  );
}

function NewAccount({ onCancel, onCreated }: { onCancel: () => void; onCreated: (a: ServiceAccount) => void }) {
  const { entity, entities, entityRoles } = useEntity();
  const scopes = useQuery({ queryKey: ["studio-scopes"], queryFn: studioApi.scopes });
  const companyEnvironment = useQuery({ queryKey: ["studio-company-environment", entity?.id], queryFn: studioReleaseApi.environment, enabled: !!entity });
  const manageable = entities.filter((e) => MANAGE.has(entityRoles[e.id] ?? ""));
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const environment = companyEnvironment.data?.environment ?? "production";
  const [companies, setCompanies] = useState<string[]>(entity ? [entity.id] : []);
  const [chosen, setChosen] = useState<string[]>(PRESETS[1].scopes);
  const [busy, setBusy] = useState(false);
  const toggle = (list: string[], v: string) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);

  const save = async () => {
    setBusy(true);
    try {
      onCreated(await studioApi.createAccount({ name, description: description || null, environment, entity_ids: companies, scopes: chosen }));
      toast.success("Service account created");
    } catch (e) {
      toast.error("Not created", { description: e instanceof Error ? e.message : "" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-3 rounded-xl border border-brand-200 bg-brand-50/30 p-4">
      {companyEnvironment.error && <AlertBanner variant="error" title="Company environment could not be loaded">Reload Studio before issuing a key.</AlertBanner>}
      <div className="grid gap-3 md:grid-cols-[1fr_1fr_12rem]">
        <label className="text-xs font-semibold text-ink-700">Name — the system that will use it
          <input className={cn(FIELD, "mt-1")} placeholder="e.g. HRMS nightly feed" value={name} onChange={(e) => setName(e.target.value)} /></label>
        <label className="text-xs font-semibold text-ink-700">Description
          <input className={cn(FIELD, "mt-1")} value={description} onChange={(e) => setDescription(e.target.value)} /></label>
        <div className="text-xs font-semibold text-ink-700">Environment
          <p className="mt-1 flex h-9 items-center gap-1 text-[13px] font-normal text-ink-900"><span className="capitalize">{companyEnvironment.isLoading ? "Loading…" : environment}</span><span className="text-ink-500">· set by this company</span></p></div>
      </div>
      <p className="text-xs text-warning-800">A key can only access companies marked with the same environment. Test and development companies must use synthetic data; they share infrastructure with production and are not separate databases.</p>
      <fieldset>
        <legend className="text-xs font-semibold text-ink-700">Companies it may act on — only ones you manage</legend>
        <div className="mt-1 flex flex-wrap gap-2">
          {manageable.map((e) => (
            <label key={e.id} className="flex items-center gap-1.5 rounded-lg border border-ink-200 px-2 py-1 text-sm">
              <input type="checkbox" checked={companies.includes(e.id)} onChange={() => setCompanies(toggle(companies, e.id))} /> {e.name}
            </label>
          ))}
        </div>
      </fieldset>
      {companies.length > 1 && <p className="text-xs text-warning-800">This key can act on multiple companies. Its callers must send X-Company-Id on every request. For independent clients, use one account per company.</p>}
      <fieldset>
        <legend className="text-xs font-semibold text-ink-700">Scopes — grant the least it needs</legend>
        <div className="mt-1 flex flex-wrap gap-2">
          {PRESETS.map((p) => (
            <button key={p.label} type="button" onClick={() => setChosen(p.scopes)} className="rounded-full border border-brand-300 bg-white px-2.5 py-0.5 text-xs text-brand-700 hover:bg-brand-50">{p.label}</button>
          ))}
        </div>
        <div className="mt-2 grid gap-1.5 md:grid-cols-2">
          {(scopes.data ?? []).map((s) => (
            <label key={s.scope} className="flex items-start gap-2 text-sm">
              <input type="checkbox" className="mt-1" checked={chosen.includes(s.scope)} onChange={() => setChosen(toggle(chosen, s.scope))} />
              <span><code className="text-xs">{s.scope}</code>{s.writes ? <Badge variant="warning" className="ml-1">changes data</Badge> : null}
                <span className="block text-xs text-ink-500">{s.grants}</span></span>
            </label>
          ))}
        </div>
      </fieldset>
      <div className="flex gap-2">
        <Button disabled={busy || companyEnvironment.isLoading || !!companyEnvironment.error || name.trim().length < 2 || !companies.length || !chosen.length} onClick={() => void save()}>Create and issue a key</Button>
        <Button variant="ghost" onClick={onCancel}>Cancel</Button>
      </div>
    </div>
  );
}

function AccountCard({ account, onIssued, onChanged }: { account: ServiceAccount; onIssued: (k: IssuedCredential) => void; onChanged: () => Promise<unknown> }) {
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState<{ kind: "rotate" | "revoke"; cred: Credential } | { kind: "disable" } | null>(null);
  const run = async (fn: () => Promise<unknown>, done: string) => {
    setBusy(true);
    try { await fn(); toast.success(done); await onChanged(); } catch (e) {
      toast.error("Refused", { description: e instanceof Error ? e.message : "" });
    } finally { setBusy(false); }
  };
  const issue = () => run(async () => onIssued(await studioApi.issueKey(account.id, { label: "Additional key", expires_in_days: 90 })), "Key issued");
  const rotate = (c: Credential) => setConfirm({ kind: "rotate", cred: c });
  const revoke = (c: Credential) => setConfirm({ kind: "revoke", cred: c });
  const setStatus = (status: "active" | "disabled") => run(() => studioApi.updateAccount(account.id, { status }),
    status === "disabled" ? "Service account disabled — every key stopped" : "Service account enabled");
  const toggle = () => (account.status === "active" ? setConfirm({ kind: "disable" }) : void setStatus("active"));

  return (
    <div className="rounded-xl border border-ink-200 p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="flex flex-wrap items-center gap-2 font-semibold text-ink-900">
            {account.name} <Badge variant={account.environment === "production" ? "primary" : "secondary"}>{account.environment}</Badge>
            {account.status !== "active" ? <Badge variant="destructive">disabled</Badge> : null}
          </p>
          {account.description ? <p className="text-xs text-ink-500">{account.description}</p> : null}
          <p className="pt-1 text-xs text-ink-600">Companies: {account.companies.map((c) => c.name).join(", ")}{account.hidden_companies ? ` + ${account.hidden_companies} you cannot see` : ""}</p>
          <div className="flex flex-wrap gap-1 pt-1">{account.scopes.map((s) => <code key={s} className="rounded bg-ink-100 px-1.5 py-0.5 text-[11px]">{s}</code>)}</div>
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" disabled={busy || account.status !== "active"} onClick={() => void issue()}>Issue key</Button>
          <Button size="sm" variant={account.status === "active" ? "destructive-outline" : "outline"} disabled={busy} onClick={() => toggle()}>{account.status === "active" ? "Disable" : "Enable"}</Button>
        </div>
      </div>
      {account.credentials.length ? (
        <div className="scrollbar-thin overflow-x-auto" tabIndex={0} role="region" aria-label={`Keys for ${account.name}`}><table className="mt-3 w-full text-xs">
          <thead className="text-left text-ink-500"><tr><th className="py-1 font-medium">Key</th><th>State</th><th>Expires</th><th>Last used</th><th /></tr></thead>
          <tbody className="divide-y divide-ink-100">
            {account.credentials.map((c) => (
              <tr key={c.id}>
                <td className="py-1.5 font-mono">{c.prefix}…<span className="block font-sans text-ink-500">{c.label}</span></td>
                <td><Badge variant={c.state === "active" ? "success" : c.state === "rotating" ? "warning" : "secondary"}>{c.state}</Badge>
                  {c.revoke_reason ? <span className="block text-ink-500">{c.revoke_reason}</span> : null}</td>
                <td>{new Date(c.expires_at).toLocaleDateString("en-IN")}</td>
                <td>{c.last_used_at ? fmtTime(c.last_used_at) : "never"}</td>
                <td className="text-right">
                  {c.state === "active" ? (
                    <span className="inline-flex gap-2">
                      <Button size="sm" variant="outline" disabled={busy} onClick={() => rotate(c)}><RotateCcw size={12} /> Rotate</Button>
                      <Button size="sm" variant="destructive-outline" disabled={busy} onClick={() => revoke(c)}><ShieldOff size={12} /> Revoke</Button>
                    </span>
                  ) : c.state === "rotating" ? (
                    <Button size="sm" variant="destructive-outline" disabled={busy} onClick={() => revoke(c)}><ShieldOff size={12} /> Revoke now</Button>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table></div>
      ) : <p className="pt-2 text-xs text-ink-500">No keys yet.</p>}

      <ConfirmAction
        open={confirm?.kind === "rotate"}
        onClose={() => setConfirm(null)}
        tone="primary"
        title={confirm?.kind === "rotate" ? `Rotate ${confirm.cred.prefix}…?` : ""}
        consequence="A new key is issued and shown once. The old key keeps working for the overlap you choose, then stops, so the sending system can switch without a gap."
        confirmLabel="Rotate key"
        field={{ kind: "hours", label: "Keep the old key working for (hours)", min: 0, max: 168, initial: 24, help: "0 stops the old key at once; at most 168 (seven days)." }}
        onConfirm={(hours) => confirm?.kind === "rotate" ? run(async () => onIssued((await studioApi.rotateKey(confirm.cred.id, { grace_hours: Number(hours), expires_in_days: 90 })).new), "Key rotated") : undefined}
      />
      <ConfirmAction
        open={confirm?.kind === "revoke"}
        onClose={() => setConfirm(null)}
        title={confirm?.kind === "revoke" ? `Revoke ${confirm.cred.prefix}…?` : ""}
        consequence="It stops working immediately and cannot be restored. Any system still using it is refused from its next call."
        confirmLabel="Revoke key"
        field={{ kind: "reason", label: "Why — recorded in the audit trail", required: true, placeholder: "e.g. key exposed in a support ticket" }}
        onConfirm={(reason) => confirm?.kind === "revoke" ? run(() => studioApi.revokeKey(confirm.cred.id, reason), "Key revoked") : undefined}
      />
      <ConfirmAction
        open={confirm?.kind === "disable"}
        onClose={() => setConfirm(null)}
        title={`Disable ${account.name}?`}
        consequence="Every key on this account stops working until it is enabled again. Runs already accepted are not affected."
        confirmLabel="Disable account"
        onConfirm={() => setStatus("disabled")}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Documentation
// ---------------------------------------------------------------------------
const METHOD_TONE: Record<string, string> = {
  get: "bg-brand-100 text-brand-800", post: "bg-success-100 text-success-800",
  patch: "bg-warning-100 text-warning-800", put: "bg-warning-100 text-warning-800", delete: "bg-danger-100 text-danger-800",
};

function Docs() {
  const spec = useQuery({ queryKey: ["integration-openapi"], queryFn: studioApi.openapi, staleTime: 10 * 60_000 });
  const { entity } = useEntity();
  const base = integrationBaseUrl(spec.data?.servers?.[0]?.url ?? "/api/integration/v1");
  return (
    <Card id="docs"><CardContent className="space-y-4 py-5">
      <div>
        <h2 className="text-base font-semibold text-ink-900">Integration API documentation</h2>
        <p className="text-xs text-ink-500">Read live from the published contract. Base URL: <code className="break-all">{base}</code>
          {" · "}<a className="text-brand-700 underline" href={`/api/proxy/api/integration/v1/openapi.json`} target="_blank" rel="noreferrer">OpenAPI JSON</a>.
          Examples use invented people; <code>$POL_KEY</code> stands for your key, which never appears on this page.</p>
      </div>
      {entity && <div className="flex flex-wrap items-center gap-2 rounded-lg border border-ink-200 p-3 text-xs"><strong>Selected company:</strong> {entity.name} <code className="break-all">{entity.id}</code><CopyButton value={entity.id} label="Copy company ID" what="Company ID copied" /></div>}
      <QuickStart base={base} companyId={entity?.id ?? "<company id>"} />
      {spec.error ? <AlertBanner variant="error" title="Could not load the API contract">{(spec.error as Error).message}</AlertBanner> : null}
      {!spec.data ? <Skeleton className="h-40 w-full" /> : <Contract spec={spec.data} base={base} companyId={entity?.id ?? "<company id>"} />}
    </CardContent></Card>
  );
}

function curl(base: string, companyId: string, method: string, path: string, body?: unknown, idem = false) {
  const lines = [`curl -sS -X ${method.toUpperCase()} "${base}${path}"`, `  -H "Authorization: Bearer $POL_KEY"`, `  -H "X-Company-Id: ${companyId}"`];
  if (idem) lines.push(`  -H "Idempotency-Key: $(uuidgen)"`);
  if (body !== undefined) {
    lines.push(`  -H "Content-Type: application/json"`);
    lines.push(`  -d '${JSON.stringify(body)}'`);
  }
  return lines.join(" \\\n");
}

function Snippet({ code }: { code: string }) {
  return (
    <div className="relative">
      <pre tabIndex={0} aria-label="Example command" className="overflow-x-auto rounded-lg bg-ink-900 p-3 pr-16 text-[11px] leading-relaxed text-ink-100">{code}</pre>
      <CopyButton value={code} what="Command copied" dark className="absolute right-2 top-2" />
    </div>
  );
}

function QuickStart({ base, companyId }: { base: string; companyId: string }) {
  const master = { effective_from: "2026-06-01", records: [{ employee_id: "00123", employee_name: "Asha Rao (synthetic)", date_of_joining: "2024-04-15" }] };
  const steps: [string, string][] = [
    ["1 · Check the key", curl(base, companyId, "get", "/me")],
    ["2 · Rehearse an import — stores nothing, reports what would happen", curl(base, companyId, "post", "/imports/employee_master/check", master)],
    ["3 · Import it for real — returns a run at once (202)", curl(base, companyId, "post", "/imports/employee_master", { ...master, batch_id: "FIRST-TEST" }, true)],
    ["4 · Poll the run until it is final; read the counts", curl(base, companyId, "get", "/imports/<run id>")],
    ["5 · Start validation once the month's register is in", curl(base, companyId, "post", "/validation-jobs", { period_month: "2026-06-01" }, true)],
  ];
  return (
    <details className="rounded-xl border border-ink-200 p-3" open>
      <summary className="cursor-pointer text-sm font-semibold">Quick start — five calls</summary>
      <div className="space-y-3 pt-3">{steps.map(([t, c]) => <div key={t}><p className="pb-1 text-xs font-semibold text-ink-700">{t}</p><Snippet code={c} /></div>)}</div>
    </details>
  );
}

function Contract({ spec, base, companyId }: { spec: OpenApi; base: string; companyId: string }) {
  const byTag = useMemo(() => {
    const out: Record<string, { method: string; path: string; op: OpenApiOperation }[]> = {};
    Object.entries(spec.paths).forEach(([path, methods]) => {
      Object.entries(methods).forEach(([method, op]) => {
        const tag = op.tags?.[0] ?? "other";
        (out[tag] ??= []).push({ method, path, op });
      });
    });
    return out;
  }, [spec]);
  return (
    <div className="space-y-4">
      <details className="rounded-xl border border-ink-200 p-3">
        <summary className="cursor-pointer text-sm font-semibold">Contract — authentication, scopes, idempotency, limits, errors, versioning (v{spec.info.version})</summary>
        <div className="pt-2"><Markdown text={spec.info.description} /></div>
      </details>
      {(spec.tags ?? []).map((t) => (
        <div key={t.name} className="space-y-2">
          <h3 className="text-sm font-semibold capitalize text-ink-900">{t.name} <span className="font-normal text-ink-500">— {t.description}</span></h3>
          {(byTag[t.name] ?? []).map(({ method, path, op }) => {
            const content = op.requestBody?.content?.["application/json"];
            const examples = content?.examples ? Object.entries(content.examples) : content?.example !== undefined ? [["example", { value: content.example }] as const] : [];
            const needsIdem = /Idempotency-Key is required/i.test(op.description ?? "");
            const concrete = path.replace("{kind}", "employee_master");
            return (
              <details key={`${method}${path}`} className="rounded-lg border border-ink-200 px-3 py-2">
                <summary className="flex cursor-pointer flex-wrap items-center gap-2 text-sm">
                  <span className={cn("rounded px-1.5 py-0.5 font-mono text-[11px] font-semibold", METHOD_TONE[method] ?? "bg-ink-100")}>{method}</span>
                  <code className="text-xs">{path}</code><span className="text-ink-600">{op.summary}</span>
                </summary>
                <div className="space-y-2 pt-2 text-sm">
                  {op.description ? <Markdown text={op.description} /> : null}
                  {op.parameters?.length ? (
                    <div className="scrollbar-thin overflow-x-auto" tabIndex={0} role="region" aria-label="Parameters"><table className="w-full text-xs"><tbody>{op.parameters.filter((p) => !["authorization"].includes(p.name.toLowerCase())).map((p) => (
                      <tr key={`${p.in}${p.name}`} className="border-b border-ink-100">
                        <td className="py-1 pr-2 font-mono">{p.name}</td><td className="pr-2 text-ink-500">{p.in}{p.required ? " · required" : ""}</td>
                        <td className="text-ink-600">{p.description ?? p.schema?.pattern ?? ""}</td></tr>))}</tbody></table></div>
                  ) : null}
                  {examples.length ? examples.map(([k, ex]) => (
                    <div key={k}><p className="pb-1 text-xs font-semibold text-ink-700">{"summary" in ex && ex.summary ? ex.summary : "Example"}</p>
                      <Snippet code={curl(base, companyId, method, k !== "example" && path.includes("{kind}") ? path.replace("{kind}", k) : concrete, ex.value, needsIdem)} /></div>
                  )) : <Snippet code={curl(base, companyId, method, concrete, method === "get" ? undefined : undefined, needsIdem)} />}
                  <p className="text-[11px] text-ink-500">Responses: {Object.entries(op.responses ?? {}).map(([code, r]) => `${code} ${r.description ?? ""}`).join(" · ")}</p>
                </div>
              </details>
            );
          })}
        </div>
      ))}
    </div>
  );
}
