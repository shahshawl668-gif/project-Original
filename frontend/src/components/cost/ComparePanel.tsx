"use client";

import { ArrowRight, Users } from "lucide-react";

import { Panel } from "@/components/cost/pieces";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Skeleton } from "@/components/ui/skeleton";
import {
  formatDelta,
  formatINR,
  formatPct,
  type CostCompare,
  type DeltaRow,
} from "@/lib/cost-analysis";
import { cn } from "@/lib/utils";

/** Rising cost reads as bad news; falling cost as good. */
function toneFor(delta: number) {
  if (delta === 0) return "text-ink-500 dark:text-ink-400";
  return delta > 0
    ? "text-danger-600 dark:text-danger-400"
    : "text-success-700 dark:text-success-400";
}

function DeltaTable({
  rows,
  aLabel,
  bLabel,
  firstColumn,
  emphasise,
}: {
  rows: DeltaRow[];
  aLabel: string;
  bLabel: string;
  firstColumn: string;
  emphasise?: (row: DeltaRow) => boolean;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-ink-200 text-[10px] uppercase tracking-wide text-ink-400 dark:border-white/10">
            <th className="py-2 text-left font-semibold">{firstColumn}</th>
            <th className="py-2 text-right font-semibold">{aLabel}</th>
            <th className="py-2 text-right font-semibold">{bLabel}</th>
            <th className="py-2 text-right font-semibold">Change</th>
            <th className="py-2 text-right font-semibold">%</th>
          </tr>
        </thead>
        <tbody className="tabular-nums">
          {rows.map((row) => (
            <tr
              key={row.key}
              className={cn(
                "border-b border-ink-100 last:border-0 dark:border-white/5",
                emphasise?.(row) && "font-semibold",
              )}
            >
              <td className="py-2 pr-3 text-ink-800 dark:text-ink-100">{row.label}</td>
              <td className="py-2 text-right text-ink-600 dark:text-ink-300">
                {formatINR(row.a, true)}
              </td>
              <td className="py-2 text-right text-ink-900 dark:text-white">
                {formatINR(row.b, true)}
              </td>
              <td className={cn("py-2 text-right", toneFor(row.delta))}>
                {formatDelta(row.delta)}
              </td>
              <td className={cn("py-2 text-right", toneFor(row.delta))}>
                {/* "New" rather than a percentage: a group that did not exist
                    in the first period has not grown by an infinite amount. */}
                {row.delta_pct === null
                  ? row.b !== 0 && row.a === 0
                    ? "new"
                    : "—"
                  : formatPct(row.delta_pct)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ComparePanel({
  data,
  isLoading,
  error,
}: {
  data?: CostCompare;
  isLoading: boolean;
  error?: Error | null;
}) {
  if (error) {
    return (
      <AlertBanner variant="error" title="Could not compare those periods">
        {error.message}
      </AlertBanner>
    );
  }
  if (isLoading || !data) return <Skeleton className="h-64" />;

  const aLabel = data.a.label;
  const bLabel = data.b.label;
  const ctc = data.by_derived.find((r) => r.key === "ctc");
  const missing = [
    !data.a.present ? aLabel : null,
    !data.b.present ? bLabel : null,
  ].filter(Boolean) as string[];

  return (
    <div className="space-y-4">
      {missing.length > 0 && (
        <AlertBanner variant="warning" title="No register for every period selected">
          Nothing has been uploaded for {missing.join(" or ")}, so that side reads as
          zero rather than as a fall in cost.
        </AlertBanner>
      )}

      <Panel
        title={`${aLabel} compared with ${bLabel}`}
        description="Every line of the taxonomy, both periods, and what moved between them."
      >
        <div className="mb-5 grid gap-4 sm:grid-cols-3">
          <div className="rounded-xl border border-ink-200/70 p-3 dark:border-white/10">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-ink-400">{aLabel}</p>
            <p className="font-display text-xl font-semibold tabular-nums text-ink-900 dark:text-white">
              {formatINR(ctc?.a ?? 0, true)}
            </p>
            <p className="flex items-center gap-1 text-xs text-ink-500 dark:text-ink-400">
              <Users size={12} /> {data.headcount.a} employees
            </p>
          </div>
          <div className="flex flex-col items-center justify-center rounded-xl border border-ink-200/70 p-3 text-center dark:border-white/10">
            <ArrowRight size={16} className="mb-1 text-ink-400" />
            <p className={cn("font-display text-xl font-semibold tabular-nums", toneFor(ctc?.delta ?? 0))}>
              {formatDelta(ctc?.delta ?? 0)}
            </p>
            <p className="text-xs text-ink-500 dark:text-ink-400">
              {formatPct(ctc?.delta_pct ?? null)} in total CTC
            </p>
          </div>
          <div className="rounded-xl border border-ink-200/70 p-3 dark:border-white/10">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-ink-400">{bLabel}</p>
            <p className="font-display text-xl font-semibold tabular-nums text-ink-900 dark:text-white">
              {formatINR(ctc?.b ?? 0, true)}
            </p>
            <p className="flex items-center gap-1 text-xs text-ink-500 dark:text-ink-400">
              <Users size={12} /> {data.headcount.b} employees
              {data.headcount.delta !== 0 && (
                <span className={toneFor(data.headcount.delta)}>
                  ({data.headcount.delta > 0 ? "+" : "−"}
                  {Math.abs(data.headcount.delta)})
                </span>
              )}
            </p>
          </div>
        </div>

        <div className="grid gap-6 lg:grid-cols-2">
          <div className="space-y-2">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-ink-500 dark:text-ink-400">
              Roll-ups
            </h4>
            <DeltaTable
              rows={data.by_derived}
              aLabel={aLabel}
              bLabel={bLabel}
              firstColumn="Total"
              emphasise={(row) => row.key === "ctc"}
            />
            <h4 className="pt-3 text-xs font-semibold uppercase tracking-wide text-ink-500 dark:text-ink-400">
              By {data.group_by_label.toLowerCase()}, on {data.measure_label}
            </h4>
            <DeltaTable
              rows={data.by_group}
              aLabel={aLabel}
              bLabel={bLabel}
              firstColumn={data.group_by_label}
            />
          </div>

          <div className="space-y-2">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-ink-500 dark:text-ink-400">
              Line by line
            </h4>
            <DeltaTable
              rows={data.by_measure}
              aLabel={aLabel}
              bLabel={bLabel}
              firstColumn="Component"
            />
          </div>
        </div>
      </Panel>
    </div>
  );
}
