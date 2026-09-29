"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Bar, BarChart, CartesianGrid, Cell, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { AlertTriangle, ArrowUpRight, Info, Loader2 } from "lucide-react";

import { useEntity } from "@/context/EntityContext";
import { fetchDimensions } from "@/lib/cost-analysis";
import {
  dashboardsApi, formatValue,
  type Catalogue, type Chart, type PeriodSpec, type QueryResult, type Tile,
} from "@/lib/dashboards";
import { cn } from "@/lib/utils";

const COLORS = ["#0284c7", "#6366f1", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6", "#14b8a6", "#f97316"];
const FIELD =
  "w-full rounded-lg border border-ink-200 bg-white px-2.5 py-1.5 text-sm text-ink-900";

/** One tile: asks its question now, and shows the answer with what it rests on. */
export function TileView({ tile, period, onEdit, onRemove }: {
  tile: Tile; period: PeriodSpec; onEdit?: () => void; onRemove?: () => void;
}) {
  const { entity } = useEntity();
  const q = useQuery<QueryResult>({
    queryKey: ["dash-tile", entity?.id, tile, period],
    queryFn: () => dashboardsApi.query(tile, period),
    enabled: !!entity,
    retry: false,
  });
  const r = q.data;
  return (
    <div className={cn("flex flex-col rounded-2xl border border-ink-200/70 bg-white p-4 shadow-soft",
      tile.chart === "kpi" ? "min-h-[9rem]" : "min-h-[18rem]")}>
      <div className="mb-2 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold text-ink-900">{tile.title}</h3>
          {r ? (
            <p className="truncate text-[11px] text-ink-500" title={r.metric.definition}>
              {r.metric.label} · {r.breakdown.key !== "period" || tile.chart !== "kpi" ? `by ${r.breakdown.label.toLowerCase()} · ` : ""}{r.period.label}
            </p>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-1 text-[11px]">
          {r ? <span title={`${r.metric.definition}\nSource: ${r.dataset.source}`} className="text-ink-400"><Info size={13} /></span> : null}
          {onEdit ? <button type="button" onClick={onEdit} className="rounded px-1.5 py-0.5 font-semibold text-brand-700 hover:bg-brand-50">Edit</button> : null}
          {onRemove ? <button type="button" onClick={onRemove} className="rounded px-1.5 py-0.5 text-ink-500 hover:bg-ink-100" aria-label={`Remove ${tile.title}`}>Remove</button> : null}
        </div>
      </div>
      <div className="flex-1">
        {q.isLoading ? (
          <div className="flex h-full items-center justify-center text-ink-400"><Loader2 className="animate-spin" size={18} /></div>
        ) : q.error ? (
          <p className="flex items-start gap-1.5 text-xs text-danger-700"><AlertTriangle size={13} className="mt-0.5 shrink-0" />
            {q.error instanceof Error ? q.error.message : "This tile could not be computed."}</p>
        ) : r ? <Answer r={r} chart={tile.chart} /> : null}
      </div>
      {r ? <BasisLine r={r} /> : null}
    </div>
  );
}

function Answer({ r, chart }: { r: QueryResult; chart: Chart }) {
  if (r.status === "no_data" || r.status === "no_budget") {
    return <p className="text-sm text-ink-500">{r.note ?? "No data for this period."} <span className="font-semibold">Not a zero.</span></p>;
  }
  const unit = r.metric.unit;
  if (chart === "kpi") {
    return (
      <div>
        <p className="font-display text-3xl font-bold tabular-nums text-ink-900">{formatValue(r.total, unit)}</p>
        {r.total === null && r.status === "ok" ? <p className="text-xs text-ink-500">Could not be computed from the data present.</p> : null}
        {r.note ? <p className="mt-1 text-xs text-ink-500">{r.note}</p> : null}
      </div>
    );
  }
  if (!r.rows.length) return <p className="text-sm text-ink-500">{r.note ?? "Nothing to show."}</p>;
  const data = r.rows.map((row) => ({ name: row.label, value: row.value, drill: row.drill }));
  if (chart === "table") {
    return (
      <div className="max-h-64 overflow-auto">
        <table className="w-full text-sm">
          <tbody>
            {r.rows.map((row) => (
              <tr key={row.key} className="border-b border-ink-100 last:border-0">
                <td className="py-1.5 pr-2 text-ink-700">
                  {row.drill ? <Link href={row.drill} className="inline-flex items-center gap-1 hover:underline">{row.label} <ArrowUpRight size={11} /></Link> : row.label}
                </td>
                <td className="py-1.5 text-right tabular-nums text-ink-900">{formatValue(row.value, unit)}</td>
              </tr>
            ))}
            {r.total !== null ? (
              <tr className="font-semibold"><td className="py-1.5">Total</td><td className="py-1.5 text-right tabular-nums">{formatValue(r.total, unit)}</td></tr>
            ) : null}
          </tbody>
        </table>
      </div>
    );
  }
  const tick = { fontSize: 11, fill: "currentColor" };
  return (
    <div className="h-52 text-ink-500">
      <ResponsiveContainer width="100%" height="100%">
        {chart === "line" ? (
          <LineChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid stroke="rgba(148,163,184,0.2)" vertical={false} />
            <XAxis dataKey="name" tick={tick} tickLine={false} axisLine={false} />
            <YAxis tick={tick} tickLine={false} axisLine={false} width={56} tickFormatter={(v: number) => formatValue(v, unit)} />
            <Tooltip formatter={(v) => formatValue(typeof v === "number" ? v : null, unit)} />
            {/* Gaps stay gaps: a missing value is not drawn as zero. */}
            <Line type="monotone" dataKey="value" stroke={COLORS[0]} strokeWidth={2.5} dot={{ r: 3 }} connectNulls={false} />
          </LineChart>
        ) : chart === "pie" ? (
          <PieChart>
            <Pie data={data.filter((d) => d.value !== null)} dataKey="value" nameKey="name" outerRadius={80}
              label={({ name }) => String(name)}>
              {data.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
            </Pie>
            <Tooltip formatter={(v) => formatValue(typeof v === "number" ? v : null, unit)} />
          </PieChart>
        ) : (
          <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid stroke="rgba(148,163,184,0.2)" vertical={false} />
            <XAxis dataKey="name" tick={tick} tickLine={false} axisLine={false} interval={0} />
            <YAxis tick={tick} tickLine={false} axisLine={false} width={56} tickFormatter={(v: number) => formatValue(v, unit)} />
            <Tooltip formatter={(v) => formatValue(typeof v === "number" ? v : null, unit)} />
            <Bar dataKey="value" fill={COLORS[0]} radius={[4, 4, 0, 0]} cursor="pointer"
              onClick={(d) => {
                const drill = (d as { payload?: { drill?: string | null } })?.payload?.drill;
                if (drill) window.location.assign(drill);
              }} />
          </BarChart>
        )}
      </ResponsiveContainer>
    </div>
  );
}

function BasisLine({ r }: { r: QueryResult }) {
  const b = r.basis;
  const parts: string[] = [];
  if (b) {
    if (b.missing_months.length) parts.push(`${b.missing_months.length} month(s) with no register`);
    if (b.unvalidated_months) parts.push(`${b.unvalidated_months} month(s) not validated or changed since`);
    if (b.last_uploaded_at) parts.push(`data as of ${new Date(b.last_uploaded_at).toLocaleDateString("en-IN")}`);
  }
  const warn = !!b && (b.missing_months.length > 0 || b.unvalidated_months > 0);
  const firstDrill = r.rows.find((row) => row.drill)?.drill;
  return (
    <div className="mt-2 flex flex-wrap items-center justify-between gap-2 border-t border-ink-100 pt-2 text-[11px]">
      <span className={warn ? "font-semibold text-warning-800" : "text-ink-400"}>
        {parts.length ? parts.join(" · ") : r.dataset.source}
      </span>
      {firstDrill ? <Link href={firstDrill} className="inline-flex items-center gap-0.5 font-semibold text-brand-700 hover:underline">Open <ArrowUpRight size={11} /></Link> : null}
    </div>
  );
}

const FINDING_FILTERS: Record<string, string[]> = {
  state: ["open", "acknowledged", "waived", "resolved"],
  severity: ["CRITICAL", "WARNING", "INFO"],
};

/** Dataset → Metric → Breakdown → Chart → Filters → Save. */
export function TileBuilder({ catalogue, initial, onSave, onCancel }: {
  catalogue: Catalogue; initial?: Tile; onSave: (tile: Tile) => void; onCancel: () => void;
}) {
  const [tile, setTile] = useState<Tile>(initial ?? {
    title: "", dataset: "payroll_cost", metric: "ctc", kpi_id: null, breakdown: "period", chart: "bar",
    granularity: "month", filters: {}, period: { inherit: true },
  });
  const dims = useQuery({ queryKey: ["bi", "dimensions"], queryFn: fetchDimensions });
  const ds = catalogue.datasets.find((d) => d.key === tile.dataset) ?? catalogue.datasets[0];
  const kpis = catalogue.kpis.filter((k) => k.dataset === ds.key);
  const set = (patch: Partial<Tile>) => setTile((t) => ({ ...t, ...patch }));
  const valueOptions = (key: string): string[] =>
    FINDING_FILTERS[key] ?? dims.data?.dimensions.find((d) => d.key === key)?.values ?? [];
  const metricLabel = tile.kpi_id
    ? kpis.find((k) => k.id === tile.kpi_id)?.name
    : ds.metrics.find((m) => m.key === tile.metric)?.label;
  const step = "space-y-1 rounded-xl border border-ink-200 p-3";

  return (
    <div className="space-y-3 rounded-2xl border border-brand-200 bg-brand-50/40 p-4">
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        <div className={step}>
          <p className="text-xs font-semibold text-ink-700">1 · Dataset</p>
          <select aria-label="Dataset" className={FIELD} value={tile.dataset} onChange={(e) => {
            const next = catalogue.datasets.find((d) => d.key === e.target.value)!;
            set({ dataset: next.key, metric: next.metrics[0].key, kpi_id: null, breakdown: next.breakdowns[0].key, filters: {} });
          }}>
            {catalogue.datasets.map((d) => <option key={d.key} value={d.key}>{d.label}</option>)}
          </select>
          <p className="text-[11px] text-ink-500">{ds.source}</p>
        </div>
        <div className={step}>
          <p className="text-xs font-semibold text-ink-700">2 · Metric</p>
          <select aria-label="Metric" className={FIELD} value={tile.kpi_id ? `kpi:${tile.kpi_id}` : tile.metric ?? ""} onChange={(e) => {
            const v = e.target.value;
            if (v.startsWith("kpi:")) set({ kpi_id: v.slice(4), metric: null });
            else set({ metric: v, kpi_id: null });
          }}>
            {ds.metrics.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
            {kpis.length ? <optgroup label="Custom KPIs">{kpis.map((k) => <option key={k.id} value={`kpi:${k.id}`}>{k.name}</option>)}</optgroup> : null}
          </select>
          <p className="text-[11px] text-ink-500">
            {tile.kpi_id ? `= ${kpis.find((k) => k.id === tile.kpi_id)?.formula ?? ""}` : ds.metrics.find((m) => m.key === tile.metric)?.definition}
          </p>
        </div>
        <div className={step}>
          <p className="text-xs font-semibold text-ink-700">3 · Breakdown</p>
          <select aria-label="Breakdown" className={FIELD} value={tile.breakdown} onChange={(e) => set({ breakdown: e.target.value })}>
            {ds.breakdowns.map((b) => <option key={b.key} value={b.key}>{b.label}</option>)}
          </select>
          {tile.breakdown === "period" && ds.key === "payroll_cost" ? (
            <select aria-label="Granularity" className={FIELD} value={tile.granularity} onChange={(e) => set({ granularity: e.target.value as Tile["granularity"] })}>
              <option value="month">By month</option><option value="quarter">By quarter</option><option value="year">By year</option>
            </select>
          ) : null}
        </div>
        <div className={step}>
          <p className="text-xs font-semibold text-ink-700">4 · Chart</p>
          <div className="flex flex-wrap gap-1.5">
            {catalogue.charts.map((c) => (
              <button key={c} type="button" onClick={() => set({ chart: c })} aria-pressed={tile.chart === c}
                className={cn("rounded-lg px-2.5 py-1 text-xs font-semibold", tile.chart === c ? "bg-ink-900 text-white" : "bg-white text-ink-600 ring-1 ring-ink-200")}>
                {c === "kpi" ? "Single figure" : c[0].toUpperCase() + c.slice(1)}
              </button>
            ))}
          </div>
        </div>
        <div className={cn(step, "xl:col-span-2")}>
          <p className="text-xs font-semibold text-ink-700">5 · Filters (optional)</p>
          {ds.filters.length === 0 ? <p className="text-[11px] text-ink-500">This dataset has no filters.</p> : (
            <div className="grid gap-2 sm:grid-cols-2">
              {ds.filters.map((f) => {
                const opts = valueOptions(f);
                if (!opts.length) return null;
                return (
                  <label key={f} className="text-[11px] text-ink-600">
                    {f.replaceAll("_", " ")}
                    <select multiple aria-label={`Filter ${f}`} className={cn(FIELD, "mt-0.5 h-20")} value={tile.filters[f] ?? []}
                      onChange={(e) => set({ filters: { ...tile.filters, [f]: Array.from(e.target.selectedOptions).map((o) => o.value) } })}>
                      {opts.map((o) => <option key={o} value={o}>{o}</option>)}
                    </select>
                  </label>
                );
              })}
            </div>
          )}
        </div>
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <label className="min-w-64 flex-1 text-xs font-semibold text-ink-700">6 · Title
          <input className={cn(FIELD, "mt-1")} value={tile.title} placeholder={metricLabel ?? "Tile title"}
            onChange={(e) => set({ title: e.target.value })} />
        </label>
        <button type="button" onClick={() => onSave({ ...tile, title: tile.title.trim() || metricLabel || "Tile" })}
          className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white">Save tile</button>
        <button type="button" onClick={onCancel} className="px-3 py-2 text-sm text-ink-600">Cancel</button>
      </div>
      <div className="rounded-xl bg-white p-2">
        <p className="mb-1 text-[11px] font-semibold text-ink-400">Preview</p>
        <TileView tile={{ ...tile, title: tile.title || metricLabel || "Preview" }} period={{ preset: "last_6" }} />
      </div>
    </div>
  );
}
