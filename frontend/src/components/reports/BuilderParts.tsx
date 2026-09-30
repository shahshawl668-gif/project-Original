"use client";

import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, Loader2 } from "lucide-react";
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

import { DIRECT_LABEL_MARGIN, DirectLabels } from "@/components/charts/DirectLabels";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useEntity } from "@/context/EntityContext";
import { CHART, tooltipStyle } from "@/lib/chart-colors";
import { SERIES } from "@/lib/cost-analysis";
import { count, inr, inrCompact } from "@/lib/format";
import { builderApi, type ChartData, type OutputFormat, type Pivot, type Schedule, type ScheduleInput, type Unit } from "@/lib/report-builder";
import { periodLabel } from "@/lib/workspace";
import { cn } from "@/lib/utils";

const FIELD = "h-9 w-full rounded-lg border border-ink-200 bg-white px-2.5 text-[13px] text-ink-900";

/** A value in the unit its column declares. Missing is a dash, never zero. */
export function formatValue(v: string | number | null | undefined, unit: Unit): string {
  if (v === null || v === undefined || v === "") return "—";
  if (unit === "month") return periodLabel(String(v));
  if (unit === "text") return String(v);
  const n = Number(v);
  if (unit === "inr") return inr(n);
  if (unit === "pct") return `${n.toLocaleString("en-IN", { maximumFractionDigits: 2 })}%`;
  return Number.isInteger(n) ? count(n) : n.toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

const compact = (unit: Unit) => (v: number) => (unit === "inr" ? inrCompact(v) : unit === "pct" ? `${v}%` : count(v));

/** The report's chart, as the file will draw it. */
export function PreviewChart({ chart }: { chart: ChartData }) {
  const tick = { fontSize: 11, fill: CHART.axis };
  if (chart.type === "bar") {
    const data = chart.bars.map((b) => ({ name: b.group, value: b.value }));
    return (
      <figure className="rounded-lg border border-ink-200 p-3">
        <figcaption className="mb-2 text-[13px] font-semibold text-ink-900">{chart.label} · {periodLabel(chart.period)}</figcaption>
        <div style={{ height: Math.min(360, Math.max(140, data.length * 26 + 24)) }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} layout="vertical" margin={{ top: 0, right: 24, left: 0, bottom: 0 }}>
              <CartesianGrid stroke={CHART.grid} horizontal={false} />
              <XAxis type="number" tick={tick} tickLine={false} axisLine={false} tickFormatter={compact(chart.unit)} />
              <YAxis type="category" dataKey="name" tick={tick} tickLine={false} axisLine={false} width={180} interval={0}
                tickFormatter={(v: string) => (v.length > 28 ? `${v.slice(0, 27)}…` : v)} />
              <Tooltip formatter={(v) => formatValue(v as number, chart.unit)} {...tooltipStyle} />
              <Bar dataKey="value" name={chart.label} fill={CHART.primary} radius={[0, 4, 4, 0]} barSize={16} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        {chart.omitted ? <p className="mt-1 text-xs text-ink-500">{chart.omitted === 1 ? "1 smaller group is" : `${chart.omitted} smaller groups are`} not drawn; {chart.omitted === 1 ? "it is" : "they are"} in the table.</p> : null}
      </figure>
    );
  }
  const data = chart.periods.map((p, i) => ({
    period: periodLabel(p),
    ...Object.fromEntries(chart.series.map((s) => [s.group, s.points[i]])),
  }));
  const series = chart.series.map((s, i) => ({ key: s.group, label: s.group, color: SERIES[i % SERIES.length] }));
  const labelled = series.length >= 2 && series.length <= 4;
  return (
    <figure className="rounded-lg border border-ink-200 p-3">
      <figcaption className="mb-2 text-[13px] font-semibold text-ink-900">{chart.label} over time</figcaption>
      <div className="h-[260px]">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: labelled ? DIRECT_LABEL_MARGIN : 16, left: 0, bottom: 0 }}>
            <CartesianGrid stroke={CHART.grid} vertical={false} />
            <XAxis dataKey="period" tick={tick} tickLine={false} axisLine={false} />
            <YAxis tick={tick} tickLine={false} axisLine={false} width={72} tickFormatter={compact(chart.unit)} />
            <Tooltip formatter={(v) => formatValue(v as number, chart.unit)} {...tooltipStyle} />
            <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 12, paddingTop: 8 }} />
            {/* Gaps stay gaps: a month without a value is not drawn as zero. */}
            {series.map((s) => <Line key={s.key} type="monotone" dataKey={s.key} stroke={s.color} strokeWidth={2} dot={{ r: 3 }} connectNulls={false} isAnimationActive={false} />)}
            <DirectLabels data={data} xKey="period" series={series} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      {chart.omitted ? <p className="mt-1 text-xs text-ink-500">{chart.omitted === 1 ? "1 smaller group is" : `${chart.omitted} smaller groups are`} not drawn; {chart.omitted === 1 ? "it is" : "they are"} in the table.</p> : null}
    </figure>
  );
}

/** Groups down, months across, one number — totalled only where it adds up. */
export function PivotTable({ pivot, dimLabel }: { pivot: Pivot; dimLabel: string }) {
  return (
    <div className="space-y-1.5">
      <h3 className="text-[13px] font-semibold text-ink-900">{pivot.label} by {dimLabel.toLowerCase()} and month</h3>
      <Table containerClassName="max-h-[420px] rounded-lg border border-ink-200" scrollLabel={`${pivot.label} pivot`}>
        <TableHeader>
          <TableRow>
            <TableHead pin>{dimLabel}</TableHead>
            {pivot.periods.map((p) => <TableHead key={p} numeric>{periodLabel(p)}</TableHead>)}
            {pivot.row_totals ? <TableHead numeric>Total</TableHead> : null}
          </TableRow>
        </TableHeader>
        <TableBody>
          {pivot.rows.map((r) => (
            <TableRow key={r.dimension}>
              <TableCell pin>{r.dimension}</TableCell>
              {pivot.periods.map((p) => <TableCell key={p} numeric>{formatValue(r.cells[p], pivot.unit)}</TableCell>)}
              {pivot.row_totals ? <TableCell numeric className="font-semibold">{formatValue(r.total, pivot.unit)}</TableCell> : null}
            </TableRow>
          ))}
          {pivot.column_totals ? (
            <TableRow className="bg-ink-50 font-semibold">
              <TableCell pin>Total</TableCell>
              {pivot.periods.map((p) => <TableCell key={p} numeric>{formatValue(pivot.column_totals![p], pivot.unit)}</TableCell>)}
              {pivot.row_totals ? <TableCell numeric>{formatValue(pivot.grand_total, pivot.unit)}</TableCell> : null}
            </TableRow>
          ) : null}
        </TableBody>
      </Table>
      {pivot.note ? <p className="text-xs text-ink-500">{pivot.note}</p> : null}
    </div>
  );
}

/** Schedules are set in India time, so their times are shown in it too, whatever the browser's zone. */
function indiaTime(iso: string): string {
  return `${new Date(iso).toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata", day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
  })} India time`;
}

const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const DEFAULT: ScheduleInput = { frequency: "monthly", day: 5, hour: 9, months: 1, format: "xlsx", enabled: true };

/** Generate the saved report for yourself on a timetable. Delivery is to Generated files; there is no email. */
export function ScheduleCard({ reportId, blocked, onChanged }: { reportId: string; blocked: string | null; onChanged: () => void }) {
  const { entity } = useEntity();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["rb-schedule", entity?.id, reportId], queryFn: () => builderApi.schedule(reportId), enabled: !!entity });
  const current: Schedule | null = q.data?.schedule ?? null;
  const [form, setForm] = useState<ScheduleInput>(DEFAULT);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setForm(current ? { frequency: current.frequency, day: current.day, hour: current.hour, months: current.months, format: current.format, enabled: current.enabled } : DEFAULT);
  }, [current]);

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await qc.invalidateQueries({ queryKey: ["rb-schedule", entity?.id, reportId] });
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Not saved.");
    } finally {
      setBusy(false);
    }
  }

  const set = (patch: Partial<ScheduleInput>) => setForm((f) => ({ ...f, ...patch }));
  return (
    <div className="rounded-lg border border-ink-200 p-3.5">
      <h3 className="flex items-center gap-1.5 text-[13px] font-semibold text-ink-900"><CalendarClock size={14} aria-hidden /> Schedule</h3>
      <p className="mt-1 text-xs text-ink-500">Makes this report for you on a timetable, covering the complete months before each run. Files arrive in Generated files; the product sends no email.</p>
      {current ? (
        <p className={cn("mt-2 text-xs", current.last_error ? "text-danger-700" : "text-ink-700")}>
          {current.last_error ? `Stopped: ${current.last_error}` : current.enabled && current.next_run_at ? `Next run ${indiaTime(current.next_run_at)}.` : "Paused."}
          {current.last_run_at ? ` Last ran ${indiaTime(current.last_run_at)}.` : ""}
        </p>
      ) : null}
      <div className="mt-2 grid grid-cols-2 gap-2">
        <label className="text-xs text-ink-700">Every
          <select className={cn(FIELD, "mt-1")} value={form.frequency} onChange={(e) => set({ frequency: e.target.value as "monthly" | "weekly", day: e.target.value === "weekly" ? 0 : 5 })}>
            <option value="monthly">Month</option><option value="weekly">Week</option>
          </select>
        </label>
        <label className="text-xs text-ink-700">On
          <select className={cn(FIELD, "mt-1")} value={form.day} onChange={(e) => set({ day: Number(e.target.value) })}>
            {form.frequency === "weekly"
              ? WEEKDAYS.map((d, i) => <option key={d} value={i}>{d}</option>)
              : Array.from({ length: 28 }, (_, i) => i + 1).map((d) => <option key={d} value={d}>Day {d}</option>)}
          </select>
        </label>
        <label className="text-xs text-ink-700">At (India time)
          <select className={cn(FIELD, "mt-1")} value={form.hour} onChange={(e) => set({ hour: Number(e.target.value) })}>
            {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{String(h).padStart(2, "0")}:00</option>)}
          </select>
        </label>
        <label className="text-xs text-ink-700">Covering
          <select className={cn(FIELD, "mt-1")} value={form.months} onChange={(e) => set({ months: Number(e.target.value) })}>
            {[1, 2, 3, 6, 12].map((m) => <option key={m} value={m}>{m === 1 ? "Last month" : `Last ${m} months`}</option>)}
          </select>
        </label>
        <label className="col-span-2 text-xs text-ink-700">As
          <select className={cn(FIELD, "mt-1")} value={form.format} onChange={(e) => set({ format: e.target.value as OutputFormat })}>
            <option value="xlsx">Excel</option><option value="pdf">PDF</option>
          </select>
        </label>
      </div>
      {blocked ? <p className="mt-2 text-xs text-ink-700">{blocked}</p> : null}
      {error ? <p className="mt-2 text-xs text-danger-700">{error}</p> : null}
      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm" variant="outline" disabled={busy || !!blocked} onClick={() => void act(() => builderApi.setSchedule(reportId, { ...form, enabled: true }))}>
          {busy ? <Loader2 size={13} className="animate-spin" /> : null} {current ? "Save schedule" : "Schedule it"}
        </Button>
        {current?.enabled ? <Button size="sm" variant="ghost" disabled={busy} onClick={() => void act(() => builderApi.setSchedule(reportId, { ...form, enabled: false }))}>Pause</Button> : null}
        {current ? <Button size="sm" variant="ghost" disabled={busy} onClick={() => void act(() => builderApi.removeSchedule(reportId))}>Remove</Button> : null}
      </div>
    </div>
  );
}
