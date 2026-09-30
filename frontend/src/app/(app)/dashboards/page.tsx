"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { LayoutGrid, Lock, Plus, Sigma, Users } from "lucide-react";

import { useEntity } from "@/context/EntityContext";
import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { dashboardsApi, type Catalogue, type Dashboard, type Kpi, type Unit } from "@/lib/dashboards";
import { cn } from "@/lib/utils";

const FIELD =
  "w-full rounded-lg border border-ink-200 bg-white px-3 py-2 text-sm text-ink-900";
const WRITE_ROLES = new Set(["owner", "manager", "analyst"]);

/**
 * Dashboards: personal and shared boards for this company, eight ready-made
 * templates, and custom KPIs. Every figure on a board is computed when it is
 * opened, from this company's data only.
 */
export default function DashboardsPage() {
  const { entity, activeRole } = useEntity();
  const router = useRouter();
  const qc = useQueryClient();
  const canShare = WRITE_ROLES.has(activeRole ?? "");
  const boards = useQuery({ queryKey: ["dashboards", entity?.id], queryFn: dashboardsApi.list, enabled: !!entity });
  const catalogue = useQuery({ queryKey: ["dash-catalogue", entity?.id], queryFn: dashboardsApi.catalogue, enabled: !!entity });
  const [busy, setBusy] = useState(false);

  const create = async (fn: () => Promise<Dashboard>) => {
    setBusy(true);
    try {
      const d = await fn();
      await qc.invalidateQueries({ queryKey: ["dashboards", entity?.id] });
      router.push(`/dashboards/${d.id}`);
    } catch (e) {
      toast.error("Not created", { description: e instanceof Error ? e.message : "" });
      setBusy(false);
    }
  };

  const mine = (boards.data ?? []).filter((d) => d.mine);
  const shared = (boards.data ?? []).filter((d) => !d.mine);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Dashboards"
        description="Your own boards and the ones shared with this company. Each tile is a question — dataset, metric, breakdown, chart, filters, period — answered from this company's data when you open it."
        actions={
          <button type="button" disabled={busy} className="inline-flex items-center gap-2 rounded-lg bg-brand-600 px-3 py-2 text-sm font-semibold text-white"
            onClick={() => void create(() => dashboardsApi.create({ name: "Untitled dashboard", visibility: "private", period: { preset: "last_6" }, tiles: [] }))}>
            <Plus size={15} /> New dashboard
          </button>
        }
      />
      {boards.error ? <AlertBanner variant="error" title="Could not load dashboards">{(boards.error as Error).message}</AlertBanner> : null}

      <div className="grid gap-4 lg:grid-cols-2">
        <BoardList title="Mine" icon={Lock} boards={mine} loading={boards.isLoading} empty="No dashboards of your own yet — start from a template below." />
        <BoardList title="Shared with this company" icon={Users} boards={shared} loading={boards.isLoading} empty="Nobody has shared a dashboard here yet." />
      </div>

      <Card><CardContent className="space-y-3 py-5">
        <h2 className="flex items-center gap-2 text-base font-semibold text-ink-900"><LayoutGrid size={16} /> Start from a template</h2>
        <p className="text-xs text-ink-500">A template makes a private copy you can use as it is or change. Nothing is shared until you share it.</p>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {(catalogue.data?.templates ?? []).map((t) => (
            <button key={t.key} type="button" disabled={busy} onClick={() => void create(() => dashboardsApi.fromTemplate(t.key))}
              className="rounded-xl border border-ink-200 p-3 text-left transition hover:border-brand-400 hover:bg-brand-50/40">
              <span className="block text-sm font-semibold text-ink-900">{t.name}</span>
              <span className="block pt-0.5 text-xs text-ink-500">{t.description}</span>
              <span className="block pt-1 text-[11px] text-ink-500">{t.tiles} tiles</span>
            </button>
          ))}
        </div>
      </CardContent></Card>

      {catalogue.data ? <KpiPanel catalogue={catalogue.data} canShare={canShare} /> : null}
    </div>
  );
}

function BoardList({ title, icon: Icon, boards, loading, empty }: {
  title: string; icon: React.ComponentType<{ size?: number | string; className?: string }>;
  boards: Dashboard[]; loading: boolean; empty: string;
}) {
  return (
    <Card><CardContent className="py-5">
      <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold text-ink-900"><Icon size={14} className="text-ink-500" /> {title}</h2>
      {loading ? <Skeleton className="h-20 w-full" /> : boards.length === 0 ? <p className="text-sm text-ink-500">{empty}</p> : (
        <ul className="divide-y divide-ink-100">
          {boards.map((d) => (
            <li key={d.id} className="flex items-center justify-between gap-2 py-2">
              <Link href={`/dashboards/${d.id}`} className="min-w-0 font-medium text-brand-700 hover:underline">{d.name}</Link>
              <span className="shrink-0 text-xs text-ink-500">
                {d.layout.tiles.length} tiles · {d.visibility}{!d.mine && d.owner_email ? ` · by ${d.owner_email}` : ""}
              </span>
            </li>
          ))}
        </ul>
      )}
    </CardContent></Card>
  );
}

function KpiPanel({ catalogue, canShare }: { catalogue: Catalogue; canShare: boolean }) {
  const { entity } = useEntity();
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [dataset, setDataset] = useState("payroll_cost");
  const [formula, setFormula] = useState("");
  const [unit, setUnit] = useState<Unit>("pct");
  const [shared, setShared] = useState(false);
  const [busy, setBusy] = useState(false);
  const ds = catalogue.datasets.find((d) => d.key === dataset)!;

  const save = async () => {
    setBusy(true);
    try {
      await dashboardsApi.createKpi({ name, dataset, formula, unit, visibility: shared ? "shared" : "private" });
      toast.success("KPI saved");
      setName(""); setFormula("");
      await qc.invalidateQueries({ queryKey: ["dash-catalogue", entity?.id] });
    } catch (e) {
      toast.error("Not saved", { description: e instanceof Error ? e.message : "" });
    } finally {
      setBusy(false);
    }
  };
  const remove = async (k: Kpi) => {
    try {
      await dashboardsApi.deleteKpi(k.id);
      await qc.invalidateQueries({ queryKey: ["dash-catalogue", entity?.id] });
    } catch (e) {
      toast.error("Not deleted", { description: e instanceof Error ? e.message : "" });
    }
  };

  return (
    <Card><CardContent className="space-y-3 py-5">
      <h2 className="flex items-center gap-2 text-base font-semibold text-ink-900"><Sigma size={16} /> Custom KPIs</h2>
      <p className="text-xs text-ink-500">A KPI is a formula over one dataset&apos;s metrics — for example <code>employer_cost / gross * 100</code>. It is evaluated safely on the server; a value that divides by zero or lacks an input shows as “—”, never 0.</p>
      {catalogue.kpis.length ? (
        <ul className="divide-y divide-ink-100 text-sm">
          {catalogue.kpis.map((k) => (
            <li key={k.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <span><strong>{k.name}</strong> <span className="font-mono text-xs text-ink-500">= {k.formula}</span>
                <span className="ml-2 text-xs text-ink-500">{catalogue.datasets.find((d) => d.key === k.dataset)?.label} · {k.unit} · {k.visibility}</span></span>
              {k.can_edit ? <button type="button" onClick={() => void remove(k)} className="text-xs text-ink-500 hover:text-danger-700">Delete</button> : null}
            </li>
          ))}
        </ul>
      ) : null}
      <div className="grid gap-2 md:grid-cols-[1fr_12rem_1fr_8rem]">
        <input aria-label="KPI name" className={FIELD} placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} />
        <select aria-label="KPI dataset" className={FIELD} value={dataset} onChange={(e) => setDataset(e.target.value)}>
          {catalogue.datasets.map((d) => <option key={d.key} value={d.key}>{d.label}</option>)}
        </select>
        <input aria-label="KPI formula" className={cn(FIELD, "font-mono")} placeholder="employer_cost / gross * 100" value={formula} onChange={(e) => setFormula(e.target.value)} />
        <select aria-label="KPI unit" className={FIELD} value={unit} onChange={(e) => setUnit(e.target.value as Unit)}>
          <option value="pct">Percent</option><option value="inr">Rupees</option><option value="number">Number</option>
        </select>
      </div>
      <p className="text-[11px] text-ink-500">Metrics you can use: {ds.metrics.map((m) => m.key).join(", ")}</p>
      <div className="flex items-center gap-3">
        <label className={cn("flex items-center gap-1.5 text-xs", !canShare && "opacity-50")}>
          <input type="checkbox" disabled={!canShare} checked={shared} onChange={(e) => setShared(e.target.checked)} /> Share with this company
        </label>
        <button type="button" disabled={busy || !name.trim() || !formula.trim()} onClick={() => void save()}
          className="rounded-lg bg-brand-600 px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50">Save KPI</button>
      </div>
    </CardContent></Card>
  );
}
