"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { AlertTriangle, ArrowDown, ArrowUp, ArrowUpRight, Info, Pencil, Search, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useEntity } from "@/context/EntityContext";
import { CHART, categorical, statusColors, tooltipStyle } from "@/lib/chart-colors";
import { fetchDimensions } from "@/lib/cost-analysis";
import {
  dashboardsApi, formatValue,
  type Catalogue, type Chart, type PeriodSpec, type QueryResult, type Tile, type Unit,
} from "@/lib/dashboards";
import { cn } from "@/lib/utils";

const FIELD = "h-8 w-full rounded-lg border border-ink-200 bg-white px-2 text-[13px] text-ink-900";
const UNIT_LABEL: Record<Unit, string> = { inr: "₹", number: "count", pct: "%" };

/**
 * One tile: asks its question now, and shows the answer with what it rests
 * on — metric, breakdown, period, units, company and filters — so a figure
 * is never read without its basis.
 */
export function TileView({ tile, period, onEdit, onRemove, onMoveUp, onMoveDown, position }: {
  tile: Tile; period: PeriodSpec; onEdit?: () => void; onRemove?: () => void;
  onMoveUp?: () => void; onMoveDown?: () => void; position?: string;
}) {
  const { entity } = useEntity();
  const q = useQuery<QueryResult>({
    queryKey: ["dash-tile", entity?.id, tile, period],
    queryFn: () => dashboardsApi.query(tile, period),
    enabled: !!entity,
    retry: false,
    placeholderData: (prev) => prev,
  });
  const r = q.data;
  const filters = Object.entries(tile.filters ?? {}).filter(([, v]) => v.length);
  return (
    <section
      aria-label={tile.title}
      className={cn("flex flex-col rounded-xl border border-ink-200 bg-white p-4 shadow-soft", tile.chart === "kpi" ? "min-h-[9rem]" : "h-full min-h-[19rem]")}
    >
      <header className="mb-2 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="truncate text-[13px] font-semibold text-ink-900">{tile.title}</h3>
          {r ? (
            <p className="text-xs text-ink-500" title={r.metric.definition}>
              {r.metric.label}
              {r.breakdown.key !== "period" || tile.chart !== "kpi" ? ` · by ${r.breakdown.label.toLowerCase()}` : ""}
              {" · "}{r.period.label}
              {" · "}<span className="text-ink-500">{UNIT_LABEL[r.metric.unit]}</span>
            </p>
          ) : <Skeleton className="mt-1 h-3 w-40" />}
          {filters.length ? (
            <p className="mt-0.5 truncate text-[11px] text-ink-500">
              Filtered: {filters.map(([k, v]) => `${k.replaceAll("_", " ")} ${v.join(", ")}`).join(" · ")}
            </p>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-0.5">
          {r ? (
            <span title={`${r.metric.definition}\nSource: ${r.dataset.source}${entity ? `\nCompany: ${entity.name}` : ""}`} className="p-1 text-ink-500">
              <Info size={13} aria-hidden /><span className="sr-only">How this is calculated: {r.metric.definition}. Source: {r.dataset.source}.</span>
            </span>
          ) : null}
          {onMoveUp ? <IconAction label={`Move ${tile.title} earlier${position ? ` (now ${position})` : ""}`} onClick={onMoveUp}><ArrowUp size={13} /></IconAction> : null}
          {onMoveDown ? <IconAction label={`Move ${tile.title} later${position ? ` (now ${position})` : ""}`} onClick={onMoveDown}><ArrowDown size={13} /></IconAction> : null}
          {onEdit ? <IconAction label={`Edit ${tile.title}`} onClick={onEdit}><Pencil size={13} /></IconAction> : null}
          {onRemove ? <IconAction label={`Remove ${tile.title}`} onClick={onRemove} danger><Trash2 size={13} /></IconAction> : null}
        </div>
      </header>
      <div className={cn("relative flex-1 transition-opacity duration-fast", q.isFetching && r ? "opacity-60" : "")}>
        {q.isLoading ? (
          <Skeleton className="h-full min-h-[6rem] w-full" />
        ) : q.error ? (
          <p className="flex items-start gap-1.5 text-xs text-danger-700" role="alert">
            <AlertTriangle size={13} className="mt-0.5 shrink-0" aria-hidden />
            {q.error instanceof Error ? q.error.message : "This tile could not be computed."}
          </p>
        ) : r ? <Answer r={r} chart={tile.chart} /> : null}
      </div>
      {r ? <BasisLine r={r} /> : null}
    </section>
  );
}

function IconAction({ label, onClick, children, danger }: { label: string; onClick: () => void; children: React.ReactNode; danger?: boolean }) {
  return (
    <button type="button" onClick={onClick} aria-label={label} title={label}
      className={cn("rounded-md p-1 transition-colors", danger ? "text-ink-500 hover:bg-danger-50 hover:text-danger-700" : "text-ink-500 hover:bg-ink-100 hover:text-ink-900")}>
      {children}
    </button>
  );
}

function Answer({ r, chart }: { r: QueryResult; chart: Chart }) {
  if (r.status === "no_data" || r.status === "no_budget") {
    return (
      <div className="flex h-full flex-col justify-center rounded-lg border border-dashed border-ink-200 px-3 py-4 text-center">
        <p className="text-[13px] font-medium text-ink-700">No data</p>
        <p className="mt-0.5 text-xs text-ink-500">{r.note ?? "Nothing was recorded for this period."} This is not a zero.</p>
      </div>
    );
  }
  const unit = r.metric.unit;
  if (chart === "kpi") {
    return (
      <div>
        {r.total === null ? (
          <p className="text-sm font-medium text-ink-500">Not available</p>
        ) : (
          <p className="num text-[28px] font-semibold leading-tight tracking-tight text-ink-900">{formatValue(r.total, unit)}</p>
        )}
        {r.total === null && r.status === "ok" ? <p className="text-xs text-ink-500">Could not be computed from the data present.</p> : null}
        {r.note ? <p className="mt-1 text-xs text-ink-500">{r.note}</p> : null}
      </div>
    );
  }
  if (!r.rows.length) return <p className="text-[13px] text-ink-500">{r.note ?? "Nothing to show."}</p>;
  const data = r.rows.map((row) => ({ name: row.label, value: row.value, drill: row.drill }));
  const missing = r.rows.filter((row) => row.value === null).length;
  const fmt = (v: unknown) => formatValue(typeof v === "number" ? v : null, unit);

  if (chart === "table") {
    return (
      <div className="scrollbar-thin max-h-64 overflow-auto">
        <table className="w-full border-separate border-spacing-0 text-[13px]">
          <caption className="sr-only">{r.metric.label} by {r.breakdown.label}</caption>
          <thead>
            <tr className="[&>th]:sticky [&>th]:top-0 [&>th]:bg-white [&>th]:py-1 [&>th]:text-xs [&>th]:font-medium [&>th]:text-ink-500">
              <th scope="col" className="text-left">{r.breakdown.label}</th>
              <th scope="col" className="text-right">{r.metric.label}</th>
            </tr>
          </thead>
          <tbody>
            {r.rows.map((row) => (
              <tr key={row.key} className="[&>td]:border-b [&>td]:border-ink-100 [&>td]:py-1.5">
                <td className="pr-2 text-ink-700">
                  {row.drill ? <Link href={row.drill} className="inline-flex items-center gap-1 hover:underline">{row.label} <ArrowUpRight size={11} aria-hidden /></Link> : row.label}
                </td>
                <td className="num text-right text-ink-900">{row.value === null ? <span className="text-ink-500">no data</span> : formatValue(row.value, unit)}</td>
              </tr>
            ))}
            {r.total !== null ? (
              <tr className="font-semibold"><td className="py-1.5">Total</td><td className="num py-1.5 text-right">{formatValue(r.total, unit)}</td></tr>
            ) : null}
          </tbody>
        </table>
      </div>
    );
  }

  const tick = { fontSize: 11, fill: CHART.axis };
  const periodAxis = r.breakdown.key === "period";
  const drillTo = (d: unknown) => {
    const drill = (d as { payload?: { drill?: string | null } })?.payload?.drill;
    if (drill) window.location.assign(drill);
  };
  // Long category names read along a horizontal bar; months read along an axis.
  const horizontal = chart === "bar" && !periodAxis;
  // One measure, one colour — unless the categories are states, which wear theirs.
  const barColors = statusColors(data.map((d) => d.name));
  const slices = chart === "pie" ? categorical(data.filter((d) => d.value !== null)).map((d) => ({ ...d, drill: d.name.startsWith("Other (") ? null : d.drill })) : [];
  const height = horizontal ? Math.min(20 * 16, Math.max(160, data.length * 28 + 24)) : 208;

  return (
    <figure className="text-ink-500">
      <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          {chart === "line" ? (
            <LineChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
              <CartesianGrid stroke={CHART.grid} vertical={false} />
              <XAxis dataKey="name" tick={tick} tickLine={false} axisLine={false} />
              <YAxis tick={tick} tickLine={false} axisLine={false} width={60} allowDecimals={unit !== "number"} tickFormatter={(v: number) => formatValue(v, unit)} />
              <Tooltip formatter={fmt} {...tooltipStyle} />
              {/* Gaps stay gaps: a missing value is not drawn as zero. */}
              <Line type="monotone" dataKey="value" name={r.metric.label} stroke={CHART.primary} strokeWidth={2} dot={{ r: 3 }} connectNulls={false} isAnimationActive={false} />
            </LineChart>
          ) : chart === "pie" ? (
            <PieChart>
              <Pie data={slices} dataKey="value" nameKey="name" innerRadius={48} outerRadius={78} paddingAngle={1} isAnimationActive={false}
                onClick={drillTo} cursor="pointer">
                {slices.map((d) => <Cell key={d.name} fill={d.color} stroke="#fff" strokeWidth={2} />)}
              </Pie>
              <Tooltip formatter={fmt} {...tooltipStyle} />
              <Legend verticalAlign="middle" align="right" layout="vertical" iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 12 }}
                formatter={(name: string) => {
                  const hit = slices.find((d) => d.name === name);
                  return <span style={{ color: CHART.text }}>{name} <span className="num" style={{ color: "#111522" }}>{hit ? formatValue(hit.value, unit) : ""}</span></span>;
                }} />
            </PieChart>
          ) : horizontal ? (
            <BarChart data={data} layout="vertical" margin={{ top: 0, right: 16, left: 0, bottom: 0 }}>
              <CartesianGrid stroke={CHART.grid} horizontal={false} />
              <XAxis type="number" tick={tick} tickLine={false} axisLine={false} allowDecimals={unit !== "number"} tickFormatter={(v: number) => formatValue(v, unit)} />
              <YAxis type="category" dataKey="name" tick={tick} tickLine={false} axisLine={false} width={176} interval={0}
                tickFormatter={(v: string) => (v.length > 27 ? `${v.slice(0, 26)}…` : v)} />
              <Tooltip formatter={fmt} {...tooltipStyle} />
              <Bar dataKey="value" name={r.metric.label} fill={CHART.primary} radius={[0, 4, 4, 0]} cursor="pointer" onClick={drillTo} isAnimationActive={false} barSize={16}>
                {barColors ? data.map((d, i) => <Cell key={d.name} fill={barColors[i]} />) : null}
              </Bar>
            </BarChart>
          ) : (
            <BarChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
              <CartesianGrid stroke={CHART.grid} vertical={false} />
              <XAxis dataKey="name" tick={tick} tickLine={false} axisLine={false} />
              <YAxis tick={tick} tickLine={false} axisLine={false} width={60} allowDecimals={unit !== "number"} tickFormatter={(v: number) => formatValue(v, unit)} />
              <Tooltip formatter={fmt} {...tooltipStyle} />
              <Bar dataKey="value" name={r.metric.label} fill={CHART.primary} radius={[4, 4, 0, 0]} cursor="pointer" onClick={drillTo} isAnimationActive={false} />
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
      <figcaption className="sr-only">
        {r.metric.label} by {r.breakdown.label}, {r.period.label}: {r.rows.map((row) => `${row.label} ${row.value === null ? "no data" : formatValue(row.value, unit)}`).join("; ")}.
      </figcaption>
      {missing ? <p className="mt-1 text-[11px] text-warning-800">{missing} of {r.rows.length} {periodAxis ? "periods" : "values"} have no data and are left as gaps, not zeros.</p> : null}
    </figure>
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
      <span className={warn ? "font-medium text-warning-800" : "text-ink-500"}>
        {parts.length ? parts.join(" · ") : r.dataset.source}
      </span>
      {firstDrill ? <Link href={firstDrill} className="inline-flex items-center gap-0.5 font-medium text-brand-700 hover:underline">Open <ArrowUpRight size={11} aria-hidden /></Link> : null}
    </div>
  );
}

const FINDING_FILTERS: Record<string, string[]> = {
  state: ["open", "acknowledged", "waived", "resolved"],
  severity: ["CRITICAL", "WARNING", "INFO"],
};

type LibraryEntry = { dataset: string; datasetLabel: string; metric: string | null; kpi: string | null; label: string; definition: string };

/**
 * Dataset → Metric → Breakdown → Chart → Filters → Title, with a live
 * preview for the dashboard's own period. The metric library above it
 * searches every dataset's metrics and the company's custom KPIs at once.
 */
export function TileBuilder({ catalogue, initial, onSave, onCancel, period }: {
  catalogue: Catalogue; initial?: Tile; onSave: (tile: Tile) => void; onCancel: () => void; period?: PeriodSpec;
}) {
  const [tile, setTile] = useState<Tile>(initial ?? {
    title: "", dataset: "payroll_cost", metric: "ctc", kpi_id: null, breakdown: "period", chart: "bar",
    granularity: "month", filters: {}, period: { inherit: true },
  });
  const [search, setSearch] = useState("");
  const dims = useQuery({ queryKey: ["bi", "dimensions"], queryFn: fetchDimensions });
  const ds = catalogue.datasets.find((d) => d.key === tile.dataset) ?? catalogue.datasets[0];
  const kpis = catalogue.kpis.filter((k) => k.dataset === ds.key);
  const set = (patch: Partial<Tile>) => setTile((t) => ({ ...t, ...patch }));
  const valueOptions = (key: string): string[] =>
    FINDING_FILTERS[key] ?? dims.data?.dimensions.find((d) => d.key === key)?.values ?? [];
  const metricLabel = tile.kpi_id
    ? kpis.find((k) => k.id === tile.kpi_id)?.name
    : ds.metrics.find((m) => m.key === tile.metric)?.label;

  const library = useMemo<LibraryEntry[]>(() => [
    ...catalogue.datasets.flatMap((d) => d.metrics.map((m) => ({ dataset: d.key, datasetLabel: d.label, metric: m.key, kpi: null, label: m.label, definition: m.definition }))),
    ...catalogue.kpis.map((k) => ({ dataset: k.dataset, datasetLabel: catalogue.datasets.find((d) => d.key === k.dataset)?.label ?? k.dataset, metric: null, kpi: k.id, label: k.name, definition: `Custom KPI = ${k.formula}` })),
  ], [catalogue]);
  const found = search.trim()
    ? library.filter((e) => `${e.label} ${e.datasetLabel} ${e.definition}`.toLowerCase().includes(search.trim().toLowerCase())).slice(0, 8)
    : [];
  const pick = (e: LibraryEntry) => {
    const next = catalogue.datasets.find((d) => d.key === e.dataset)!;
    set({
      dataset: e.dataset, metric: e.metric, kpi_id: e.kpi, filters: {},
      breakdown: next.breakdowns.some((b) => b.key === tile.breakdown) ? tile.breakdown : next.breakdowns[0].key,
    });
    setSearch("");
  };
  const step = "space-y-1.5 rounded-lg border border-ink-200 bg-white p-3";

  return (
    <section aria-label={initial ? "Edit tile" : "New tile"} className="space-y-3 rounded-xl border border-brand-200 bg-brand-50/40 p-4">
      <div className="relative">
        <label className="text-xs font-medium text-ink-700" htmlFor="metric-search">Find a metric</label>
        <div className="relative mt-1">
          <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-500" aria-hidden />
          <input id="metric-search" type="search" value={search} onChange={(e) => setSearch(e.target.value)} autoComplete="off"
            placeholder="Search every dataset's metrics and your custom KPIs — e.g. overdue, employer, headcount"
            className="h-9 w-full rounded-lg border border-ink-200 bg-white pl-8 pr-2 text-[13px] focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20" />
        </div>
        {search.trim() ? (
          <ul className="absolute z-20 mt-1 max-h-72 w-full overflow-auto rounded-xl border border-ink-200 bg-white p-1 shadow-elevated" role="listbox" aria-label="Matching metrics">
            {found.length ? found.map((e) => (
              <li key={`${e.dataset}:${e.metric ?? e.kpi}`}>
                <button type="button" role="option" aria-selected={false} onClick={() => pick(e)} className="w-full rounded-lg px-2.5 py-1.5 text-left hover:bg-ink-50">
                  <span className="block text-[13px] text-ink-900">{e.label} <span className="text-xs text-ink-500">· {e.datasetLabel}</span></span>
                  <span className="block truncate text-xs text-ink-500">{e.definition}</span>
                </button>
              </li>
            )) : <li className="px-2.5 py-2 text-xs text-ink-500">No metric matches “{search}”.</li>}
          </ul>
        ) : null}
      </div>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        <div className={step}>
          <p className="text-xs font-medium text-ink-700">1 · Dataset</p>
          <select aria-label="Dataset" className={FIELD} value={tile.dataset} onChange={(e) => {
            const next = catalogue.datasets.find((d) => d.key === e.target.value)!;
            set({ dataset: next.key, metric: next.metrics[0].key, kpi_id: null, breakdown: next.breakdowns[0].key, filters: {} });
          }}>
            {catalogue.datasets.map((d) => <option key={d.key} value={d.key}>{d.label}</option>)}
          </select>
          <p className="text-[11px] text-ink-500">{ds.source}</p>
        </div>
        <div className={step}>
          <p className="text-xs font-medium text-ink-700">2 · Metric</p>
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
          <p className="text-xs font-medium text-ink-700">3 · Breakdown</p>
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
          <p className="text-xs font-medium text-ink-700" id="chart-label">4 · Chart</p>
          <div className="flex flex-wrap gap-1.5" role="group" aria-labelledby="chart-label">
            {catalogue.charts.map((c) => (
              <button key={c} type="button" onClick={() => set({ chart: c })} aria-pressed={tile.chart === c}
                className={cn("rounded-md px-2.5 py-1 text-xs font-medium", tile.chart === c ? "bg-ink-900 text-white" : "bg-white text-ink-700 ring-1 ring-ink-200 hover:bg-ink-50")}>
                {c === "kpi" ? "Single figure" : c[0].toUpperCase() + c.slice(1)}
              </button>
            ))}
          </div>
        </div>
        <div className={cn(step, "xl:col-span-2")}>
          <p className="text-xs font-medium text-ink-700">5 · Filters (optional)</p>
          {ds.filters.length === 0 ? <p className="text-[11px] text-ink-500">This dataset has no filters.</p> : (
            <div className="grid gap-2 sm:grid-cols-2">
              {ds.filters.map((f) => {
                const opts = valueOptions(f);
                if (!opts.length) return null;
                return (
                  <label key={f} className="text-[11px] text-ink-600">
                    {f.replaceAll("_", " ")} <span className="text-ink-500">(Ctrl/⌘-click for several)</span>
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
        <label className="min-w-[16rem] flex-1 text-xs font-medium text-ink-700">6 · Title
          <input className={cn(FIELD, "mt-1 h-9")} value={tile.title} placeholder={metricLabel ?? "Tile title"}
            onChange={(e) => set({ title: e.target.value })} />
        </label>
        <Button variant="ghost" onClick={onCancel}>Cancel</Button>
        <Button onClick={() => onSave({ ...tile, title: tile.title.trim() || metricLabel || "Tile" })}>{initial ? "Update tile" : "Add tile"}</Button>
      </div>
      <div>
        <p className="mb-1 text-xs font-medium text-ink-500">Preview — the dashboard&apos;s period, live data</p>
        <TileView tile={{ ...tile, title: tile.title || metricLabel || "Preview" }} period={period ?? { preset: "last_6" }} />
      </div>
    </section>
  );
}
