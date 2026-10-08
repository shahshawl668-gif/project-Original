"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Circle, KeyRound, ListChecks, PlugZap, ServerCog } from "lucide-react";

import { useEntity } from "@/context/EntityContext";
import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { StudioNav } from "@/components/studio/StudioNav";
import { RunLine, fmtTime } from "@/components/studio/RunBits";
import { STATUS_LABEL, runTitle, studioApi, type RunStatus } from "@/lib/studio";

const MANAGE = new Set(["owner", "manager"]);

/**
 * PeopleOps Studio — where a company's systems are connected to PeopleOpsLab.
 *
 * The overview answers three questions at a glance: is anything connected,
 * did the last data that arrived land, and what needs someone's attention.
 * The setup checklist is computed from what exists, not ticked by hand.
 */
export default function StudioOverviewPage() {
  const { entity, organization, activeRole } = useEntity();
  const q = useQuery({ queryKey: ["studio-overview", entity?.id], queryFn: studioApi.overview, enabled: !!entity, retry: false });
  const canManage = MANAGE.has(activeRole ?? "");

  if (q.error) {
    return (
      <div className="space-y-5">
        <PageHeader eyebrow="PeopleOps Studio" title="Studio" />
        <AlertBanner variant="error" title="Studio could not be opened">{(q.error as Error).message}</AlertBanner>
      </div>
    );
  }

  const data = q.data;
  const runs7 = data?.runs_last_7_days ?? {};
  const totalRuns = Object.values(runs7).reduce((a, b) => a + (b ?? 0), 0);
  const steps = data ? [
    { done: data.service_accounts.total > 0, label: "Create a service account for the system that will send data",
      href: "/studio/api", hint: "API Centre → New service account" },
    { done: data.keys.active > 0, label: "Issue it a key, scoped to what it needs",
      href: "/studio/api", hint: "The key is shown once — store it in that system's secret store" },
    { done: totalRuns > 0 || !!data.last_run, label: "Send a first batch — try /check first; it stores nothing",
      href: "/studio/api#docs", hint: "Copy an example from the documentation" },
    { done: !!data.last_run && data.last_run.status === "completed",
      label: "See it land: counts reconcile, nothing rejected", href: "/studio/runs", hint: "Run history" },
  ] : [];

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="PeopleOps Studio"
        title="Connect your systems"
        description={<>Send employee master, CTC, attendance and salary registers from your HRMS or payroll system, start validation, and read results — through a documented, versioned API. Studio never runs payroll: it moves data in and lets the validation engine judge it.</>}
      />
      <StudioNav />
      {entity && (
        <Card><CardContent className="space-y-3 py-5">
          <p className="text-xs font-semibold uppercase tracking-wide text-brand-700">Selected company</p>
          <h2 className="text-lg font-semibold text-ink-900 dark:text-white">{entity.name} <span className="text-sm font-normal text-ink-500">({entity.code})</span></h2>
          <p className="text-sm text-ink-600">Workspace: {organization?.name ?? "—"}. Studio connections, mappings, workflows and runs on this page belong to the selected company. Switch company in the application header before setting up another client.</p>
          <p className="text-xs text-ink-500">The integration API uses a shared address. A service account key is limited to its named companies; requests with more than one company on the key must supply X-Company-Id. Give each client and source system a separate key.</p>
          <div className="flex flex-wrap gap-2">
            <Link href="/studio/connections" className="rounded-lg bg-brand-600 px-3 py-2 text-sm font-semibold text-white">Connect a source system</Link>
            <Link href="/studio/mapping" className="rounded-lg border border-ink-200 px-3 py-2 text-sm font-semibold">Map a client file</Link>
            <Link href="/studio/api" className="rounded-lg border border-ink-200 px-3 py-2 text-sm font-semibold">Create an API key</Link>
            <Link href="/studio/developer" className="rounded-lg border border-ink-200 px-3 py-2 text-sm font-semibold">Test custom logic</Link>
            <Link href="/studio/python" className="rounded-lg border border-ink-200 px-3 py-2 text-sm font-semibold">Build a Python integration</Link>
          </div>
        </CardContent></Card>
      )}

      {!data ? <Skeleton className="h-64 w-full rounded-2xl" /> : (
        <>
          {!data.worker_enabled ? (
            <AlertBanner variant="warning" title="No background worker on this server">
              Imports and validations are queued but will not run until a worker is started. Set VALIDATION_WORKER_ENABLED=true or run <code>python -m app.worker</code>.
            </AlertBanner>
          ) : null}

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Stat icon={ServerCog} label="Service accounts" value={data.service_accounts.total}
              note={`${data.service_accounts.active} active`} />
            <Stat icon={KeyRound} label="Keys in use" value={data.keys.active}
              note={data.keys.expiring_within_14_days.length ? `${data.keys.expiring_within_14_days.length} expire within 14 days` : "none expiring soon"}
              warn={data.keys.expiring_within_14_days.length > 0} />
            <Stat icon={PlugZap} label="Runs, last 7 days" value={totalRuns}
              note={Object.entries(runs7).map(([s, n]) => `${n} ${STATUS_LABEL[s as RunStatus]?.toLowerCase() ?? s}`).join(" · ") || "no activity"} />
            <Stat icon={ListChecks} label="Last run" value={data.last_run ? STATUS_LABEL[data.last_run.status] : "—"}
              note={data.last_run ? `${runTitle(data.last_run)} · ${fmtTime(data.last_run.queued_at)}` : "nothing has arrived yet"} />
          </div>

          <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
            <Card><CardContent className="space-y-3 py-5">
              <h2 className="text-base font-semibold text-ink-900 dark:text-white">Set up an integration</h2>
              <p className="text-xs text-ink-500">Four steps. Each ticks itself when it has actually happened for {data.company.name}.</p>
              <ol className="space-y-2">
                {steps.map((s, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm">
                    {s.done ? <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-success-600" /> : <Circle size={16} className="mt-0.5 shrink-0 text-ink-300" />}
                    <span>
                      <Link href={s.href} className={s.done ? "text-ink-500 line-through" : "font-medium text-brand-700 hover:underline dark:text-brand-300"}>{s.label}</Link>
                      <span className="block text-xs text-ink-500">{s.hint}</span>
                    </span>
                  </li>
                ))}
              </ol>
              {!canManage ? <p className="text-xs text-ink-500">Creating service accounts and keys needs an owner or manager.</p> : null}
            </CardContent></Card>

            <Card><CardContent className="space-y-3 py-5">
              <h2 className="flex items-center gap-2 text-base font-semibold text-ink-900 dark:text-white"><AlertTriangle size={16} className="text-warning-600" /> Needs attention</h2>
              {data.needs_attention.length === 0 ? (
                <p className="text-sm text-ink-500">No failed or partly rejected runs in the last seven days.</p>
              ) : (
                <ul className="divide-y divide-ink-100 dark:divide-white/5">
                  {data.needs_attention.map((r) => <RunLine key={r.id} run={r} />)}
                </ul>
              )}
              {data.keys.expiring_within_14_days.length ? (
                <div className="rounded-lg border border-warning-200 bg-warning-50 p-3 text-xs text-warning-900 dark:border-warning-500/30 dark:bg-warning-500/10 dark:text-warning-100">
                  Keys expiring soon: {data.keys.expiring_within_14_days.map((k) => `${k.prefix} (${new Date(k.expires_at).toLocaleDateString("en-IN")})`).join(", ")}. Rotate them in the API Centre.
                </div>
              ) : null}
            </CardContent></Card>
          </div>

          <Card><CardContent className="space-y-3 py-5">
            <h2 className="text-base font-semibold text-ink-900 dark:text-white">What Studio does</h2>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              {data.sections.map((s) => s.available && s.href ? (
                <Link key={s.key} href={s.href} className="rounded-xl border border-ink-200 p-3 transition hover:border-brand-400 hover:bg-brand-50/40 dark:border-white/10">
                  <span className="flex items-center justify-between text-sm font-semibold text-ink-900 dark:text-white">{s.label} <Badge variant="success">available</Badge></span>
                  <span className="block pt-1 text-xs text-ink-500">{s.summary}</span>
                </Link>
              ) : (
                <div key={s.key} className="rounded-xl border border-dashed border-ink-200 p-3 opacity-70 dark:border-white/10">
                  <span className="flex items-center justify-between text-sm font-semibold text-ink-600 dark:text-ink-300">{s.label} <Badge variant="secondary">not in this release</Badge></span>
                  <span className="block pt-1 text-xs text-ink-500">{s.summary}</span>
                </div>
              ))}
            </div>
          </CardContent></Card>
        </>
      )}
    </div>
  );
}

function Stat({ icon: Icon, label, value, note, warn }: {
  icon: React.ComponentType<{ size?: number | string; className?: string }>; label: string; value: React.ReactNode; note: string; warn?: boolean;
}) {
  return (
    <Card><CardContent className="space-y-1 py-4">
      <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-ink-500"><Icon size={14} /> {label}</p>
      <p className="text-2xl font-bold text-ink-900 dark:text-white">{value}</p>
      <p className={warn ? "text-xs text-warning-700" : "text-xs text-ink-500"}>{note}</p>
    </CardContent></Card>
  );
}
