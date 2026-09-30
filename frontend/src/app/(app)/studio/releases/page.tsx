"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowRight, GitBranch, Plus } from "lucide-react";

import { useEntity } from "@/context/EntityContext";
import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { StudioNav } from "@/components/studio/StudioNav";
import { fmtTime } from "@/components/studio/RunBits";
import { RELEASE_VARIANT, studioReleaseApi, type EnvName } from "@/lib/studio";
import { cn } from "@/lib/utils";

const FIELD =
  "w-full rounded-lg border border-ink-200 bg-white px-3 py-2 text-sm text-ink-900";
const MANAGE = new Set(["owner", "manager"]);
const RANK: Record<EnvName, number> = { development: 0, test: 1, production: 2 };

export default function ReleasesPage() {
  const { entity, activeRole } = useEntity();
  const qc = useQueryClient();
  const canManage = MANAGE.has(activeRole ?? "");
  const env = useQuery({ queryKey: ["studio-env", entity?.id], queryFn: studioReleaseApi.environment, enabled: !!entity });
  const list = useQuery({ queryKey: ["studio-releases", entity?.id], queryFn: studioReleaseApi.list, enabled: !!entity });
  const [creating, setCreating] = useState(false);

  const setEnv = async (e: EnvName) => {
    try { await studioReleaseApi.setEnvironment(e); toast.success(`This company is now ${e}`); await qc.invalidateQueries({ queryKey: ["studio-env", entity?.id] }); }
    catch (err) { toast.error("Refused", { description: err instanceof Error ? err.message : "" }); }
  };

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="PeopleOps Studio" title="Versions & releases"
        description="Build and try configuration in a test company on synthetic data; carry it to production in a release — mappings and workflows only, never data, connections or secrets."
        actions={canManage && !creating ? <button type="button" onClick={() => setCreating(true)} className="inline-flex items-center gap-1.5 rounded-lg bg-brand-600 px-3 py-2 text-sm font-semibold text-white"><Plus size={14} /> New release</button> : null} />
      <StudioNav />

      {env.data ? (
        <Card><CardContent className="space-y-3 py-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-base font-semibold text-ink-900">This company is <span data-testid="environment">{env.data.environment}</span></h2>
              <p className="text-xs text-ink-500">Releases go upward: development → test → production. A company holding real payroll stays production.</p>
            </div>
            {canManage ? <select aria-label="Environment" className={cn(FIELD, "max-w-[12rem]")} value={env.data.environment} onChange={(e) => void setEnv(e.target.value as EnvName)}>
              <option value="development">Development</option><option value="test">Test</option><option value="production">Production</option></select> : null}
          </div>
          <ul className="flex flex-wrap gap-2 text-xs">{env.data.companies.map((c) => (
            <li key={c.id} className="rounded-full border border-ink-200 px-2.5 py-1">{c.name} · <strong>{c.environment}</strong></li>))}</ul>
        </CardContent></Card>
      ) : null}

      {creating && env.data ? <NewRelease environment={env.data.environment} companies={env.data.companies} onCancel={() => setCreating(false)} /> : null}

      {!list.data ? <Skeleton className="h-32 w-full rounded-2xl" /> : list.data.length === 0 ? (
        <Card><CardContent className="py-10 text-center text-sm text-ink-500"><GitBranch className="mx-auto mb-2" size={22} />No releases involve this company yet.</CardContent></Card>
      ) : (
        <Card><CardContent className="py-2"><ul className="divide-y divide-ink-100">
          {list.data.map((r) => (
            <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 py-3">
              <div>
                <Link href={`/studio/releases/${r.id}`} className="font-semibold text-brand-700 hover:underline">{r.title}</Link>
                <p className="flex items-center gap-1 text-xs text-ink-500">{r.source.name} ({r.source.environment}) <ArrowRight size={11} /> {r.target.name} ({r.target.environment}) · {r.items.length} item(s) · by {r.created_by} {fmtTime(r.created_at)}</p>
              </div>
              <Badge variant={RELEASE_VARIANT[r.status]}>{r.status.replace("_", " ")}</Badge>
            </li>
          ))}
        </ul></CardContent></Card>
      )}
    </div>
  );
}

function NewRelease({ environment, companies, onCancel }: { environment: EnvName; companies: { id: string; name: string; environment: EnvName; manage: boolean }[]; onCancel: () => void }) {
  const router = useRouter();
  const { entity } = useEntity();
  const cands = useQuery({ queryKey: ["studio-release-cands", entity?.id], queryFn: studioReleaseApi.candidates, enabled: !!entity });
  const targets = companies.filter((c) => c.id !== entity?.id && c.manage && RANK[c.environment] > RANK[environment]);
  const [target, setTarget] = useState(targets[0]?.id ?? "");
  const [title, setTitle] = useState("");
  const [notes, setNotes] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const toggle = (k: string) => setPicked(picked.includes(k) ? picked.filter((x) => x !== k) : [...picked, k]);
  const create = async () => {
    try {
      const r = await studioReleaseApi.create({ target_entity_id: target, title, notes, items: picked.map((p) => { const [kind, ...n] = p.split(":"); return { kind, name: n.join(":") }; }) });
      router.push(`/studio/releases/${r.id}`);
    } catch (e) { toast.error("Not created", { description: e instanceof Error ? e.message : "" }); }
  };
  if (environment === "production") {
    return <AlertBanner variant="info" title="Releases start from a development or test company">This company is production. Open the test company where the configuration was built, or mark a company without real payroll as test above.</AlertBanner>;
  }
  return (
    <Card><CardContent className="space-y-3 py-5">
      {targets.length === 0 ? <AlertBanner variant="warning" title="No company to release to">You must be an owner or manager of a company in a higher environment than this one.</AlertBanner> : null}
      <div className="grid gap-3 md:grid-cols-2">
        <input aria-label="Release title" className={FIELD} placeholder="Title, e.g. July: new HRMS mapping" value={title} onChange={(e) => setTitle(e.target.value)} />
        <select aria-label="Target company" className={FIELD} value={target} onChange={(e) => setTarget(e.target.value)}>
          {targets.map((t) => <option key={t.id} value={t.id}>{t.name} ({t.environment})</option>)}</select>
      </div>
      <textarea aria-label="Release notes" className={cn(FIELD, "h-14")} placeholder="What changes and why (optional)" value={notes} onChange={(e) => setNotes(e.target.value)} />
      <div className="grid gap-3 md:grid-cols-2 text-sm">
        <div><p className="text-xs font-semibold text-ink-700">Mappings (the version in force)</p>
          {(cands.data?.mappings ?? []).map((m) => <label key={m.name} className="flex items-center gap-2"><input type="checkbox" checked={picked.includes(`mapping:${m.name}`)} onChange={() => toggle(`mapping:${m.name}`)} /> {m.label} <code className="text-xs">{m.name} v{m.version}</code></label>)}
          {cands.data && !cands.data.mappings.length ? <p className="text-xs text-ink-500">None published.</p> : null}</div>
        <div><p className="text-xs font-semibold text-ink-700">Workflows (the version in force)</p>
          {(cands.data?.workflows ?? []).map((w) => <label key={w.name} className="flex items-center gap-2"><input type="checkbox" checked={picked.includes(`workflow:${w.name}`)} onChange={() => toggle(`workflow:${w.name}`)} /> {w.name} <code className="text-xs">v{w.version}</code></label>)}
          {cands.data && !cands.data.workflows.length ? <p className="text-xs text-ink-500">None published.</p> : null}</div>
      </div>
      <p className="text-xs text-ink-500">Not carried, by design: records, registers, runs, findings, connections, credentials, webhook secrets. Set connections and webhooks up in each company; a workflow finds them there by name.</p>
      <div className="flex gap-2">
        <button type="button" disabled={!target || title.trim().length < 3 || !picked.length} onClick={() => void create()} className="rounded-lg bg-brand-600 px-3 py-2 text-sm font-semibold text-white disabled:opacity-40">Draft release and preview impact</button>
        <button type="button" onClick={onCancel} className="px-3 py-2 text-sm text-ink-600">Cancel</button>
      </div>
    </CardContent></Card>
  );
}
