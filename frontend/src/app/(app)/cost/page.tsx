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
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  CalendarRange,
  Coins,
  GitCompareArrows,
  IndianRupee,
  Landmark,
  Layers,
  LayoutGrid,
  Equal,
  Receipt,
  Scale,
  ShieldCheck,
  Target,
  Users,
  Wallet,
} from "lucide-react";

import { BudgetView } from "@/components/cost/BudgetView";
import { ComparePanel } from "@/components/cost/ComparePanel";
import { CompensationView } from "@/components/cost/CompensationView";
import { CompliancePanel } from "@/components/cost/CompliancePanel";
import { ActiveFilters, FilterMenu } from "@/components/cost/FilterMenu";
import { HeadcountMovement } from "@/components/cost/HeadcountMovement";
import { Menu, MenuItem } from "@/components/cost/Menu";
import { PayEquityView } from "@/components/cost/PayEquityView";
import { ClickHint, CostTooltip, MeasureTable, Panel, StatTile } from "@/components/cost/pieces";
import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Card, CardContent } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { useTheme } from "@/providers/ThemeProvider";
import {
  capSeries,
  chartTheme,
  fetchCostAnalysis,
  fetchCompensation,
  fetchCostCompare,
  fetchDimensions,
  fetchHeadcountMovement,
  fetchMeasures,
  fetchPeriods,
  fetchReadiness,
  formatINR,
  formatPct,
  OTHER_COLOR_DARK,
  OTHER_COLOR_LIGHT,
  OTHER_LABEL,
  SERIES_DARK,
  SERIES_LIGHT,
  type Granularity,
  type MeasureMeta,
} from "@/lib/cost-analysis";
import { cn } from "@/lib/utils";

/**
 * The sections of the dashboard.
 *
 * One at a time, chosen from a control, rather than all of them stacked down a
 * page nobody scrolls to the bottom of. An Indian payroll cost report has three
 * layers and four or five questions asked of it; showing every one at once
 * means none of them is answered clearly.
 */
type ViewKey =
  | "overview" | "earnings" | "employer" | "deduction"
  | "headcount" | "compensation" | "pay_equity" | "budget" | "compliance";

const VIEWS: { key: ViewKey; label: string; hint: string; icon: typeof LayoutGrid }[] = [
  { key: "overview", label: "Overview", hint: "CTC, where it goes, and by whom", icon: LayoutGrid },
  { key: "earnings", label: "Earnings", hint: "Basic & DA, HRA, allowances, variable pay", icon: Wallet },
  { key: "employer", label: "Employer contributions", hint: "EPF, ESI, gratuity, LWF", icon: Landmark },
  { key: "deduction", label: "Deductions & net", hint: "TDS, PT, employee EPF and ESI", icon: Receipt },
  { key: "headcount", label: "Headcount & variance", hint: "Joiners, exits, cost per head", icon: Users },
  { key: "compensation", label: "Compensation & benefits", hint: "Median, spread, fixed vs variable", icon: Scale },
  { key: "pay_equity", label: "Pay equity", hint: "Gender pay gap, unadjusted and like for like", icon: Equal },
  { key: "budget", label: "Budget & forecast", hint: "Actual against approved budget, scenarios", icon: Target },
  { key: "compliance", label: "Filing readiness", hint: "EPF ECR, ESIC, PT, Form 24Q", icon: ShieldCheck },
];

const GRANULARITIES: { value: Granularity; label: string }[] = [
  { value: "month", label: "By month" },
  { value: "quarter", label: "By quarter" },
  { value: "year", label: "By year" },
];

const LAYER_FOR_VIEW: Record<string, "earnings" | "employer" | "deduction"> = {
  earnings: "earnings",
  employer: "employer",
  deduction: "deduction",
};

const LAYER_TOTAL: Record<string, string> = {
  earnings: "gross",
  employer: "employer_cost",
  deduction: "deductions",
};

export default function CostAnalysisPage() {
  const { resolved } = useTheme();
  const isDark = resolved === "dark";
  const palette = isDark ? SERIES_DARK : SERIES_LIGHT;
  const otherColor = isDark ? OTHER_COLOR_DARK : OTHER_COLOR_LIGHT;

  const [view, setView] = useState<ViewKey>("overview");
  const [groupBy, setGroupBy] = useState("department");
  const [granularity, setGranularity] = useState<Granularity>("month");
  const [measure, setMeasure] = useState("ctc");
  const [filters, setFilters] = useState<Record<string, string[]>>({});
  const [comparing, setComparing] = useState(false);
  const [periodA, setPeriodA] = useState<string | null>(null);
  const [periodB, setPeriodB] = useState<string | null>(null);
  const [readinessPeriod, setReadinessPeriod] = useState<string | null>(null);

  const dims = useQuery({ queryKey: ["bi", "dimensions"], queryFn: fetchDimensions });
  const catalogue = useQuery({ queryKey: ["bi", "measures"], queryFn: fetchMeasures });
  const periods = useQuery({ queryKey: ["bi", "periods"], queryFn: fetchPeriods });

  // The layer view drives the measure, so the two controls cannot disagree
  // about what is on screen.
  const effectiveMeasure = LAYER_TOTAL[view] ?? measure;

  const analysis = useQuery({
    queryKey: ["bi", "cost", groupBy, granularity, effectiveMeasure, filters],
    queryFn: () => fetchCostAnalysis({ groupBy, granularity, measure: effectiveMeasure, filters }),
  });

  const compare = useQuery({
    queryKey: ["bi", "compare", periodA, periodB, groupBy, effectiveMeasure, filters],
    queryFn: () =>
      fetchCostCompare({
        periodA: periodA as string,
        periodB: periodB as string,
        groupBy,
        measure: effectiveMeasure,
        filters,
      }),
    enabled: comparing && Boolean(periodA && periodB),
  });

  const movement = useQuery({
    queryKey: ["bi", "movement", filters],
    queryFn: () => fetchHeadcountMovement({ filters }),
    enabled: view === "headcount",
  });

  const compensation = useQuery({
    queryKey: ["bi", "compensation", groupBy, filters],
    queryFn: () => fetchCompensation({ groupBy, filters }),
    enabled: view === "compensation",
  });

  const readiness = useQuery({
    queryKey: ["bi", "readiness", readinessPeriod],
    queryFn: () => fetchReadiness(readinessPeriod as string),
    enabled: view === "compliance" && Boolean(readinessPeriod),
  });

  // Default the comparison to the two most recent months, and readiness to the
  // latest — the pairs someone would have picked by hand anyway.
  const available = useMemo(() => periods.data?.periods ?? [], [periods.data]);
  useEffect(() => {
    if (!available.length) return;
    setPeriodB((current) => current ?? available[0].period);
    setPeriodA((current) => current ?? (available[1] ?? available[0]).period);
    setReadinessPeriod((current) => current ?? available[0].period);
  }, [available]);

  const measures = useMemo(() => catalogue.data?.measures ?? [], [catalogue.data]);
  const measureOptions: { key: string; label: string; hint?: string }[] = [
    { key: "ctc", label: "Total CTC", hint: "Gross plus employer contributions" },
    { key: "gross", label: "Gross pay", hint: "What the register paid" },
    { key: "employer_cost", label: "Employer contributions", hint: "EPF, ESI, gratuity, LWF" },
    { key: "deductions", label: "Employee deductions" },
    { key: "net", label: "Net pay" },
    ...measures.map((m) => ({ key: m.key, label: m.label, hint: m.hint })),
  ];

  const groups = useMemo(() => capSeries(analysis.data?.matrix ?? []), [analysis.data]);
  const colorFor = (group: string, index: number) =>
    group === OTHER_LABEL ? otherColor : palette[index % palette.length];

  const totals = analysis.data?.totals;
  const points = useMemo(() => analysis.data?.period_totals ?? [], [analysis.data]);
  const latest = points[points.length - 1];
  const previous = points[points.length - 2];
  const deltaOf = (key: string) =>
    latest && previous ? latest.measures[key] - previous.measures[key] : undefined;
  const deltaPctOf = (key: string) => {
    if (!latest || !previous || !previous.measures[key]) return null;
    return ((latest.measures[key] - previous.measures[key]) / previous.measures[key]) * 100;
  };

  /**
   * Clicking a mark filters on what it represents.
   *
   * The behaviour every reader of a BI tool expects, and the one thing that
   * turns a chart from a picture into a question you can ask. It goes through
   * the same filter state as the menu, so what a click did is visible as a chip
   * and undone the same way — a click that filtered invisibly would leave
   * someone staring at a total they cannot explain.
   */
  function filterFromChart(value: string | undefined, key: string = groupBy) {
    if (!value || value === OTHER_LABEL) return;
    toggleFilter(key, value);
  }

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

  // A selected group stays fully painted and the rest recede. Colour still
  // follows the entity — nothing is repainted, only dimmed — so a reader who
  // learned which hue is Engineering is not misled by a filter.
  const chrome = chartTheme(isDark);
  const selected = filters[groupBy] ?? [];
  const isFiltered = (group: string) => selected.length === 0 || selected.includes(group);
  const dimmed = (group: string) => (isFiltered(group) ? 1 : 0.28);

  const groupChartData = useMemo(() => {
    const periodList = analysis.data?.periods ?? [];
    return periodList.map((period) => {
      const point: Record<string, string | number> = { period: period.label };
      for (const g of groups) {
        point[g.group] = g.series.find((p) => p.period === period.key)?.value ?? 0;
      }
      return point;
    });
  }, [analysis.data, groups]);

  const layer = LAYER_FOR_VIEW[view];
  const layerMeasures: MeasureMeta[] = useMemo(
    () => (layer ? measures.filter((m) => m.layer === layer) : []),
    [layer, measures],
  );
  const layerChartData = useMemo(() => {
    if (!layerMeasures.length) return [];
    return points.map((point) => {
      const row: Record<string, string | number> = { period: point.label };
      for (const m of layerMeasures) row[m.label] = point.measures[m.key] ?? 0;
      return row;
    });
  }, [points, layerMeasures]);

  const currentView = VIEWS.find((v) => v.key === view) as (typeof VIEWS)[number];
  const hasData = Boolean(totals && (totals.ctc ?? 0) !== 0);

  // A control that cannot change what is on screen is not a disabled control,
  // it is one that should not be there. Filing readiness is entity-wide and by
  // wage month; the headcount view is a time series of the whole population.
  const shows = {
    groupBy: !["compliance", "headcount", "budget"].includes(view),
    period: !["compliance", "compensation", "pay_equity", "budget"].includes(view),
    measure: view === "overview",
    filters: view !== "compliance",
    compare: !["compliance", "compensation", "pay_equity", "budget", "headcount"].includes(view),
  };
  const controlCount = 1 + Number(shows.groupBy) + Number(shows.period)
    + Number(shows.measure) + Number(shows.filters);

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Business intelligence"
        title="Payroll cost analysis"
        description="Gross pay, the employer contributions on top of it, and what comes back out — by any reporting dimension, over months, quarters or years. Attribution uses the department, location and grade recorded when each register was stored, so a reorganisation today does not rewrite what last year cost."
      />

      {/* ── controls: everything behind a menu, nothing stacked on screen ── */}
      <Card>
        <CardContent className="space-y-3 py-4">
          <div
            className={cn(
              "grid gap-3 sm:grid-cols-2",
              controlCount >= 5 ? "lg:grid-cols-5" : controlCount === 4 ? "lg:grid-cols-4" : "lg:grid-cols-3",
            )}
          >
            <Menu
              label="View"
              icon={currentView.icon}
              summary={currentView.label}
              width="w-72"
            >
              {(close) =>
                VIEWS.map((option) => (
                  <MenuItem
                    key={option.key}
                    selected={option.key === view}
                    hint={option.hint}
                    onClick={() => {
                      setView(option.key);
                      close();
                    }}
                  >
                    {option.label}
                  </MenuItem>
                ))
              }
            </Menu>

            {shows.groupBy && (
            <Menu
              label="Break down by"
              icon={Layers}
              summary={
                dims.data?.dimensions.find((d) => d.key === groupBy)?.label ?? "Department"
              }
            >
              {(close) =>
                (dims.data?.dimensions ?? []).map((dimension) => (
                  <MenuItem
                    key={dimension.key}
                    selected={dimension.key === groupBy}
                    hint={`${dimension.values.length} value${dimension.values.length === 1 ? "" : "s"}`}
                    onClick={() => {
                      setGroupBy(dimension.key);
                      close();
                    }}
                  >
                    {dimension.label}
                  </MenuItem>
                ))
              }
            </Menu>
            )}

            {shows.period && (
            <Menu
              label="Period"
              icon={CalendarRange}
              summary={GRANULARITIES.find((g) => g.value === granularity)?.label ?? "By month"}
              width="w-48"
            >
              {(close) =>
                GRANULARITIES.map((option) => (
                  <MenuItem
                    key={option.value}
                    selected={option.value === granularity}
                    onClick={() => {
                      setGranularity(option.value);
                      close();
                    }}
                  >
                    {option.label}
                  </MenuItem>
                ))
              }
            </Menu>
            )}

            {shows.measure && (
            <Menu
              label="Measure"
              icon={Coins}
              summary={measureOptions.find((m) => m.key === measure)?.label ?? "Total CTC"}
              width="w-72"
            >
              {(close) =>
                measureOptions.map((option) => (
                  <MenuItem
                    key={option.key}
                    selected={option.key === measure}
                    hint={option.hint}
                    onClick={() => {
                      setMeasure(option.key);
                      close();
                    }}
                  >
                    {option.label}
                  </MenuItem>
                ))
              }
            </Menu>
            )}

            {shows.filters && (
              <FilterMenu
                dimensions={dims.data?.dimensions ?? []}
                filters={filters}
                onToggle={toggleFilter}
                onClear={() => setFilters({})}
              />
            )}
          </div>

          {shows.compare && (
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-ink-100 pt-3 dark:border-white/5">
            <ActiveFilters
              dimensions={dims.data?.dimensions ?? []}
              filters={filters}
              onToggle={toggleFilter}
              onClear={() => setFilters({})}
            />

            <div className="ml-auto flex items-end gap-2">
              <button
                type="button"
                onClick={() => setComparing((v) => !v)}
                aria-pressed={comparing}
                className={cn(
                  "inline-flex h-9 items-center gap-1.5 rounded-lg border px-3 text-sm font-medium transition-colors",
                  comparing
                    ? "border-brand-500 bg-brand-600 text-white"
                    : "border-ink-200 bg-white text-ink-700 hover:bg-ink-50 dark:border-white/10 dark:bg-white/[0.04] dark:text-ink-200 dark:hover:bg-white/[0.07]",
                )}
              >
                <GitCompareArrows size={14} />
                {comparing ? "Comparing" : "Compare periods"}
              </button>

              {comparing && (
                <>
                  <PeriodPicker
                    label="From"
                    value={periodA}
                    options={available}
                    onChange={setPeriodA}
                  />
                  <PeriodPicker
                    label="To"
                    value={periodB}
                    options={available}
                    onChange={setPeriodB}
                  />
                </>
              )}
            </div>
          </div>
          )}

          {shows.compare && comparing && available.length < 2 && (
            <p className="text-xs text-ink-500 dark:text-ink-400">
              Only one month has been uploaded, so there is nothing yet to compare it with.
            </p>
          )}
        </CardContent>
      </Card>

      {analysis.isError && (
        <AlertBanner variant="error" title="Could not load cost analysis">
          {(analysis.error as Error)?.message ?? "Unknown error"}
        </AlertBanner>
      )}

      {shows.compare && comparing && periodA && periodB && (
        <ComparePanel
          data={compare.data}
          isLoading={compare.isLoading}
          error={compare.error as Error | null}
        />
      )}

      {analysis.isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-24" />)}
        </div>
      ) : view === "pay_equity" ? (
        // Reachable before the first register: authorising the analysis is a
        // governance step someone sets up while configuring the workspace, not
        // something they should have to upload payroll to find.
        <PayEquityView
          groupBy={groupBy}
          filters={filters}
          palette={palette}
          isDark={isDark}
          onSelectGroup={(group) => filterFromChart(group)}
        />
      ) : !hasData ? (
        <EmptyState
          icon={Layers}
          title="No payroll cost to analyse yet"
          description="Upload and validate a salary register. Cost is attributed using the employee master, so upload that too for a breakdown by department, location and grade."
        />
      ) : view === "compliance" ? (
        <div className="space-y-4">
          <div className="flex justify-end">
            <div className="w-56">
              <PeriodPicker
                label="Wage month"
                value={readinessPeriod}
                options={available}
                onChange={setReadinessPeriod}
                full
              />
            </div>
          </div>
          <CompliancePanel
            data={readiness.data}
            isLoading={readiness.isLoading}
            error={readiness.error as Error | null}
          />
        </div>
      ) : view === "compensation" ? (
        <CompensationView
          data={compensation.data}
          isLoading={compensation.isLoading}
          error={compensation.error as Error | null}
          palette={palette}
          isDark={isDark}
          onSelectGroup={(group) => filterFromChart(group)}
        />
      ) : view === "budget" ? (
        <BudgetView filters={filters} palette={palette} isDark={isDark} />
      ) : (
        <>
          {/* ── the figures ───────────────────────────────────────── */}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatTile
              icon={IndianRupee}
              label="Total CTC"
              value={formatINR(totals?.ctc ?? 0, true)}
              tone="cost"
              delta={deltaOf("ctc")}
              deltaPct={deltaPctOf("ctc")}
              hint={previous ? `on ${previous.label}` : `${points.length} periods`}
            />
            <StatTile
              icon={Wallet}
              label="Gross pay"
              value={formatINR(totals?.gross ?? 0, true)}
              hint={`${(((totals?.gross ?? 0) / (totals?.ctc || 1)) * 100).toFixed(1)}% of CTC`}
            />
            <StatTile
              icon={Landmark}
              label="Employer contributions"
              value={formatINR(totals?.employer_cost ?? 0, true)}
              hint={`${(((totals?.employer_cost ?? 0) / (totals?.ctc || 1)) * 100).toFixed(1)}% on top of gross`}
            />
            <StatTile
              icon={Users}
              label="Cost per head"
              value={formatINR(totals?.cost_per_head ?? 0, true)}
              hint={`${totals?.headcount ?? 0} employees`}
            />
          </div>

          {view === "overview" && (
            <>
              <Panel
                title={`${analysis.data?.measure_label} over time by ${analysis.data?.group_by_label.toLowerCase()}`}
                description="Stacked to the total. Hover any period for the full breakdown."
              >
                <div className="h-[320px] w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={groupChartData} margin={{ top: 8, right: 16, left: 8, bottom: 0 }}>
                      <CartesianGrid stroke={gridColor} vertical={false} />
                      <XAxis dataKey="period" tick={axisTick} tickLine={false} axisLine={false} />
                      <YAxis
                        tick={axisTick} tickLine={false} axisLine={false} width={64}
                        tickFormatter={(v: number) => formatINR(v, true)}
                      />
                      <Tooltip content={<CostTooltip isDark={isDark} />} />
                      <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 12, paddingTop: 12 }} />
                      {groups.map((g, i) => (
                        <Area
                          key={g.group}
                          type="monotone"
                          dataKey={g.group}
                          stackId="cost"
                          // The band's own top line, which is what separates one
                          // fill from the next on a stacked area.
                          stroke={colorFor(g.group, i)}
                          strokeWidth={2}
                          fill={colorFor(g.group, i)}
                          fillOpacity={0.82}
                        />
                      ))}
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              </Panel>

              <div className="grid gap-4 lg:grid-cols-5">
                <Panel
                  className="self-start lg:col-span-3"
                  title={`Total by ${analysis.data?.group_by_label.toLowerCase()}`}
                  description={`Ranked on ${analysis.data?.measure_label} across the selected periods.`}
                >
                  <ClickHint>
                    Click a bar to filter everything on this page to that {analysis.data?.group_by_label.toLowerCase()}.
                  </ClickHint>
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
                        <Bar
                          dataKey="total"
                          radius={[0, 4, 4, 0]}
                          barSize={18}
                          cursor="pointer"
                          onClick={(entry: { name?: string }) => filterFromChart(entry?.name)}
                        >
                          {groups.map((g, i) => (
                            <Cell key={g.group} fill={colorFor(g.group, i)}
                                  opacity={isFiltered(g.group) ? 1 : dimmed(g.group)} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </Panel>

                <Panel
                  className="lg:col-span-2"
                  title="Where the money goes"
                  description="Earnings, what the employer pays on top, and what comes back out of gross."
                >
                  <CtcBreakdown totals={totals} measures={measures} />
                </Panel>
              </div>
            </>
          )}

          {layer && (
            <>
              <Panel
                title={`${currentView.label} over time`}
                description={
                  layer === "employer"
                    ? "Cost on top of gross. Gratuity is an accrual, not a payment — it is the liability this month added, and it is always computed because no register carries it."
                    : layer === "deduction"
                      ? "These come out of gross pay. They are never added to CTC: doing so would count the same money twice."
                      : "What the register paid, split the way an Indian pay structure is built."
                }
              >
                <div className="h-[320px] w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={layerChartData} margin={{ top: 8, right: 16, left: 8, bottom: 0 }}>
                      <CartesianGrid stroke={gridColor} vertical={false} />
                      <XAxis dataKey="period" tick={axisTick} tickLine={false} axisLine={false} />
                      <YAxis tick={axisTick} tickLine={false} axisLine={false} width={64}
                             tickFormatter={(v: number) => formatINR(v, true)} />
                      <Tooltip content={<CostTooltip isDark={isDark} />} />
                      <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 12, paddingTop: 12 }} />
                      {layerMeasures.map((m, i) => (
                        <Area
                          key={m.key}
                          type="monotone"
                          dataKey={m.label}
                          stackId="layer"
                          stroke={palette[i % palette.length]}
                          strokeWidth={2}
                          fill={palette[i % palette.length]}
                          fillOpacity={0.82}
                        />
                      ))}
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              </Panel>

              <div className="grid gap-4 lg:grid-cols-2">
                <Panel title={`${currentView.label} in full`} description="Across every period on screen.">
                  <MeasureTable
                    rows={layerMeasures.map((m) => ({
                      key: m.key,
                      label: m.label,
                      hint: m.hint,
                      amount: totals?.[m.key] ?? 0,
                    }))}
                    total={totals?.[LAYER_TOTAL[view]] ?? 0}
                    totalLabel={currentView.label}
                    shareOf={totals?.[LAYER_TOTAL[view]] ?? 0}
                  />
                  {layer !== "earnings" && analysis.data && (
                    <p className="mt-3 rounded-lg border border-ink-200/70 bg-ink-50 px-3 py-2 text-xs text-ink-600 dark:border-white/10 dark:bg-white/[0.03] dark:text-ink-400">
                      {formatINR(analysis.data.sources.reported, true)} of the statutory total is the
                      payroll system&rsquo;s own figure; {formatINR(analysis.data.sources.computed, true)}{" "}
                      was computed here. Where the two disagree, that disagreement is a validation
                      finding rather than a silent substitution.
                    </p>
                  )}
                </Panel>

                <Panel
                  title={`By ${analysis.data?.group_by_label.toLowerCase()}`}
                  description={`${currentView.label} across the selected periods.`}
                >
                  <ClickHint>
                    Click a bar to filter everything on this page to that {analysis.data?.group_by_label.toLowerCase()}.
                  </ClickHint>
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
                        <Bar
                          dataKey="total"
                          radius={[0, 4, 4, 0]}
                          barSize={18}
                          cursor="pointer"
                          onClick={(entry: { name?: string }) => filterFromChart(entry?.name)}
                        >
                          {groups.map((g, i) => (
                            <Cell key={g.group} fill={colorFor(g.group, i)}
                                  opacity={isFiltered(g.group) ? 1 : dimmed(g.group)} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </Panel>
              </div>
            </>
          )}

          {view === "headcount" && (
            <>
              <div className="grid gap-4 lg:grid-cols-2">
                {/* Two charts rather than two y-axes on one. Plotting people
                    against rupees on a shared plot invents a correlation out of
                    where the two scales happen to be pinned. */}
                <Panel
                  title="Headcount"
                  description="People on the register each period."
                >
                  <div className="h-[260px] w-full">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart
                        data={points.map((p) => ({ period: p.label, Headcount: p.headcount }))}
                        margin={{ top: 8, right: 16, left: 8, bottom: 0 }}
                      >
                        <CartesianGrid stroke={gridColor} vertical={false} />
                        <XAxis dataKey="period" tick={axisTick} tickLine={false} axisLine={false} />
                        <YAxis tick={axisTick} tickLine={false} axisLine={false} width={40}
                               allowDecimals={false} />
                        <Tooltip cursor={{ fill: chrome.cursor }}
                                 content={<CostTooltip isDark={isDark} single plain />} />
                        <Bar dataKey="Headcount" fill={palette[4]} radius={[4, 4, 0, 0]} barSize={26} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </Panel>

                <Panel
                  title="Cost per head"
                  description="Total CTC divided by average headcount. It moves when pay moves without the establishment changing — which is the movement worth explaining."
                >
                  <div className="h-[260px] w-full">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart
                        data={points.map((p) => ({
                          period: p.label,
                          "Cost per head": p.headcount ? p.measures.ctc / p.headcount : 0,
                        }))}
                        margin={{ top: 8, right: 16, left: 8, bottom: 0 }}
                      >
                        <CartesianGrid stroke={gridColor} vertical={false} />
                        <XAxis dataKey="period" tick={axisTick} tickLine={false} axisLine={false} />
                        <YAxis tick={axisTick} tickLine={false} axisLine={false} width={64}
                               tickFormatter={(v: number) => formatINR(v, true)} />
                        <Tooltip content={<CostTooltip isDark={isDark} single />} />
                        <Line type="monotone" dataKey="Cost per head" stroke={palette[2]}
                              strokeWidth={2.5} dot={{ r: 3 }} />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                </Panel>
              </div>

              <Panel
                title="Period on period"
                description="Each period against the one before it, so a rise in total cost can be told apart from a rise in what a person costs."
              >
                <VarianceTable points={points} />
              </Panel>

              {movement.isLoading ? (
                <Skeleton className="h-64" />
              ) : movement.data ? (
                <HeadcountMovement
                  points={movement.data.periods}
                  note={movement.data.denominator_note}
                  masked={movement.data.identity.masked}
                />
              ) : null}
            </>
          )}
        </>
      )}
    </div>
  );
}

function PeriodPicker({
  label,
  value,
  options,
  onChange,
  full,
}: {
  label: string;
  value: string | null;
  options: { period: string; label: string }[];
  onChange: (period: string) => void;
  full?: boolean;
}) {
  const current = options.find((o) => o.period === value);
  return (
    <div className={full ? "w-full" : "w-36"}>
      <Menu
        label={label}
        icon={CalendarRange}
        summary={current?.label ?? "—"}
        align="right"
        width="w-44"
      >
        {(close) =>
          options.length ? (
            options.map((option) => (
              <MenuItem
                key={option.period}
                selected={option.period === value}
                onClick={() => {
                  onChange(option.period);
                  close();
                }}
              >
                {option.label}
              </MenuItem>
            ))
          ) : (
            <p className="px-2.5 py-3 text-xs text-ink-500 dark:text-ink-400">
              No registers uploaded yet.
            </p>
          )
        }
      </Menu>
    </div>
  );
}

/** The CTC identity, stated as an addition so a reader can check it by eye. */
function CtcBreakdown({
  totals,
  measures,
}: {
  totals?: Record<string, number>;
  measures: MeasureMeta[];
}) {
  if (!totals) return null;
  const earnings = measures.filter((m) => m.layer === "earnings");
  const employer = measures.filter((m) => m.layer === "employer");

  return (
    <div className="space-y-4">
      <MeasureTable
        rows={earnings.map((m) => ({ key: m.key, label: m.label, amount: totals[m.key] ?? 0 }))}
        total={totals.gross ?? 0}
        totalLabel="Gross pay"
        shareOf={totals.ctc ?? 0}
      />
      <MeasureTable
        rows={employer.map((m) => ({ key: m.key, label: m.label, amount: totals[m.key] ?? 0 }))}
        total={totals.employer_cost ?? 0}
        totalLabel="Employer contributions"
        shareOf={totals.ctc ?? 0}
      />
      <div className="flex items-baseline justify-between rounded-xl border-2 border-brand-200 bg-brand-50 px-3 py-2.5 dark:border-brand-500/40 dark:bg-brand-500/10">
        <span className="text-sm font-semibold text-brand-900 dark:text-brand-100">Total CTC</span>
        <span className="font-display text-lg font-semibold tabular-nums text-brand-900 dark:text-brand-100">
          {formatINR(totals.ctc ?? 0, true)}
        </span>
      </div>
      <p className="text-xs text-ink-500 dark:text-ink-400">
        Deductions — {formatINR(totals.deductions ?? 0, true)}, leaving{" "}
        {formatINR(totals.net ?? 0, true)} net — come out of gross and are not added here.
        Counting them again is the commonest way a payroll cost report overstates itself.
      </p>
    </div>
  );
}

function VarianceTable({
  points,
}: {
  points: { period: string; label: string; headcount: number; measures: Record<string, number> }[];
}) {
  const rows = points.map((point, index) => {
    const prior = points[index - 1];
    const perHead = point.headcount ? point.measures.ctc / point.headcount : 0;
    const priorPerHead = prior && prior.headcount ? prior.measures.ctc / prior.headcount : 0;
    return {
      ...point,
      perHead,
      ctcDelta: prior ? point.measures.ctc - prior.measures.ctc : null,
      ctcPct: prior && prior.measures.ctc
        ? ((point.measures.ctc - prior.measures.ctc) / prior.measures.ctc) * 100
        : null,
      headDelta: prior ? point.headcount - prior.headcount : null,
      perHeadPct: priorPerHead ? ((perHead - priorPerHead) / priorPerHead) * 100 : null,
    };
  });

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-ink-200 text-[10px] uppercase tracking-wide text-ink-400 dark:border-white/10">
            <th className="py-2 text-left font-semibold">Period</th>
            <th className="py-2 text-right font-semibold">Headcount</th>
            <th className="py-2 text-right font-semibold">Change</th>
            <th className="py-2 text-right font-semibold">Total CTC</th>
            <th className="py-2 text-right font-semibold">Change</th>
            <th className="py-2 text-right font-semibold">Cost per head</th>
            <th className="py-2 text-right font-semibold">Change</th>
            <th className="py-2 text-right font-semibold">Arrears</th>
          </tr>
        </thead>
        <tbody className="tabular-nums">
          {rows.map((row) => (
            <tr key={row.period} className="border-b border-ink-100 last:border-0 dark:border-white/5">
              <td className="py-2 pr-3 text-ink-800 dark:text-ink-100">{row.label}</td>
              <td className="py-2 text-right text-ink-900 dark:text-white">{row.headcount}</td>
              <td className="py-2 text-right text-ink-500 dark:text-ink-400">
                {row.headDelta === null ? "—" : row.headDelta === 0 ? "0" : row.headDelta > 0 ? `+${row.headDelta}` : row.headDelta}
              </td>
              <td className="py-2 text-right text-ink-900 dark:text-white">
                {formatINR(row.measures.ctc, true)}
              </td>
              <td className={cn(
                "py-2 text-right",
                (row.ctcDelta ?? 0) > 0 ? "text-danger-600 dark:text-danger-400"
                  : (row.ctcDelta ?? 0) < 0 ? "text-success-700 dark:text-success-400"
                  : "text-ink-500 dark:text-ink-400",
              )}>
                {formatPct(row.ctcPct)}
              </td>
              <td className="py-2 text-right text-ink-900 dark:text-white">
                {formatINR(row.perHead, true)}
              </td>
              <td className={cn(
                "py-2 text-right",
                (row.perHeadPct ?? 0) > 0 ? "text-danger-600 dark:text-danger-400"
                  : (row.perHeadPct ?? 0) < 0 ? "text-success-700 dark:text-success-400"
                  : "text-ink-500 dark:text-ink-400",
              )}>
                {formatPct(row.perHeadPct)}
              </td>
              {/* Arrears alongside, because a month inflated by back-pay is not
                  a month whose run rate rose. */}
              <td className="py-2 text-right text-ink-500 dark:text-ink-400">
                {formatINR(row.measures.arrears, true)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
