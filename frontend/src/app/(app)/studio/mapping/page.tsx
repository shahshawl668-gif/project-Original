"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus } from "lucide-react";

import { useEntity } from "@/context/EntityContext";
import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { StudioNav } from "@/components/studio/StudioNav";
import { OBJECT_LABEL, studioMapApi } from "@/lib/studio";

const FIELD =
  "w-full rounded-lg border border-ink-200 bg-white px-3 py-2 text-sm text-ink-900";
const WRITE = new Set(["owner", "manager", "analyst"]);

export default function MappingListPage() {
  const { entity, activeRole } = useEntity();
  const router = useRouter();
  const list = useQuery({ queryKey: ["studio-mappings", entity?.id], queryFn: studioMapApi.list, enabled: !!entity });
  const [creating, setCreating] = useState(false);
  const [f, setF] = useState({ key: "", name: "", object_type: "employee_master" });
  const create = async () => {
    try {
      const v = await studioMapApi.create({ ...f, spec: { fields: [{ target: "employee_id", source: "employee_id", type: "id", required: true }] },
        change_reason: "First version" });
      router.push(`/studio/mapping/${v.id}`);
    } catch (e) {
      toast.error("Not created", { description: e instanceof Error ? e.message : "" });
    }
  };
  return (
    <div className="space-y-5">
      <PageHeader eyebrow="PeopleOps Studio" title="Data mapping"
        description="How another system's fields become this product's fields. A mapping transforms values — dates, numbers, codes, lookups — and never judges them: payroll rules stay in validation. Every version is previewed on sample data before it is published, and a published version never changes." />
      <StudioNav />
      <Card><CardContent className="space-y-3 py-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-base font-semibold text-ink-900">Mapping profiles</h2>
          {WRITE.has(activeRole ?? "") && !creating ? <button type="button" onClick={() => setCreating(true)} className="inline-flex items-center gap-1.5 rounded-lg bg-brand-600 px-3 py-2 text-sm font-semibold text-white"><Plus size={14} /> New mapping</button> : null}
        </div>
        {creating ? (
          <div className="grid gap-2 rounded-xl border border-brand-200 p-3 md:grid-cols-[1fr_1fr_14rem_auto]">
            <input aria-label="Key" className={FIELD} placeholder="key, e.g. hrms-employees" value={f.key} onChange={(e) => setF({ ...f, key: e.target.value.toLowerCase() })} />
            <input aria-label="Name" className={FIELD} placeholder="Name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
            <select aria-label="Maps" className={FIELD} value={f.object_type} onChange={(e) => setF({ ...f, object_type: e.target.value })}>
              {Object.entries(OBJECT_LABEL).filter(([k]) => k !== "validation").map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <button type="button" disabled={f.key.length < 2} onClick={() => void create()} className="rounded-lg bg-brand-600 px-3 py-2 text-sm font-semibold text-white disabled:opacity-40">Create draft</button>
          </div>
        ) : null}
        {list.error ? <AlertBanner variant="error" title="Could not load mappings">{(list.error as Error).message}</AlertBanner> : null}
        {!list.data ? <Skeleton className="h-24 w-full" /> : list.data.length === 0 ? (
          <p className="rounded-xl border border-dashed border-ink-200 px-4 py-6 text-center text-sm text-ink-500">No mappings yet. Without one, records are read by the field names the upload screens recognise.</p>
        ) : (
          <div className="scrollbar-thin overflow-x-auto"><table className="w-full text-sm">
            <thead className="text-left text-xs text-ink-500"><tr><th className="py-1">Mapping</th><th>Maps</th><th>In force</th><th>Versions</th></tr></thead>
            <tbody className="divide-y divide-ink-100">
              {list.data.map((m) => (
                <tr key={m.key}>
                  <td className="py-2"><Link href={`/studio/mapping/${m.versions[0].id}`} className="font-medium text-brand-700 hover:underline">{m.name}</Link>
                    <span className="block font-mono text-xs text-ink-500">{m.key}</span></td>
                  <td className="text-xs">{OBJECT_LABEL[m.object_type] ?? m.object_type}</td>
                  <td>{m.in_force ? <Badge variant="success">v{m.in_force.version}</Badge> : <Badge variant="secondary">nothing published</Badge>}</td>
                  <td className="text-xs">{m.versions.map((v) => <Link key={v.id} href={`/studio/mapping/${v.id}`} className="mr-2 underline">v{v.version} {v.status}</Link>)}</td>
                </tr>
              ))}
            </tbody>
          </table></div>
        )}
      </CardContent></Card>
    </div>
  );
}
