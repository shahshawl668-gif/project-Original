"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowLeft, Copy, Pencil, Plus, Save, Trash2 } from "lucide-react";

import { useEntity } from "@/context/EntityContext";
import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Skeleton } from "@/components/ui/skeleton";
import { TileBuilder, TileView } from "@/components/dashboards/Tiles";
import { PERIOD_PRESETS, dashboardsApi, type Dashboard, type PeriodSpec, type Tile } from "@/lib/dashboards";
import { cn } from "@/lib/utils";

const FIELD =
  "rounded-lg border border-ink-200 bg-white px-2.5 py-1.5 text-sm text-ink-900 dark:border-white/10 dark:bg-white/[0.04] dark:text-white";
const WRITE_ROLES = new Set(["owner", "manager", "analyst"]);

export default function DashboardPage() {
  const { id } = useParams<{ id: string }>();
  const { entity, activeRole } = useEntity();
  const router = useRouter();
  const qc = useQueryClient();
  const board = useQuery({ queryKey: ["dashboard", entity?.id, id], queryFn: () => dashboardsApi.get(id), enabled: !!entity && !!id, retry: false });
  const catalogue = useQuery({ queryKey: ["dash-catalogue", entity?.id], queryFn: dashboardsApi.catalogue, enabled: !!entity });

  const [draft, setDraft] = useState<Dashboard | null>(null);
  const [editing, setEditing] = useState(false);
  const [building, setBuilding] = useState<number | "new" | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (board.data) setDraft(board.data); }, [board.data]);

  if (board.error) {
    return (
      <div className="space-y-4">
        <PageHeader title="Dashboard" />
        <AlertBanner variant="error" title="This dashboard could not be opened">
          It may be private to someone else, belong to another company, or have been deleted.{" "}
          <Link href="/dashboards" className="font-semibold underline">All dashboards</Link>
        </AlertBanner>
      </div>
    );
  }
  if (!draft || !catalogue.data) return <Skeleton className="h-96 w-full rounded-2xl" />;

  const period = draft.layout.period ?? { preset: "last_6" };
  const setPeriod = (p: PeriodSpec) => setDraft({ ...draft, layout: { ...draft.layout, period: p } });
  const setTiles = (tiles: Tile[]) => setDraft({ ...draft, layout: { ...draft.layout, tiles } });

  const save = async () => {
    setBusy(true);
    try {
      const saved = await dashboardsApi.update(draft.id, {
        name: draft.name, description: draft.description, visibility: draft.visibility,
        period: draft.layout.period, tiles: draft.layout.tiles,
      });
      setDraft(saved);
      setEditing(false);
      toast.success("Dashboard saved");
      await qc.invalidateQueries({ queryKey: ["dashboards", entity?.id] });
    } catch (e) {
      toast.error("Not saved", { description: e instanceof Error ? e.message : "" });
    } finally {
      setBusy(false);
    }
  };

  const act = async (fn: () => Promise<unknown>, after: () => void) => {
    setBusy(true);
    try { await fn(); after(); } catch (e) {
      toast.error("Refused", { description: e instanceof Error ? e.message : "" });
    } finally { setBusy(false); }
  };

  return (
    <div className="space-y-5">
      <PageHeader
        title={editing ? "Edit dashboard" : draft.name}
        description={`${draft.description ? `${draft.description} · ` : ""}${draft.visibility === "shared" ? "Shared with this company" : "Private to you"}${draft.owner_email && !draft.mine ? ` · by ${draft.owner_email}` : ""}`}
        actions={
          <div className="flex flex-wrap gap-2">
            <Link href="/dashboards" className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-ink-200 px-3 text-sm"><ArrowLeft size={14} /> All</Link>
            <button type="button" disabled={busy} onClick={() => void act(() => dashboardsApi.duplicate(draft.id).then((d) => router.push(`/dashboards/${d.id}`)), () => undefined)}
              className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-ink-200 px-3 text-sm"><Copy size={14} /> Duplicate</button>
            {draft.can_edit && !editing ? (
              <button type="button" onClick={() => setEditing(true)} className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-brand-600 px-3 text-sm font-semibold text-white"><Pencil size={14} /> Edit</button>
            ) : null}
            {editing ? (
              <>
                <button type="button" disabled={busy} onClick={() => void save()} className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-brand-600 px-3 text-sm font-semibold text-white"><Save size={14} /> Save</button>
                <button type="button" onClick={() => { setDraft(board.data!); setEditing(false); setBuilding(null); }} className="h-9 px-3 text-sm text-ink-600">Cancel</button>
                <button type="button" disabled={busy} onClick={() => { if (window.confirm(`Delete “${draft.name}”?`)) void act(() => dashboardsApi.remove(draft.id), () => router.push("/dashboards")); }}
                  className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-danger-200 px-3 text-sm text-danger-700"><Trash2 size={14} /> Delete</button>
              </>
            ) : null}
          </div>
        }
      />

      {editing ? (
        <div className="grid gap-3 rounded-2xl border border-ink-200 p-4 md:grid-cols-[1fr_1fr_auto] dark:border-white/10">
          <label className="text-xs font-semibold text-ink-700">Name<input className={cn(FIELD, "mt-1 w-full")} value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></label>
          <label className="text-xs font-semibold text-ink-700">Description<input className={cn(FIELD, "mt-1 w-full")} value={draft.description ?? ""} onChange={(e) => setDraft({ ...draft, description: e.target.value })} /></label>
          <label className={cn("flex items-center gap-2 self-end pb-2 text-xs font-semibold", !WRITE_ROLES.has(activeRole ?? "") && "opacity-50")}>
            <input type="checkbox" disabled={!WRITE_ROLES.has(activeRole ?? "")} checked={draft.visibility === "shared"}
              onChange={(e) => setDraft({ ...draft, visibility: e.target.checked ? "shared" : "private" })} />
            Share with everyone who can open this company
          </label>
        </div>
      ) : null}

      <div className="flex flex-wrap items-end gap-2">
        <label className="text-xs font-semibold text-ink-700">Period
          <select aria-label="Dashboard period" className={cn(FIELD, "mt-1 block")} value={period.preset ?? "last_6"}
            onChange={(e) => setPeriod({ ...period, preset: e.target.value as PeriodSpec["preset"] })}>
            {PERIOD_PRESETS.map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
          </select>
        </label>
        {period.preset === "custom" ? (
          <>
            <label className="text-xs font-semibold text-ink-700">From<input type="month" className={cn(FIELD, "mt-1 block")} value={period.from ?? ""} onChange={(e) => setPeriod({ ...period, from: e.target.value })} /></label>
            <label className="text-xs font-semibold text-ink-700">To<input type="month" className={cn(FIELD, "mt-1 block")} value={period.to ?? ""} onChange={(e) => setPeriod({ ...period, to: e.target.value })} /></label>
          </>
        ) : null}
        <p className="pb-2 text-[11px] text-ink-500">{editing ? "Saved as the dashboard's default period." : "Applies to every tile that does not set its own."}</p>
      </div>

      {building === "new" ? (
        <TileBuilder catalogue={catalogue.data} onCancel={() => setBuilding(null)}
          onSave={(t) => { setTiles([...draft.layout.tiles, t]); setBuilding(null); }} />
      ) : null}

      {draft.layout.tiles.length === 0 && building !== "new" ? (
        <div className="rounded-2xl border border-dashed border-ink-200 px-6 py-12 text-center text-sm text-ink-500 dark:border-white/10">
          This dashboard has no tiles yet.{" "}
          {draft.can_edit ? <button type="button" className="font-semibold text-brand-700 underline" onClick={() => { setEditing(true); setBuilding("new"); }}>Add the first tile</button> : null}
        </div>
      ) : null}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {draft.layout.tiles.map((t, i) => building === i ? (
          <div key={t.id ?? i} className="md:col-span-2 xl:col-span-3">
            <TileBuilder catalogue={catalogue.data!} initial={t} onCancel={() => setBuilding(null)}
              onSave={(nt) => { setTiles(draft.layout.tiles.map((x, j) => (j === i ? nt : x))); setBuilding(null); }} />
          </div>
        ) : (
          <div key={t.id ?? i} className={t.chart === "kpi" ? "" : "md:col-span-1"}>
            <TileView tile={t} period={period}
              onEdit={editing ? () => setBuilding(i) : undefined}
              onRemove={editing ? () => setTiles(draft.layout.tiles.filter((_, j) => j !== i)) : undefined} />
          </div>
        ))}
      </div>

      {editing && building !== "new" ? (
        <button type="button" onClick={() => setBuilding("new")} className="inline-flex items-center gap-1.5 rounded-lg border border-brand-300 px-3 py-2 text-sm font-semibold text-brand-700">
          <Plus size={14} /> Add a tile
        </button>
      ) : null}
    </div>
  );
}
