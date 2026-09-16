"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { EyeOff, Scale, TrendingUp, Users } from "lucide-react";

import { Panel, StatTile } from "@/components/cost/pieces";
import { AlertBanner } from "@/components/ui/alert-banner";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { formatINR, type Compensation } from "@/lib/cost-analysis";

/**
 * How pay is distributed, for one month.
 *
 * The median leads, not the average: one large package moves an average and
 * nothing else does, which is why a C&B team does not reason with one. The
 * quartiles sit beside it because the spread is what a grade structure is
 * actually judged on.
 */
export function CompensationView({
  data,
  isLoading,
  error,
  palette,
  isDark,
}: {
  data?: Compensation;
  isLoading: boolean;
  error?: Error | null;
  palette: string[];
  isDark: boolean;
}) {
  if (error) {
    return (
      <AlertBanner variant="error" title="Could not load compensation analysis">
        {error.message}
      </AlertBanner>
    );
  }
  if (isLoading || !data) return <Skeleton className="h-64" />;
  if (!data.overall.count) {
    return (
      <EmptyState
        icon={Scale}
        title="No population to analyse"
        description="Upload a salary register. Compensation is read from the most recent month, so there needs to be at least one."
      />
    );
  }

  const axisTick = { fill: isDark ? "#7c8597" : "#5b6478", fontSize: 11 };
  const gridColor = isDark ? "rgba(255,255,255,0.07)" : "rgba(14,18,32,0.07)";
  const bands = data.distribution.map((b) => ({
    band: `${formatINR(b.from, true)}–${formatINR(b.to, true)}`,
    Employees: b.count,
  }));

  return (
    <div className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile icon={Scale} label="Median annual CTC"
          value={formatINR(data.overall.median, true)}
          hint={`${data.overall.count} employees · ${data.period_label}`} />
        <StatTile icon={TrendingUp} label="Mean annual CTC"
          value={formatINR(data.overall.mean, true)}
          hint={data.overall.mean > data.overall.median
            ? "Above the median — the top of the range is pulling it up"
            : "At or below the median"} />
        <StatTile icon={Users} label="Interquartile range"
          value={`${formatINR(data.overall.p25, true)} – ${formatINR(data.overall.p75, true)}`}
          hint="The middle half of the population" />
        <StatTile icon={Scale} label="Range ratio"
          value={data.overall.range_ratio ? `${data.overall.range_ratio.toFixed(1)}×` : "—"}
          hint={`${formatINR(data.overall.min, true)} to ${formatINR(data.overall.max, true)}`} />
      </div>

      {data.identity.masked && (
        <p className="flex items-center gap-2 rounded-lg border border-ink-200/70 bg-ink-50 px-3 py-2 text-xs text-ink-600 dark:border-white/10 dark:bg-white/[0.03] dark:text-ink-400">
          <EyeOff size={13} /> Identities are masked — {data.identity.reason}. The figures are
          unchanged; only who they belong to is withheld.
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-5">
        <Panel
          className="lg:col-span-3"
          title="Salary bands"
          description={`Equal-width bands across the observed range. ${data.basis}.`}
        >
          <div className="h-[300px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={bands} margin={{ top: 8, right: 12, left: 0, bottom: 44 }}>
                <CartesianGrid stroke={gridColor} vertical={false} />
                <XAxis dataKey="band" tick={axisTick} tickLine={false} axisLine={false}
                       angle={-30} textAnchor="end" interval={0} height={56} />
                <YAxis tick={axisTick} tickLine={false} axisLine={false} width={34}
                       allowDecimals={false} />
                <Tooltip
                  cursor={{ fill: isDark ? "rgba(255,255,255,0.04)" : "rgba(14,18,32,0.04)" }}
                  contentStyle={{
                    background: isDark ? "#151b2b" : "#ffffff",
                    border: `1px solid ${isDark ? "rgba(255,255,255,0.12)" : "#d6dae3"}`,
                    borderRadius: 8, fontSize: 12,
                    color: isDark ? "#eceef3" : "#1b2030",
                  }}
                />
                <Bar dataKey="Employees" radius={[4, 4, 0, 0]} fill={palette[0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Panel>

        <Panel
          className="lg:col-span-2"
          title="Fixed against variable"
          description="How much of the month's pay is guaranteed and how much is at risk."
        >
          <div className="space-y-3 pt-2">
            {[
              { label: "Fixed pay", value: data.mix.fixed, pct: data.mix.fixed_pct, color: palette[0] },
              { label: "Variable pay", value: data.mix.variable, pct: data.mix.variable_pct, color: palette[2] },
            ].map((row) => (
              <div key={row.label}>
                <div className="flex items-baseline justify-between pb-1 text-sm">
                  <span className="text-ink-700 dark:text-ink-200">{row.label}</span>
                  <span className="tabular-nums font-medium text-ink-900 dark:text-white">
                    {formatINR(row.value, true)}
                    <span className="ml-2 text-xs font-normal text-ink-500 dark:text-ink-400">
                      {row.pct.toFixed(1)}%
                    </span>
                  </span>
                </div>
                <div className="h-2.5 w-full overflow-hidden rounded-full bg-ink-100 dark:bg-white/[0.08]">
                  <div className="h-full rounded-full"
                       style={{ width: `${Math.min(100, row.pct)}%`, background: row.color }} />
                </div>
              </div>
            ))}
            {data.mix.variable === 0 && (
              <p className="pt-1 text-xs text-ink-500 dark:text-ink-400">
                No variable component is configured, so everything reads as fixed. Configure
                bonus or incentive components to split this.
              </p>
            )}
          </div>
        </Panel>
      </div>

      <Panel
        title={`By ${data.group_by_label.toLowerCase()}`}
        description="Ranked by median. The median and the quartiles, because an average on its own tells a C&B team very little."
      >
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-ink-200 text-[10px] uppercase tracking-wide text-ink-400 dark:border-white/10">
                <th className="py-2 text-left font-semibold">{data.group_by_label}</th>
                <th className="py-2 text-right font-semibold">Employees</th>
                <th className="py-2 text-right font-semibold">Median</th>
                <th className="py-2 text-right font-semibold">Mean</th>
                <th className="py-2 text-right font-semibold">P25</th>
                <th className="py-2 text-right font-semibold">P75</th>
                <th className="py-2 text-right font-semibold">Min</th>
                <th className="py-2 text-right font-semibold">Max</th>
                <th className="py-2 text-right font-semibold">Spread</th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {data.groups.map((group, index) => (
                <tr key={group.group} className="border-b border-ink-100 last:border-0 dark:border-white/5">
                  <td className="py-2 pr-3">
                    <span className="flex items-center gap-2">
                      <span aria-hidden className="h-2.5 w-2.5 flex-shrink-0 rounded-full"
                            style={{ background: palette[index % palette.length] }} />
                      <span className="text-ink-800 dark:text-ink-100">{group.group}</span>
                    </span>
                  </td>
                  <td className="py-2 text-right text-ink-500 dark:text-ink-400">{group.count}</td>
                  <td className="py-2 text-right font-medium text-ink-900 dark:text-white">
                    {formatINR(group.median, true)}
                  </td>
                  <td className="py-2 text-right text-ink-600 dark:text-ink-300">
                    {formatINR(group.mean, true)}
                  </td>
                  <td className="py-2 text-right text-ink-500 dark:text-ink-400">
                    {formatINR(group.p25, true)}
                  </td>
                  <td className="py-2 text-right text-ink-500 dark:text-ink-400">
                    {formatINR(group.p75, true)}
                  </td>
                  <td className="py-2 text-right text-ink-500 dark:text-ink-400">
                    {formatINR(group.min, true)}
                  </td>
                  <td className="py-2 text-right text-ink-500 dark:text-ink-400">
                    {formatINR(group.max, true)}
                  </td>
                  <td className="py-2 text-right text-ink-500 dark:text-ink-400">
                    {group.range_ratio ? `${group.range_ratio.toFixed(1)}×` : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel
        title="Highest cost employees"
        description={
          data.identity.masked
            ? "Identities masked. The top of the range, so an outlier can be seen without being named."
            : "The top of the range, annualised."
        }
      >
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-ink-200 text-[10px] uppercase tracking-wide text-ink-400 dark:border-white/10">
                <th className="py-2 text-left font-semibold">Employee</th>
                <th className="py-2 text-left font-semibold">Name</th>
                <th className="py-2 text-left font-semibold">{data.group_by_label}</th>
                <th className="py-2 text-right font-semibold">Annual CTC</th>
                <th className="py-2 text-right font-semibold">Fixed (month)</th>
                <th className="py-2 text-right font-semibold">Variable (month)</th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {data.employees.slice(0, 15).map((employee) => (
                <tr key={employee.employee_id}
                    className="border-b border-ink-100 last:border-0 dark:border-white/5">
                  <td className="py-2 pr-3 text-ink-800 dark:text-ink-100">{employee.employee_id}</td>
                  <td className="py-2 pr-3 text-ink-600 dark:text-ink-300">
                    {employee.employee_name ?? "—"}
                  </td>
                  <td className="py-2 pr-3 text-ink-600 dark:text-ink-300">{employee.group}</td>
                  <td className="py-2 text-right font-medium text-ink-900 dark:text-white">
                    {formatINR(employee.annual_ctc, true)}
                  </td>
                  <td className="py-2 text-right text-ink-500 dark:text-ink-400">
                    {formatINR(employee.fixed, true)}
                  </td>
                  <td className="py-2 text-right text-ink-500 dark:text-ink-400">
                    {formatINR(employee.variable, true)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {data.employees.length > 15 && (
          <p className="mt-2 text-xs text-ink-500 dark:text-ink-400">
            Showing 15 of {data.employees.length}. The employee-cost report has the full list.
          </p>
        )}
      </Panel>
    </div>
  );
}
