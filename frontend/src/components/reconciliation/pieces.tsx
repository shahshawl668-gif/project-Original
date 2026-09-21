"use client";

import { AlertTriangle, CheckCircle2, ChevronRight, Info } from "lucide-react";
import { useState } from "react";

import { Card, CardContent } from "@/components/ui/card";
import { formatINR } from "@/lib/cost-analysis";
import {
  SEVERITY_LABEL,
  SEVERITY_TONE,
  type ExceptionCounts,
  type ReconException,
  type Severity,
} from "@/lib/reconciliation";
import { cn } from "@/lib/utils";

export function SeverityChip({ severity }: { severity: Severity }) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
        SEVERITY_TONE[severity],
      )}
    >
      {SEVERITY_LABEL[severity]}
    </span>
  );
}

/**
 * The verdict for one comparison.
 *
 * Three states, not two. "Reconciled" and "exceptions found" are the obvious
 * pair; the third — nothing was compared — is the one that matters, because a
 * month with no bank file would otherwise render as a page with no red on it.
 */
export function Verdict({
  state,
  title,
  detail,
}: {
  state: "clean" | "exceptions" | "not-compared";
  title: string;
  detail?: string | null;
}) {
  const look = {
    clean: {
      icon: CheckCircle2,
      wrap: "border-success-200/80 bg-success-50/60 dark:border-success-500/25 dark:bg-success-500/10",
      tint: "text-success-700 dark:text-success-300",
    },
    exceptions: {
      icon: AlertTriangle,
      wrap: "border-danger-200/80 bg-danger-50/60 dark:border-danger-500/25 dark:bg-danger-500/10",
      tint: "text-danger-700 dark:text-danger-300",
    },
    "not-compared": {
      icon: Info,
      wrap: "border-warning-200/80 bg-warning-50/60 dark:border-warning-500/30 dark:bg-warning-500/10",
      tint: "text-warning-800 dark:text-warning-200",
    },
  }[state];
  const Icon = look.icon;

  return (
    <div className={cn("flex items-start gap-3 rounded-xl border px-4 py-3", look.wrap)}>
      <Icon size={17} className={cn("mt-0.5 shrink-0", look.tint)} />
      <div className="space-y-0.5">
        <p className={cn("text-sm font-semibold", look.tint)}>{title}</p>
        {detail && <p className="text-xs text-ink-600 dark:text-ink-300">{detail}</p>}
      </div>
    </div>
  );
}

/** How many of each severity, so the shape of a month reads at a glance. */
export function SeverityCounts({ counts }: { counts: ExceptionCounts }) {
  const order: Severity[] = ["high", "medium", "low"];
  if (!counts.total) {
    return <span className="text-xs text-ink-500 dark:text-ink-400">No exceptions</span>;
  }
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {order.map((severity) =>
        counts.by_severity[severity] ? (
          <span
            key={severity}
            className={cn(
              "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold tabular-nums",
              SEVERITY_TONE[severity],
            )}
          >
            {counts.by_severity[severity]} {SEVERITY_LABEL[severity].toLowerCase()}
          </span>
        ) : null,
      )}
    </div>
  );
}

/**
 * Exceptions, grouped by what went wrong.
 *
 * Grouped rather than listed flat: two hundred amount mismatches are one
 * problem seen two hundred times, and a flat list buries the single
 * account-substitution line underneath them. Each group opens to the employees
 * and rupees behind it, because a total nobody can trace is not actionable.
 */
export function ExceptionList({ exceptions }: { exceptions: ReconException[] }) {
  const [open, setOpen] = useState<string | null>(null);

  if (!exceptions.length) {
    return (
      <p className="py-6 text-center text-sm text-ink-500 dark:text-ink-400">
        Nothing failed to reconcile.
      </p>
    );
  }

  const groups = new Map<string, ReconException[]>();
  for (const item of exceptions) {
    const list = groups.get(item.code) ?? [];
    list.push(item);
    groups.set(item.code, list);
  }

  return (
    <div className="space-y-2">
      {Array.from(groups.entries()).map(([code, items]) => {
        const first = items[0];
        const expanded = open === code;
        const total = items.reduce((sum, item) => sum + Math.abs(item.difference ?? 0), 0);
        return (
          <div
            key={code}
            className="overflow-hidden rounded-xl border border-ink-200/70 dark:border-ink-700/60"
          >
            <button
              type="button"
              onClick={() => setOpen(expanded ? null : code)}
              className="flex w-full items-start gap-3 px-4 py-3 text-left transition hover:bg-ink-50 dark:hover:bg-ink-800/40"
            >
              <ChevronRight
                size={15}
                className={cn(
                  "mt-1 shrink-0 text-ink-400 transition-transform",
                  expanded && "rotate-90",
                )}
              />
              <div className="min-w-0 flex-1 space-y-1">
                <div className="flex flex-wrap items-center gap-2">
                  <SeverityChip severity={first.severity} />
                  <span className="text-sm font-semibold text-ink-900 dark:text-white">
                    {first.label}
                  </span>
                  <span className="text-xs tabular-nums text-ink-500 dark:text-ink-400">
                    {items.length === 1 ? "1 case" : `${items.length} cases`}
                    {total > 0 && ` · ${formatINR(total)}`}
                  </span>
                </div>
                {first.meaning && (
                  <p className="text-xs text-ink-600 dark:text-ink-300">{first.meaning}</p>
                )}
              </div>
            </button>

            {expanded && (
              <div className="border-t border-ink-200/70 bg-ink-50/50 px-4 py-3 dark:border-ink-700/60 dark:bg-ink-900/30">
                {first.action && (
                  <p className="mb-3 text-xs font-medium text-ink-700 dark:text-ink-200">
                    What to do: <span className="font-normal">{first.action}</span>
                  </p>
                )}
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-left text-[10px] uppercase tracking-wide text-ink-400">
                        <th className="pb-1.5 pr-3 font-semibold">Detail</th>
                        <th className="pb-1.5 pr-3 text-right font-semibold">Expected</th>
                        <th className="pb-1.5 pr-3 text-right font-semibold">Actual</th>
                        <th className="pb-1.5 text-right font-semibold">Difference</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-ink-200/60 dark:divide-ink-700/50">
                      {items.slice(0, 50).map((item, index) => (
                        <tr key={`${item.employee_id ?? "x"}-${index}`}>
                          <td className="py-1.5 pr-3 text-ink-700 dark:text-ink-200">
                            {item.title}
                            {item.detail && (
                              <span className="block text-ink-500 dark:text-ink-400">
                                {item.detail}
                              </span>
                            )}
                          </td>
                          <td className="py-1.5 pr-3 text-right tabular-nums text-ink-600 dark:text-ink-300">
                            {item.expected === null ? "—" : formatINR(item.expected)}
                          </td>
                          <td className="py-1.5 pr-3 text-right tabular-nums text-ink-600 dark:text-ink-300">
                            {item.actual === null ? "—" : formatINR(item.actual)}
                          </td>
                          <td className="py-1.5 text-right font-semibold tabular-nums text-ink-900 dark:text-white">
                            {item.difference === null ? "—" : formatINR(item.difference)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {items.length > 50 && (
                  <p className="pt-2 text-[11px] text-ink-500 dark:text-ink-400">
                    Showing the first 50 of {items.length}. The full list is in the
                    reconciliation report.
                  </p>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

/** A labelled figure, for the three totals every comparison comes down to. */
export function Figure({
  label,
  value,
  hint,
  tone = "neutral",
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "neutral" | "danger" | "success";
}) {
  const tint = {
    neutral: "text-ink-900 dark:text-white",
    danger: "text-danger-600 dark:text-danger-400",
    success: "text-success-700 dark:text-success-400",
  }[tone];
  return (
    <Card>
      <CardContent className="space-y-1 py-4">
        <span className="block text-[10px] font-semibold uppercase tracking-wide text-ink-400">
          {label}
        </span>
        <p className={cn("font-display text-2xl font-semibold tabular-nums", tint)}>{value}</p>
        {hint && <p className="text-xs text-ink-500 dark:text-ink-400">{hint}</p>}
      </CardContent>
    </Card>
  );
}
