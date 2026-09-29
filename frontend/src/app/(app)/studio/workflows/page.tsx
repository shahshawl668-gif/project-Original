"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus, Workflow as WorkflowIcon } from "lucide-react";

import { useEntity } from "@/context/EntityContext";
import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { StudioNav } from "@/components/studio/StudioNav";
import { StatusBadge, fmtTime } from "@/components/studio/RunBits";
import { studioFlowApi, type WorkflowDefinition } from "@/lib/studio";

const FIELD =
  "w-full rounded-lg border border-ink-200 bg-white px-3 py-2 text-sm text-ink-900 dark:border-white/10 dark:bg-white/[0.04] dark:text-white";
const WRITE = new Set(["owner", "manager", "analyst"]);

/** Starting points: each is an ordinary definition the builder opens for editing. */
const TEMPLATES: { key: string; label: string; help: string; definition: WorkflowDefinition }[] = [
  {
    key: "ready-validate", label: "Validate when inputs are ready",
    help: "When the month's register and master are both present, validate it and tell the payroll team.",
    definition: {
      trigger: { type: "inputs.ready", required: ["register", "master"] }, conditions: [],
      actions: [{ type: "start_validation", params: { period: "context" } },
                { type: "notify", params: { roles: ["owner", "manager"], title: "{{period}} validated", body: "Open the results to review findings." } }],
      on_failure: [{ type: "notify", params: { roles: ["owner", "manager"], title: "{{workflow}} stopped", severity: "error" } }],
    },
  },
  {
    key: "rejections", label: "Tell someone about rejected records",
    help: "When an import or sync finishes with rejected records, notify the people who fix them.",
    definition: {
      trigger: { type: "import.completed" }, conditions: [{ field: "data.counts.rejected", op: "gt", value: 0 }],
      actions: [{ type: "notify", params: { roles: ["owner", "manager"], title: "{{event.data.counts.rejected}} record(s) rejected", severity: "warning" } }],
      on_failure: [],
    },
  },
  {
    key: "blank", label: "Start from nothing", help: "A manual workflow with one notification step.",
    definition: { trigger: { type: "manual" }, conditions: [], actions: [{ type: "notify", params: { roles: ["owner"], title: "{{workflow}} ran" } }], on_failure: [] },
  },
];

export default function WorkflowsPage() {
  const router = useRouter();
  const { entity, activeRole } = useEntity();
  const list = useQuery({ queryKey: ["studio-workflows", entity?.id], queryFn: studioFlowApi.list, enabled: !!entity });
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [template, setTemplate] = useState(TEMPLATES[0].key);
  const canWrite = WRITE.has(activeRole ?? "");

  const create = async () => {
    const t = TEMPLATES.find((x) => x.key === template)!;
    try {
      const wf = await studioFlowApi.create({ name, description: t.help, definition: t.definition });
      router.push(`/studio/workflows/${wf.id}`);
    } catch (e) {
      toast.error("Not created", { description: e instanceof Error ? e.message : "" });
    }
  };

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="PeopleOps Studio" title="Workflows"
        description="Trigger → conditions → actions. A workflow fetches, checks, validates, assigns and tells people — it never signs, waives, resolves or approves."
        actions={canWrite && !creating ? <button type="button" onClick={() => setCreating(true)} className="inline-flex items-center gap-1.5 rounded-lg bg-brand-600 px-3 py-2 text-sm font-semibold text-white"><Plus size={14} /> New workflow</button> : null} />
      <StudioNav />

      {creating ? (
        <Card><CardContent className="space-y-3 py-5">
          <input aria-label="Workflow name" className={FIELD} placeholder="Name, e.g. Monthly validation" value={name} onChange={(e) => setName(e.target.value)} />
          <div className="grid gap-2 md:grid-cols-3">
            {TEMPLATES.map((t) => (
              <label key={t.key} className="flex cursor-pointer items-start gap-2 rounded-xl border border-ink-200 p-3 text-sm dark:border-white/10">
                <input type="radio" name="template" className="mt-1" checked={template === t.key} onChange={() => setTemplate(t.key)} />
                <span><span className="font-semibold">{t.label}</span><span className="block text-xs text-ink-500">{t.help}</span></span>
              </label>
            ))}
          </div>
          <div className="flex gap-2">
            <button type="button" disabled={name.trim().length < 2} onClick={() => void create()} className="rounded-lg bg-brand-600 px-3 py-2 text-sm font-semibold text-white disabled:opacity-40">Create draft</button>
            <button type="button" onClick={() => setCreating(false)} className="px-3 py-2 text-sm text-ink-600">Cancel</button>
          </div>
          <p className="text-xs text-ink-500">A draft does nothing until an owner or manager publishes it.</p>
        </CardContent></Card>
      ) : null}

      {list.error ? <AlertBanner variant="error" title="Workflows could not be loaded">{list.error instanceof Error ? list.error.message : ""}</AlertBanner> : null}
      {!list.data ? <Skeleton className="h-40 w-full rounded-2xl" /> : list.data.length === 0 ? (
        <Card><CardContent className="py-10 text-center text-sm text-ink-500"><WorkflowIcon className="mx-auto mb-2" size={22} />No workflows yet.</CardContent></Card>
      ) : (
        <Card><CardContent className="py-2">
          <ul className="divide-y divide-ink-100 dark:divide-white/5">
            {list.data.map((w) => (
              <li key={w.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                <div className="min-w-0">
                  <Link href={`/studio/workflows/${w.id}`} className="font-semibold text-brand-700 hover:underline dark:text-brand-300">{w.name}</Link>
                  <span className="ml-2"><Badge variant={w.status === "active" ? "success" : w.status === "draft" ? "warning" : "secondary"}>{w.status}</Badge></span>
                  {w.has_changes && w.status !== "draft" ? <span className="ml-1"><Badge variant="warning">unpublished changes</Badge></span> : null}
                  <p className="text-xs text-ink-500">
                    On {(w.active_definition ?? w.definition).trigger.type.replace(/[._]/g, " ")} · {(w.active_definition ?? w.definition).actions.length} step(s)
                    {w.active_version ? ` · v${w.active_version}` : ""}{w.next_run_at ? ` · next ${fmtTime(w.next_run_at)}` : ""}
                  </p>
                  {w.last_skip ? <p className="text-xs text-warning-800">Last skipped {fmtTime(w.last_skip.at)}: {w.last_skip.reason}</p> : null}
                </div>
                <div className="text-xs text-ink-500">{w.last_run ? <Link className="inline-flex items-center gap-2" href={`/studio/runs/${w.last_run.id}`}>last run {fmtTime(w.last_run.at)} <StatusBadge status={w.last_run.status} /></Link> : "never run"}</div>
              </li>
            ))}
          </ul>
        </CardContent></Card>
      )}
    </div>
  );
}
