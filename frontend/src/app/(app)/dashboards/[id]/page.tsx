"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Copy, Loader2, Pencil, Plus, Trash2 } from "lucide-react";

import { useEntity } from "@/context/EntityContext";
import { BackLink } from "@/components/layout/BackLink";
import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/drawer";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";
import { TileBuilder, TileView } from "@/components/dashboards/Tiles";
import { PERIOD_PRESETS, dashboardsApi, type Dashboard, type PeriodSpec, type Tile } from "@/lib/dashboards";
import { dateTime } from "@/lib/format";
import { useUnsavedChanges } from "@/lib/unsaved";
import { cn } from "@/lib/utils";

const FIELD = "h-9 rounded-lg border border-ink-200 bg-white px-2.5 text-[13px] text-ink-900";
const WRITE_ROLES = new Set(["owner", "manager", "analyst"]);

/**
 * One dashboard. Viewing and editing are separate modes: in view mode nothing
 * on the page changes the saved dashboard; in edit mode every change is a
 * draft until Save, the page says so, and leaving asks first.
 */
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
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [dragging, setDragging] = useState<number | null>(null);
  const [dropAt, setDropAt] = useState<number | null>(null);
  useEffect(() => { if (board.data) setDraft(board.data); }, [board.data]);

  const dirty = useMemo(() => editing && !!draft && !!board.data && JSON.stringify(draft) !== JSON.stringify(board.data), [editing, draft, board.data]);
  useUnsavedChanges(dirty);

  if (board.error) {
    return (
      <div className="space-y-4">
        <PageHeader title="Dashboard" />
        <AlertBanner variant="error" title="This dashboard could not be opened">
          It may be private to someone else, belong to another company, or have been deleted.{" "}
          <Link href="/dashboards" className="font-medium underline">All dashboards</Link>
        </AlertBanner>
      </div>
    );
  }
  if (!draft || !catalogue.data) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-64" />
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-72 rounded-xl" />)}</div>
      </div>
    );
  }

  const period = draft.layout.period ?? { preset: "last_6" };
  const setPeriod = (p: PeriodSpec) => setDraft({ ...draft, layout: { ...draft.layout, period: p } });
  const tiles = draft.layout.tiles;
  const setTiles = (next: Tile[]) => setDraft({ ...draft, layout: { ...draft.layout, tiles: next } });
  const move = (i: number, d: -1 | 1) => {
    const j = i + d;
    if (j < 0 || j >= tiles.length) return;
    const next = tiles.slice();
    [next[i], next[j]] = [next[j], next[i]];
    setTiles(next);
  };
  // Dragging a tile onto another puts it in that tile's place.
  const moveTo = (from: number, to: number) => {
    if (from === to || from < 0 || to < 0 || from >= tiles.length || to >= tiles.length) return;
    const next = tiles.slice();
    const [tile] = next.splice(from, 1);
    next.splice(to, 0, tile);
    setTiles(next);
  };
  const canShare = WRITE_ROLES.has(activeRole ?? "");

  const save = async () => {
    setBusy(true);
    try {
      const saved = await dashboardsApi.update(draft.id, {
        name: draft.name, description: draft.description, visibility: draft.visibility,
        period: draft.layout.period, tiles: draft.layout.tiles,
      });
      qc.setQueryData(["dashboard", entity?.id, id], saved);
      setDraft(saved);
      setEditing(false);
      setBuilding(null);
      toast.success(saved.visibility === "shared" ? "Saved — shared with this company" : "Saved — private to you");
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
      <BackLink fallback="/dashboards">All dashboards</BackLink>
      <PageHeader
        title={draft.name}
        description={draft.description || undefined}
        meta={
          <>
            <StatusPill tone={draft.visibility === "shared" ? "info" : "neutral"}>{draft.visibility === "shared" ? "Shared with this company" : "Private to you"}</StatusPill>
            {draft.owner_email && !draft.mine ? <span>by {draft.owner_email}</span> : null}
            {draft.updated_at ? <span>saved {dateTime(draft.updated_at)}</span> : null}
            {entity ? <span>· {entity.name}</span> : null}
          </>
        }
        actions={
          editing ? (
            <>
              <Button variant="destructive-outline" disabled={busy} onClick={() => setConfirmDelete(true)}><Trash2 size={14} /> Delete</Button>
              <Button variant="ghost" disabled={busy} onClick={() => { setDraft(board.data!); setEditing(false); setBuilding(null); }}>{dirty ? "Discard changes" : "Done"}</Button>
              <Button disabled={busy || !dirty} onClick={() => void save()}>{busy ? <Loader2 size={14} className="animate-spin" /> : null} Save</Button>
            </>
          ) : (
            <>
              <Button variant="outline" disabled={busy} onClick={() => void act(() => dashboardsApi.duplicate(draft.id).then((d) => router.push(`/dashboards/${d.id}`)), () => undefined)}>
                <Copy size={14} /> Duplicate
              </Button>
              {draft.can_edit ? <Button onClick={() => setEditing(true)}><Pencil size={14} /> Edit</Button> : null}
            </>
          )
        }
      />

      {editing ? (
        <section aria-label="Dashboard settings" className="space-y-3 rounded-xl border border-brand-200 bg-brand-50/40 p-4">
          <p className="text-[13px] text-ink-800">
            <b>Editing.</b> {dirty ? "Changes are not saved until you press Save." : "Nothing changed yet."} Drag a tile onto another to move it there, or use the arrows on each tile.
          </p>
          <div className="grid gap-3 md:grid-cols-[1fr_1fr]">
            <label className="text-xs font-medium text-ink-700">Name<input className={cn(FIELD, "mt-1 w-full")} value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></label>
            <label className="text-xs font-medium text-ink-700">Description<input className={cn(FIELD, "mt-1 w-full")} value={draft.description ?? ""} onChange={(e) => setDraft({ ...draft, description: e.target.value })} /></label>
          </div>
          <fieldset className={cn(!canShare && "opacity-60")}>
            <legend className="text-xs font-medium text-ink-700">Who can see it</legend>
            <div className="mt-1 flex flex-wrap gap-4 text-[13px]">
              {(["private", "shared"] as const).map((v) => (
                <label key={v} className="flex items-center gap-1.5">
                  <input type="radio" name="visibility" className="accent-brand-600" disabled={!canShare} checked={draft.visibility === v} onChange={() => setDraft({ ...draft, visibility: v })} />
                  {v === "private" ? "Only me" : "Everyone who can open this company"}
                </label>
              ))}
            </div>
            <p className="mt-1 text-xs text-ink-500">Sharing shows the questions, not answers: each viewer sees only data their own access allows.</p>
          </fieldset>
        </section>
      ) : null}

      <div className="flex flex-wrap items-end gap-2">
        <label className="text-xs font-medium text-ink-700">Period
          <select aria-label="Dashboard period" className={cn(FIELD, "mt-1 block")} value={period.preset ?? "last_6"}
            onChange={(e) => setPeriod({ ...period, preset: e.target.value as PeriodSpec["preset"] })}>
            {PERIOD_PRESETS.map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
          </select>
        </label>
        {period.preset === "custom" ? (
          <>
            <label className="text-xs font-medium text-ink-700">From<input type="month" className={cn(FIELD, "mt-1 block")} value={period.from ?? ""} onChange={(e) => setPeriod({ ...period, from: e.target.value })} /></label>
            <label className="text-xs font-medium text-ink-700">To<input type="month" className={cn(FIELD, "mt-1 block")} value={period.to ?? ""} onChange={(e) => setPeriod({ ...period, to: e.target.value })} /></label>
          </>
        ) : null}
        <p className="pb-2 text-xs text-ink-500">{editing ? "Saved as the dashboard's default period." : "For this visit; tiles with their own period keep it."}</p>
      </div>

      {building === "new" ? (
        <TileBuilder catalogue={catalogue.data} period={period} onCancel={() => setBuilding(null)}
          onSave={(t) => { setTiles([...tiles, t]); setBuilding(null); }} />
      ) : null}

      {tiles.length === 0 && building !== "new" ? (
        <div className="rounded-xl border border-dashed border-ink-200 bg-white px-6 py-12 text-center text-[13px] text-ink-500">
          This dashboard has no tiles yet.{" "}
          {draft.can_edit ? <button type="button" className="font-medium text-brand-700 underline" onClick={() => { setEditing(true); setBuilding("new"); }}>Add the first tile</button> : null}
        </div>
      ) : null}

      <div className="grid items-start gap-4 md:grid-cols-2 xl:grid-cols-3">
        {tiles.map((t, i) => building === i ? (
          <div key={t.id ?? i} className="md:col-span-2 xl:col-span-3">
            <TileBuilder catalogue={catalogue.data!} initial={t} period={period} onCancel={() => setBuilding(null)}
              onSave={(nt) => { setTiles(tiles.map((x, j) => (j === i ? nt : x))); setBuilding(null); }} />
          </div>
        ) : (
          <div key={t.id ?? i}
            draggable={editing && building === null}
            onDragStart={(e) => { setDragging(i); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", String(i)); }}
            onDragOver={(e) => { if (dragging === null) return; e.preventDefault(); e.dataTransfer.dropEffect = "move"; if (dropAt !== i) setDropAt(i); }}
            onDragLeave={() => { if (dropAt === i) setDropAt(null); }}
            onDrop={(e) => { e.preventDefault(); if (dragging !== null) moveTo(dragging, i); setDragging(null); setDropAt(null); }}
            onDragEnd={() => { setDragging(null); setDropAt(null); }}
            className={cn("h-full rounded-xl transition-shadow duration-fast",
              editing && building === null && "cursor-grab active:cursor-grabbing",
              dragging === i && "opacity-50",
              dropAt === i && dragging !== null && dragging !== i && "ring-2 ring-brand-500 ring-offset-2")}>
            <TileView tile={t} period={period}
              position={`${i + 1} of ${tiles.length}`}
              draggable={editing && building === null}
              onMoveUp={editing && i > 0 ? () => move(i, -1) : undefined}
              onMoveDown={editing && i < tiles.length - 1 ? () => move(i, 1) : undefined}
              onEdit={editing ? () => setBuilding(i) : undefined}
              onRemove={editing ? () => setTiles(tiles.filter((_, j) => j !== i)) : undefined} />
          </div>
        ))}
      </div>

      {editing && building !== "new" ? (
        <Button variant="outline" onClick={() => setBuilding("new")}><Plus size={14} /> Add a tile</Button>
      ) : null}

      <Dialog
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        title={`Delete “${draft.name}”?`}
        description={draft.visibility === "shared" ? "It is shared: it disappears for everyone in this company. The data behind it is not affected." : "The data behind it is not affected."}
        footer={
          <>
            <Button variant="outline" onClick={() => setConfirmDelete(false)}>Keep it</Button>
            <Button variant="destructive" disabled={busy} onClick={() => { setConfirmDelete(false); void act(() => dashboardsApi.remove(draft.id), () => router.push("/dashboards")); }}>Delete dashboard</Button>
          </>
        }
      >{null}</Dialog>
    </div>
  );
}
