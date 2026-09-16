"use client";

import { AlertTriangle } from "lucide-react";

import { Panel } from "@/components/cost/pieces";
import { formatINR, type MovementPoint } from "@/lib/cost-analysis";
import { cn } from "@/lib/utils";

function signed(value: number | null): string {
  if (value === null) return "—";
  if (value === 0) return "0";
  return value > 0 ? `+${value}` : String(value);
}

/**
 * Opening, joiners, exits, closing.
 *
 * A payroll that rose 6% because twelve people joined is a different
 * conversation from one that rose 6% because everyone got an increment. This
 * table is what separates them.
 */
export function HeadcountMovement({
  points,
  note,
  masked,
}: {
  points: MovementPoint[];
  note: string;
  masked: boolean;
}) {
  const disagreements = points.filter((p) => p.opening !== null && !p.master_agrees);

  return (
    <Panel
      title="Movement"
      description="Measured by presence on the register — someone paid this month who was not paid last month is a joiner. That is a verified statement; a joining date on a master that has not been re-uploaded is an assertion."
    >
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-ink-200 text-[10px] uppercase tracking-wide text-ink-400 dark:border-white/10">
              <th className="py-2 text-left font-semibold">Period</th>
              <th className="py-2 text-right font-semibold">Opening</th>
              <th className="py-2 text-right font-semibold">Joiners</th>
              <th className="py-2 text-right font-semibold">Exits</th>
              <th className="py-2 text-right font-semibold">Closing</th>
              <th className="py-2 text-right font-semibold">Net</th>
              <th className="py-2 text-right font-semibold">Avg headcount</th>
              <th className="py-2 text-right font-semibold">Cost / head</th>
              <th className="py-2 text-right font-semibold">Master</th>
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {points.map((point) => (
              <tr key={point.period} className="border-b border-ink-100 last:border-0 dark:border-white/5">
                <td className="py-2 pr-3 text-ink-800 dark:text-ink-100">{point.label}</td>
                <td className="py-2 text-right text-ink-500 dark:text-ink-400">
                  {point.opening ?? "—"}
                </td>
                <td className={cn("py-2 text-right",
                  point.joiners ? "font-medium text-success-700 dark:text-success-400" : "text-ink-400")}>
                  {point.joiners || "—"}
                </td>
                <td className={cn("py-2 text-right",
                  point.exits ? "font-medium text-danger-600 dark:text-danger-400" : "text-ink-400")}>
                  {point.exits || "—"}
                </td>
                <td className="py-2 text-right font-medium text-ink-900 dark:text-white">
                  {point.closing}
                </td>
                <td className="py-2 text-right text-ink-500 dark:text-ink-400">
                  {signed(point.net_change)}
                </td>
                <td className="py-2 text-right text-ink-500 dark:text-ink-400">
                  {point.average_headcount}
                </td>
                <td className="py-2 text-right text-ink-900 dark:text-white">
                  {formatINR(point.cost_per_head_average, true)}
                </td>
                <td className="py-2 text-right">
                  {point.opening === null ? (
                    <span className="text-ink-400">—</span>
                  ) : point.master_agrees ? (
                    <span className="text-success-700 dark:text-success-400">agrees</span>
                  ) : (
                    <span
                      className="text-warning-700 dark:text-warning-400"
                      title={`Master says ${point.master_says.joiners} joiners, ${point.master_says.exits} exits`}
                    >
                      {point.master_says.joiners}/{point.master_says.exits}
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mt-3 text-xs text-ink-500 dark:text-ink-400">{note}</p>

      {disagreements.length > 0 && (
        <p className="mt-2 flex items-start gap-2 rounded-lg border border-warning-200 bg-warning-50 px-3 py-2 text-xs text-warning-800 dark:border-warning-500/30 dark:bg-warning-500/10 dark:text-warning-300">
          <AlertTriangle size={14} className="mt-px flex-shrink-0" />
          <span>
            In {disagreements.length} month{disagreements.length === 1 ? "" : "s"} the employee
            master&rsquo;s joining and exit dates do not match what the registers show. The
            register is used, because the money moved; the master column shows its
            joiners/exits so the gap is visible rather than resolved silently.
          </span>
        </p>
      )}

      {points.some((p) => p.joiner_ids.length || p.exit_ids.length) && (
        <details className="mt-3 text-xs">
          <summary className="cursor-pointer font-medium text-ink-600 dark:text-ink-300">
            Who moved{masked ? " (identities masked for your role)" : ""}
          </summary>
          <div className="mt-2 space-y-2">
            {points
              .filter((p) => p.joiner_ids.length || p.exit_ids.length)
              .map((point) => (
                <div key={point.period} className="rounded-lg border border-ink-200/70 p-2.5 dark:border-white/10">
                  <p className="font-medium text-ink-800 dark:text-ink-100">{point.label}</p>
                  {point.joiner_ids.length > 0 && (
                    <p className="text-success-700 dark:text-success-400">
                      Joined: {point.joiner_ids.join(", ")}
                    </p>
                  )}
                  {point.exit_ids.length > 0 && (
                    <p className="text-danger-600 dark:text-danger-400">
                      Left: {point.exit_ids.join(", ")}
                    </p>
                  )}
                </div>
              ))}
          </div>
        </details>
      )}
    </Panel>
  );
}
