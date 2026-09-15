"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Building2, IndianRupee, Layers, TrendingUp, Users, X } from "lucide-react";

import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Card, CardContent } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { useTheme } from "@/providers/ThemeProvider";
import {
  capSeries,
  fetchCostAnalysis,
  fetchDimensions,
  formatINR,
  OTHER_COLOR_DARK,
  OTHER_COLOR_LIGHT,
  OTHER_LABEL,
  SERIES_DARK,
  SERIES_LIGHT,
  type Granularity,
} from "@/lib/cost-analysis";
import { cn } from "@/lib/utils";

const GRANULARITIES: { value: Granularity; label: string }[] = [
  { value: "month", label: "Month" },
  { value: "quarter", label: "Quarter" },
  { value: "year", label: "Year" },
];

export default function CostAnalysisPage() {
  const { resolved } = useTheme();
  const isDark = resolved === "dark";
  const palette = isDark ? SERIES_DARK : SERIES_LIGHT;
  const otherColor = isDark ? OTHER_COLOR_DARK : OTHER_COLOR_LIGHT;

  const [groupBy, setGroupBy] = useState("department");
  const [granularity, setGranularity] = useState<Granularity>("month");
  const [filters, setFilters] = useState<Record<string, string[]>>({});

  const dims = useQuery({ queryKey: ["bi", "dimensions"], queryFn: fetchDimensions });
  const analysis = useQuery({
    queryKey: ["bi", "cost", groupBy, granularity, filters],
    queryFn: () => fetchCostAnalysis({ groupBy, granularity, filters }),
  });

  // Group identity drives colour, so a filter that removes a series never
  // repaints the ones that remain.
  const groups = useMemo(() => capSeries(analysis.data?.matrix ?? []), [analysis.data]);
  const colorFor = (group: string, index: number) =>
    group === OTHER_LABEL ? otherColor : palette[index % palette.length];

  const chartData = useMemo(() => {
    const periods = analysis.data?.periods ?? [];
    return periods.map((period) => {
      const point: Record<string, string | number> = { period: period.label };
      for (const g of groups) {
        point[g.group] = g.series.find((p) => p.period === period.key)?.total ?? 0;
      }
      return point;
    });
  }, [analysis.data, groups]);

  const totals = analysis.data?.totals;
  const filterCount = Object.values(filters).reduce((n, v) => n + v.length, 0);

  function toggleFilter(key: string, value: string) {
    setFilters((current) => {
      const existing = current[key] ?? [];
      const next = existing.includes(value)
        ? existing.filter((v) => v !== value)
        : [...existing, value];
      const out = { ...current, [key]: next };
      if (!next.length) delete out[key];
      return out;
    });
  }

  const axisTick = { fill: isDark ? "#7c8597" : "#5b6478", fontSize: 11 };
  const gridColor = isDark ? "rgba(255,255,255,0.07)" : "rgba(14,18,32,0.07)";

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Business intelligence"
        title="Payroll cost analysis"
        description="What payroll costs, by any reporting dimension, over months, quarters or years. Attribution uses the department, location and grade recorded at the time each register was stored — a reorganisation today does not rewrite what last year cost."
      />

      {/* ── controls: one row above the charts ─────────────────────── */}
      <Card>
        <CardContent className="flex flex-col gap-4 py-4">
          <div className="flex flex-wrap items-end gap-4">
            <label className="flex flex-col gap-1.5">
              <span className="text-[10px] font-semibold uppercase tracking-wide text-ink-400">
                Break down by
              </span>
              <select
                id="cost-group-by"
                value={groupBy}
                onChange={(e) => setGroupBy(e.target.value)}
                className="h-9 rounded-lg border border-ink-200 bg-white px-3 text-sm font-medium text-ink-900 dark:border-white/10 dark:bg-white/[0.04] dark:text-ink-100"
              >
                {(dims.data?.dimensions ?? []).map((d) => (
                  <option key={d.key} value={d.key}>{d.label}</option>
                ))}
              </select>
            </label>

            <div className="flex flex-col gap-1.5">
              <span className="text-[10px] font-semibold uppercase tracking-wide text-ink-400">
                Period
              </span>
              <div className="flex overflow-hidden rounded-lg border border-ink-200 dark:border-white/10">
                {GRANULARITIES.map((g) => (
                  <button
                    key={g.value}
                    type="button"
                    onClick={() => setGranularity(g.value)}
                    className={cn(
                      "px-3 py-1.5 text-sm font-medium transition-colors",
                      granularity === g.value
                        ? "bg-brand-600 text-white"
                        : "bg-white text-ink-600 hover:bg-ink-50 dark:bg-white/[0.04] dark:text-ink-300 dark:hover:bg-white/[0.08]",
                    )}
                  >
                    {g.label}
                  </button>
                ))}
              </div>
            </div>

            {filterCount > 0 && (
              <button
                type="button"
                onClick={() => setFilters({})}
                className="ml-auto inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-ink-500 hover:bg-ink-100 dark:text-ink-300 dark:hover:bg-white/[0.06]"
              >
                <X size={13} /> Clear {filterCount} {filterCount === 1 ? "filter" : "filters"}
              </button>
            )}
          </div>

          {/* Dimension filters — multi-select, combining across dimensions. */}
          <div className="flex flex-wrap gap-x-5 gap-y-3 border-t border-ink-100 pt-3 dark:border-white/5">
            {(dims.data?.dimensions ?? [])
              .filter((d) => d.values.length > 1)
              .map((d) => (
                <div key={d.key} className="flex flex-wrap items-center gap-1.5">
                  <span className="text-[10px] font-semibold uppercase tracking-wide text-ink-400">
                    {d.label}
                  </span>
                  {d.values.slice(0, 8).map((value) => {
                    const on = (filters[d.key] ?? []).includes(value);
                    return (
                      <button
                        key={value}
                        type="button"
                        onClick={() => toggleFilter(d.key, value)}
                        aria-pressed={on}
                        className={cn(
                          "rounded-full border px-2.5 py-1 text-xs transition-colors",
                          on
                            ? "border-brand-500 bg-brand-50 font-medium text-brand-800 dark:border-brand-500/50 dark:bg-brand-500/15 dark:text-brand-200"
                            : "border-ink-200 text-ink-600 hover:bg-ink-50 dark:border-white/10 dark:text-ink-300 dark:hover:bg-white/[0.06]",
                        )}
                      >
                        {value}
                      </button>
                    );
                  })}
                </div>
              ))}
          </div>
        </CardContent>
      </Card>

      {analysis.isError && (
        <AlertBanner variant="error" title="Could not load cost analysis">
          {(analysis.error as Error)?.message ?? "Unknown error"}
        </AlertBanner>
      )}

      {analysis.isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-24" />)}
        </div>
      ) : !totals || totals.total === 0 ? (
        <EmptyState
          icon={Layers}
          title="No payroll cost to analyse yet"
          description="Upload and validate a salary register. Cost is attributed using the employee master, so upload that too for a breakdown by department, location and grade."
        />
      ) : (
        <>
          {/* ── the figures ───────────────────────────────────────── */}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatTile icon={IndianRupee} label="Total payroll cost"
              value={formatINR(totals.total, true)} hint={`${analysis.data?.periods.length ?? 0} periods`} />
            <StatTile icon={TrendingUp} label="Regular pay"
              value={formatINR(totals.regular, true)}
              hint={`${((totals.regular / totals.total) * 100).toFixed(1)}% of cost`} />
            <StatTile icon={Layers} label="Arrears & one-time"
              value={formatINR(totals.arrears, true)}
              hint="Excluded from the run rate" />
            <StatTile icon={Users} label="Cost per head"
              value={formatINR(totals.cost_per_head, true)}
              hint={`${totals.headcount} employees`} />
          </div>

          {/* ── cost over time, stacked by group ──────────────────── */}
          <Card>
            <CardContent className="space-y-1 py-5">
              <h3 className="text-base font-semibold text-ink-900 dark:text-white">
                Cost over time by {analysis.data?.group_by_label.toLowerCase()}
              </h3>
              <p className="pb-3 text-xs text-ink-500 dark:text-ink-400">
                Stacked to the total. Hover any period for the full breakdown.
              </p>
              <div className="h-[340px] w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={chartData} margin={{ top: 8, right: 16, left: 8, bottom: 0 }}>
                    <CartesianGrid stroke={gridColor} vertical={false} />
                    <XAxis dataKey="period" tick={axisTick} tickLine={false} axisLine={false} />
                    <YAxis
                      tick={axisTick} tickLine={false} axisLine={false} width={64}
                      tickFormatter={(v: number) => formatINR(v, true)}
                    />
                    <Tooltip content={<CostTooltip isDark={isDark} />} />
                    <Legend
                      iconType="circle" iconSize={8}
                      wrapperStyle={{ fontSize: 12, paddingTop: 12 }}
                    />
                    {groups.map((g, i) => (
                      <Area
                        key={g.group}
                        type="monotone"
                        dataKey={g.group}
                        stackId="cost"
                        stroke={colorFor(g.group, i)}
                        // A 2px surface gap between stacked fills, so adjacent
                        // bands stay separable for colour-vision deficiency.
                        strokeWidth={2}
                        fill={colorFor(g.group, i)}
                        fillOpacity={0.82}
                      />
                    ))}
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </CardContent>
          </Card>

          <div className="grid gap-4 lg:grid-cols-5">
            {/* ── ranked contribution ─────────────────────────────── */}
            <Card className="lg:col-span-3">
              <CardContent className="space-y-1 py-5">
                <h3 className="text-base font-semibold text-ink-900 dark:text-white">
                  Total by {analysis.data?.group_by_label.toLowerCase()}
                </h3>
                <p className="pb-3 text-xs text-ink-500 dark:text-ink-400">
                  Ranked by cost across the selected periods.
                </p>
                <div style={{ height: Math.max(220, groups.length * 42) }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart
                      data={groups.map((g) => ({ name: g.group, total: g.total }))}
                      layout="vertical"
                      margin={{ top: 4, right: 68, left: 8, bottom: 4 }}
                    >
                      <CartesianGrid stroke={gridColor} horizontal={false} />
                      <XAxis type="number" tick={axisTick} tickLine={false} axisLine={false}
                             tickFormatter={(v: number) => formatINR(v, true)} />
                      <YAxis type="category" dataKey="name" width={120}
                             tick={axisTick} tickLine={false} axisLine={false} />
                      <Tooltip
                        cursor={{ fill: isDark ? "rgba(255,255,255,0.04)" : "rgba(14,18,32,0.04)" }}
                        content={<CostTooltip isDark={isDark} single />}
                      />
                      <Bar dataKey="total" radius={[0, 4, 4, 0]} barSize={18}>
                        {groups.map((g, i) => (
                          <Cell key={g.group} fill={colorFor(g.group, i)} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </CardContent>
            </Card>

            {/* ── the table, so identity is never colour-alone ────── */}
            <Card className="lg:col-span-2">
              <CardContent className="py-5">
                <h3 className="pb-3 text-base font-semibold text-ink-900 dark:text-white">
                  Breakdown
                </h3>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-ink-200 text-[10px] uppercase tracking-wide text-ink-400 dark:border-white/10">
                        <th className="py-2 text-left font-semibold">{analysis.data?.group_by_label}</th>
                        <th className="py-2 text-right font-semibold">Cost</th>
                        <th className="py-2 text-right font-semibold">Share</th>
                      </tr>
                    </thead>
                    <tbody className="tabular-nums">
                      {groups.map((g, i) => (
                        <tr key={g.group} className="border-b border-ink-100 last:border-0 dark:border-white/5">
                          <td className="py-2">
                            <span className="flex items-center gap-2">
                              <span aria-hidden className="h-2.5 w-2.5 flex-shrink-0 rounded-full"
                                    style={{ background: colorFor(g.group, i) }} />
                              <span className="truncate text-ink-800 dark:text-ink-100">{g.group}</span>
                            </span>
                          </td>
                          <td className="py-2 text-right text-ink-900 dark:text-white">
                            {formatINR(g.total, true)}
                          </td>
                          <td className="py-2 text-right text-ink-500 dark:text-ink-400">
                            {g.share_pct.toFixed(1)}%
                          </td>
                        </tr>
                      ))}
                    </tbody>
                    <tfoot>
                      <tr className="border-t-2 border-ink-300 font-semibold dark:border-white/20">
                        <td className="py-2 text-ink-900 dark:text-white">Total</td>
                        <td className="py-2 text-right tabular-nums text-ink-900 dark:text-white">
                          {formatINR(totals.total, true)}
                        </td>
                        <td className="py-2 text-right text-ink-500 dark:text-ink-400">100%</td>
                      </tr>
                    </tfoot>
                  </table>
                </div>
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}

function StatTile({
  icon: Icon, label, value, hint,
}: {
  icon: typeof IndianRupee; label: string; value: string; hint: string;
}) {
  return (
    <Card>
      <CardContent className="space-y-1 py-4">
        <span className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-wide text-ink-400">
          <Icon size={13} /> {label}
        </span>
        <p className="font-display text-2xl font-semibold tabular-nums text-ink-900 dark:text-white">
          {value}
        </p>
        <p className="text-xs text-ink-500 dark:text-ink-400">{hint}</p>
      </CardContent>
    </Card>
  );
}

function CostTooltip({
  active, payload, label, isDark, single,
}: {
  active?: boolean;
  payload?: { name: string; value: number; color: string }[];
  label?: string;
  isDark: boolean;
  single?: boolean;
}) {
  if (!active || !payload?.length) return null;
  const total = payload.reduce((n, p) => n + (p.value ?? 0), 0);
  return (
    <div
      className="rounded-lg border px-3 py-2 text-xs shadow-lg"
      style={{
        background: isDark ? "#151b2b" : "#ffffff",
        borderColor: isDark ? "rgba(255,255,255,0.12)" : "#d6dae3",
        color: isDark ? "#eceef3" : "#1b2030",
      }}
    >
      {label && <p className="pb-1.5 font-semibold">{label}</p>}
      <table className="tabular-nums">
        <tbody>
          {payload
            .slice()
            .sort((a, b) => (b.value ?? 0) - (a.value ?? 0))
            .map((p) => (
              <tr key={p.name}>
                <td className="pr-3">
                  <span className="flex items-center gap-1.5">
                    <span aria-hidden className="h-2 w-2 rounded-full"
                          style={{ background: p.color }} />
                    {p.name}
                  </span>
                </td>
                <td className="text-right font-medium">{formatINR(p.value ?? 0, true)}</td>
              </tr>
            ))}
          {!single && payload.length > 1 && (
            <tr style={{ borderTop: `1px solid ${isDark ? "rgba(255,255,255,0.12)" : "#d6dae3"}` }}>
              <td className="pr-3 pt-1 font-semibold">Total</td>
              <td className="pt-1 text-right font-semibold">{formatINR(total, true)}</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
