"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { BadgeCheck, CheckCircle2, Download, FileWarning, Target, TrendingUp } from "lucide-react";

import { CostTooltip, Panel, StatTile } from "@/components/cost/pieces";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  approveBudget,
  fetchBudgetVariance,
  fetchBudgetVersions,
  fetchForecast,
  formatDelta,
  formatINR,
  formatPct,
  type ForecastInput,
} from "@/lib/cost-analysis";
import { apiAbsoluteUrl } from "@/lib/api";
import { cn } from "@/lib/utils";

/** Over budget reads as bad news; under budget as good. */
function toneFor(value: number | null) {
  if (value === null || value === 0) return "text-ink-500 dark:text-ink-400";
  return value > 0
    ? "text-danger-600 dark:text-danger-400"
    : "text-success-700 dark:text-success-400";
}

const MEASURE_LABELS: Record<string, string> = {
  ctc: "Total CTC",
  gross: "Gross pay",
  employer_cost: "Employer contributions",
};

const DEFAULT_SCENARIO: ForecastInput = {
  months: 6,
  incrementPct: 0,
  newHiresPerMonth: 0,
  exitsPerMonth: 0,
  bonusAmount: 0,
};

export function BudgetView({
  filters,
  palette,
  isDark,
}: {
  filters: Record<string, string[]>;
  palette: string[];
  isDark: boolean;
}) {
  const queryClient = useQueryClient();
  const [scenario, setScenario] = useState<ForecastInput>(DEFAULT_SCENARIO);

  const versions = useQuery({ queryKey: ["budget", "versions"], queryFn: fetchBudgetVersions });
  const variance = useQuery({
    queryKey: ["budget", "variance", filters],
    queryFn: () => fetchBudgetVariance({ filters }),
  });
  const forecast = useQuery({
    queryKey: ["budget", "forecast", scenario],
    queryFn: () => fetchForecast(scenario),
  });

  const approve = useMutation({
    mutationFn: approveBudget,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["budget"] });
    },
  });

  const axisTick = { fill: isDark ? "#7c8597" : "#5b6478", fontSize: 11 };
  const gridColor = isDark ? "rgba(255,255,255,0.07)" : "rgba(14,18,32,0.07)";

  const data = variance.data;
  const totals = data?.totals;

  const chartData = (data?.periods ?? []).map((p) => ({
    period: p.label,
    Actual: p.actual,
    Budget: p.budget ?? 0,
  }));

  const forecastData = [
    ...(forecast.data?.base
      ? [{
          period: forecast.data.base.label,
          Actual: forecast.data.base.actual,
          Forecast: forecast.data.base.actual,
        }]
      : []),
    ...(forecast.data?.forecast ?? []).map((row) => ({
      period: row.label,
      Forecast: row.forecast,
    })),
  ];

  return (
    <div className="space-y-5">
      {/* ── the approved budget ─────────────────────────────────────── */}
      {variance.isLoading ? (
        <Skeleton className="h-24" />
      ) : !data?.version ? (
        <AlertBanner variant="info" title="No approved budget yet">
          <p>
            {data?.note ??
              "Upload a budget and approve it. Until then there is nothing to compare actual cost against — and a draft is never used as the comparison."}
          </p>
          <p className="mt-2">
            <a
              href={apiAbsoluteUrl("/api/budget/template.csv")}
              className="inline-flex items-center gap-1.5 font-medium underline"
            >
              <Download size={13} /> Download the budget template
            </a>
          </p>
        </AlertBanner>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatTile icon={Target} label="Actual"
              value={formatINR(totals?.actual ?? 0, true)}
              hint={`on ${MEASURE_LABELS[data.measure ?? "ctc"] ?? data.measure}`} />
            <StatTile icon={BadgeCheck} label="Approved budget"
              value={totals?.budget !== null && totals?.budget !== undefined
                ? formatINR(totals.budget, true) : "—"}
              hint={data.version.name} />
            <StatTile icon={TrendingUp} label="Variance"
              value={totals?.variance !== null && totals?.variance !== undefined
                ? formatDelta(totals.variance) : "—"}
              tone="cost"
              hint={formatPct(totals?.variance_pct ?? null)} />
            <StatTile icon={CheckCircle2} label="Budget used"
              value={totals?.utilisation_pct !== null && totals?.utilisation_pct !== undefined
                ? `${totals.utilisation_pct.toFixed(1)}%` : "—"}
              hint="Actual as a share of budget" />
          </div>

          {(data.unbudgeted_periods.length > 0 || data.unspent_periods.length > 0) && (
            <AlertBanner variant="warning" title="The two sides do not cover the same months">
              {data.unbudgeted_periods.length > 0 && (
                <p>
                  No budget line for {data.unbudgeted_periods.join(", ")} — that cost is real
                  but unbudgeted, so it is shown with no comparison rather than as an overspend.
                </p>
              )}
              {data.unspent_periods.length > 0 && (
                <p>
                  Budgeted but no register yet for {data.unspent_periods.join(", ")} — unspent,
                  not saved.
                </p>
              )}
            </AlertBanner>
          )}

          <Panel
            title="Actual against budget"
            description={`Compared on ${MEASURE_LABELS[data.measure ?? "ctc"] ?? data.measure}, because that is the measure this budget was approved on.`}
          >
            <div className="h-[320px] w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData} margin={{ top: 8, right: 16, left: 8, bottom: 0 }}>
                  <CartesianGrid stroke={gridColor} vertical={false} />
                  <XAxis dataKey="period" tick={axisTick} tickLine={false} axisLine={false} />
                  <YAxis tick={axisTick} tickLine={false} axisLine={false} width={64}
                         tickFormatter={(v: number) => formatINR(v, true)} />
                  <Tooltip content={<CostTooltip isDark={isDark} single />} />
                  <Legend iconType="circle" iconSize={8}
                          wrapperStyle={{ fontSize: 12, paddingTop: 12 }} />
                  <Bar dataKey="Budget" fill={palette[4]} fillOpacity={0.45}
                       radius={[4, 4, 0, 0]} barSize={26} />
                  <Bar dataKey="Actual" fill={palette[0]} radius={[4, 4, 0, 0]} barSize={26} />
                </BarChart>
              </ResponsiveContainer>
            </div>

            <div className="mt-4 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-ink-200 text-[10px] uppercase tracking-wide text-ink-400 dark:border-white/10">
                    <th className="py-2 text-left font-semibold">Period</th>
                    <th className="py-2 text-right font-semibold">Actual</th>
                    <th className="py-2 text-right font-semibold">Budget</th>
                    <th className="py-2 text-right font-semibold">Variance</th>
                    <th className="py-2 text-right font-semibold">%</th>
                    <th className="py-2 text-right font-semibold">Used</th>
                  </tr>
                </thead>
                <tbody className="tabular-nums">
                  {data.periods.map((period) => (
                    <tr key={period.period}
                        className="border-b border-ink-100 last:border-0 dark:border-white/5">
                      <td className="py-2 pr-3 text-ink-800 dark:text-ink-100">
                        {period.label}
                        {!period.has_budget && (
                          <span className="ml-2 text-[10px] uppercase tracking-wide text-warning-700 dark:text-warning-400">
                            unbudgeted
                          </span>
                        )}
                        {!period.has_actual && (
                          <span className="ml-2 text-[10px] uppercase tracking-wide text-ink-400">
                            unspent
                          </span>
                        )}
                      </td>
                      <td className="py-2 text-right text-ink-900 dark:text-white">
                        {formatINR(period.actual, true)}
                      </td>
                      <td className="py-2 text-right text-ink-600 dark:text-ink-300">
                        {period.budget === null ? "—" : formatINR(period.budget, true)}
                      </td>
                      <td className={cn("py-2 text-right", toneFor(period.variance))}>
                        {period.variance === null ? "—" : formatDelta(period.variance)}
                      </td>
                      <td className={cn("py-2 text-right", toneFor(period.variance))}>
                        {formatPct(period.variance_pct)}
                      </td>
                      <td className="py-2 text-right text-ink-500 dark:text-ink-400">
                        {period.utilisation_pct === null
                          ? "—" : `${period.utilisation_pct.toFixed(0)}%`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>

          {data.scopes.length > 0 && (
            <Panel
              title="By budget scope"
              description="Ranked by how far each one is from its own number."
            >
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-ink-200 text-[10px] uppercase tracking-wide text-ink-400 dark:border-white/10">
                      <th className="py-2 text-left font-semibold">Scope</th>
                      <th className="py-2 text-right font-semibold">Actual</th>
                      <th className="py-2 text-right font-semibold">Budget</th>
                      <th className="py-2 text-right font-semibold">Variance</th>
                      <th className="py-2 text-right font-semibold">%</th>
                    </tr>
                  </thead>
                  <tbody className="tabular-nums">
                    {data.scopes.map((scope) => (
                      <tr key={scope.scope}
                          className="border-b border-ink-100 last:border-0 dark:border-white/5">
                        <td className="py-2 pr-3 text-ink-800 dark:text-ink-100">{scope.scope}</td>
                        <td className="py-2 text-right text-ink-900 dark:text-white">
                          {formatINR(scope.actual, true)}
                        </td>
                        <td className="py-2 text-right text-ink-600 dark:text-ink-300">
                          {scope.budget === null ? "—" : formatINR(scope.budget, true)}
                        </td>
                        <td className={cn("py-2 text-right", toneFor(scope.variance))}>
                          {scope.variance === null ? "—" : formatDelta(scope.variance)}
                        </td>
                        <td className={cn("py-2 text-right", toneFor(scope.variance))}>
                          {formatPct(scope.variance_pct)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>
          )}
        </>
      )}

      {/* ── forecast ────────────────────────────────────────────────── */}
      <Panel
        title="Forecast"
        description="Arithmetic on the assumptions below, projected from the last actual month. Not a result, and not an approved budget."
      >
        <div className="grid gap-3 pb-4 sm:grid-cols-2 lg:grid-cols-5">
          <ScenarioField label="Months ahead" value={scenario.months} min={1} max={24}
            onChange={(v) => setScenario((s) => ({ ...s, months: v }))} />
          <ScenarioField label="Increment %" value={scenario.incrementPct} min={0} max={100} step={0.5}
            onChange={(v) => setScenario((s) => ({ ...s, incrementPct: v }))} />
          <ScenarioField label="Hires / month" value={scenario.newHiresPerMonth} min={0} max={500}
            onChange={(v) => setScenario((s) => ({ ...s, newHiresPerMonth: v }))} />
          <ScenarioField label="Exits / month" value={scenario.exitsPerMonth} min={0} max={500}
            onChange={(v) => setScenario((s) => ({ ...s, exitsPerMonth: v }))} />
          <ScenarioField label="Bonus pool" value={scenario.bonusAmount} min={0} step={10000}
            onChange={(v) => setScenario((s) => ({ ...s, bonusAmount: v }))} />
        </div>

        {forecast.isLoading ? (
          <Skeleton className="h-64" />
        ) : !forecast.data?.forecast.length ? (
          <p className="text-sm text-ink-500 dark:text-ink-400">
            {forecast.data?.note ?? "Nothing to project from yet."}
          </p>
        ) : (
          <>
            <div className="h-[300px] w-full">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={forecastData} margin={{ top: 8, right: 16, left: 8, bottom: 0 }}>
                  <CartesianGrid stroke={gridColor} vertical={false} />
                  <XAxis dataKey="period" tick={axisTick} tickLine={false} axisLine={false} />
                  <YAxis tick={axisTick} tickLine={false} axisLine={false} width={64}
                         tickFormatter={(v: number) => formatINR(v, true)} />
                  <Tooltip content={<CostTooltip isDark={isDark} single />} />
                  <Legend iconType="circle" iconSize={8}
                          wrapperStyle={{ fontSize: 12, paddingTop: 12 }} />
                  <Line type="monotone" dataKey="Actual" stroke={palette[0]} strokeWidth={2.5}
                        dot={{ r: 3 }} connectNulls={false} />
                  {/* Dashed, because the eye should be able to tell a projection
                      from a measurement without reading the legend. */}
                  <Line type="monotone" dataKey="Forecast" stroke={palette[2]} strokeWidth={2.5}
                        strokeDasharray="6 4" dot={{ r: 3 }} connectNulls />
                </LineChart>
              </ResponsiveContainer>
            </div>

            <div className="mt-4 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-ink-200 text-[10px] uppercase tracking-wide text-ink-400 dark:border-white/10">
                    <th className="py-2 text-left font-semibold">Period</th>
                    <th className="py-2 text-right font-semibold">Forecast</th>
                    <th className="py-2 text-right font-semibold">Run rate</th>
                    <th className="py-2 text-right font-semibold">Increment</th>
                    <th className="py-2 text-right font-semibold">Joiners</th>
                    <th className="py-2 text-right font-semibold">Exits</th>
                    <th className="py-2 text-right font-semibold">Bonus</th>
                    <th className="py-2 text-right font-semibold">Headcount</th>
                  </tr>
                </thead>
                <tbody className="tabular-nums">
                  {forecast.data.forecast.map((row) => (
                    <tr key={row.period}
                        className="border-b border-ink-100 last:border-0 dark:border-white/5">
                      <td className="py-2 pr-3 text-ink-800 dark:text-ink-100">{row.label}</td>
                      <td className="py-2 text-right font-medium text-ink-900 dark:text-white">
                        {formatINR(row.forecast, true)}
                      </td>
                      <td className="py-2 text-right text-ink-500 dark:text-ink-400">
                        {formatINR(row.components.run_rate, true)}
                      </td>
                      <td className="py-2 text-right text-ink-500 dark:text-ink-400">
                        {row.components.increment ? formatINR(row.components.increment, true) : "—"}
                      </td>
                      <td className="py-2 text-right text-ink-500 dark:text-ink-400">
                        {row.components.joiners ? formatINR(row.components.joiners, true) : "—"}
                      </td>
                      <td className="py-2 text-right text-ink-500 dark:text-ink-400">
                        {row.components.exits ? formatINR(row.components.exits, true) : "—"}
                      </td>
                      <td className="py-2 text-right text-ink-500 dark:text-ink-400">
                        {row.components.bonus ? formatINR(row.components.bonus, true) : "—"}
                      </td>
                      <td className="py-2 text-right text-ink-500 dark:text-ink-400">
                        {row.headcount}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <p className="mt-3 rounded-lg border border-warning-200 bg-warning-50 px-3 py-2 text-xs text-warning-800 dark:border-warning-500/30 dark:bg-warning-500/10 dark:text-warning-300">
              {forecast.data.disclaimer} Base: {forecast.data.base?.note}
            </p>
          </>
        )}
      </Panel>

      {/* ── versions ────────────────────────────────────────────────── */}
      <Panel
        title="Budget versions"
        description="A budget is versioned rather than overwritten, so the variance reported at the time stays reconstructable."
        actions={
          <a
            href={apiAbsoluteUrl("/api/budget/template.csv")}
            className="inline-flex items-center gap-1.5 rounded-lg border border-ink-200 px-2.5 py-1.5 text-xs font-medium text-ink-600 hover:bg-ink-50 dark:border-white/10 dark:text-ink-300 dark:hover:bg-white/[0.06]"
          >
            <Download size={13} /> Template
          </a>
        }
      >
        {versions.isLoading ? (
          <Skeleton className="h-24" />
        ) : !versions.data?.versions.length ? (
          <p className="flex items-center gap-2 text-sm text-ink-500 dark:text-ink-400">
            <FileWarning size={15} /> No budget uploaded yet. Download the template, fill it in,
            and upload it from Data uploads.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-ink-200 text-[10px] uppercase tracking-wide text-ink-400 dark:border-white/10">
                  <th className="py-2 text-left font-semibold">Name</th>
                  <th className="py-2 text-left font-semibold">Level</th>
                  <th className="py-2 text-left font-semibold">Measure</th>
                  <th className="py-2 text-right font-semibold">Lines</th>
                  <th className="py-2 text-left font-semibold">State</th>
                  <th className="py-2 text-left font-semibold">Approved by</th>
                  <th className="py-2 text-right font-semibold"></th>
                </tr>
              </thead>
              <tbody>
                {versions.data.versions.map((version) => (
                  <tr key={version.id}
                      className="border-b border-ink-100 last:border-0 dark:border-white/5">
                    <td className="py-2 pr-3 text-ink-800 dark:text-ink-100">{version.name}</td>
                    <td className="py-2 pr-3 text-ink-600 dark:text-ink-300">{version.scope_label}</td>
                    <td className="py-2 pr-3 text-ink-600 dark:text-ink-300">{version.measure}</td>
                    <td className="py-2 text-right tabular-nums text-ink-600 dark:text-ink-300">
                      {version.line_count}
                    </td>
                    <td className="py-2 pr-3">
                      {version.is_current ? (
                        <Badge variant="success">Current</Badge>
                      ) : version.state === "approved" ? (
                        <Badge variant="secondary">Superseded</Badge>
                      ) : (
                        <Badge variant="outline">Draft</Badge>
                      )}
                    </td>
                    <td className="py-2 pr-3 text-xs text-ink-500 dark:text-ink-400">
                      {version.approved_by ?? "—"}
                    </td>
                    <td className="py-2 text-right">
                      {version.state === "draft" && (
                        <button
                          type="button"
                          onClick={() => approve.mutate(version.id)}
                          disabled={approve.isPending}
                          className="rounded-lg border border-brand-200 bg-brand-50 px-2.5 py-1 text-xs font-medium text-brand-800 hover:border-brand-400 disabled:opacity-60 dark:border-brand-500/40 dark:bg-brand-500/15 dark:text-brand-100"
                        >
                          Approve
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {approve.isError && (
              <p className="mt-2 text-xs text-danger-600 dark:text-danger-400">
                {(approve.error as Error).message}
              </p>
            )}
          </div>
        )}
      </Panel>
    </div>
  );
}

function ScenarioField({
  label, value, onChange, min, max, step,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
}) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-[10px] font-semibold uppercase tracking-wide text-ink-400">
        {label}
      </span>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        step={step ?? 1}
        onChange={(e) => onChange(Number(e.target.value) || 0)}
        className="h-9 rounded-lg border border-ink-200 bg-white px-3 text-sm tabular-nums text-ink-900 focus:outline-none focus:ring-2 focus:ring-brand-500 dark:border-white/10 dark:bg-white/[0.04] dark:text-white"
      />
    </label>
  );
}
