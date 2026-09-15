"use client";

import { AlertTriangle, CalendarClock, CheckCircle2, CircleDashed, Clock, FileWarning } from "lucide-react";

import { Panel } from "@/components/cost/pieces";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Skeleton } from "@/components/ui/skeleton";
import { formatINR, type Obligation, type Readiness } from "@/lib/cost-analysis";
import { cn } from "@/lib/utils";

/**
 * How each status reads.
 *
 * Note what is absent: there is no "filed". This product does not connect to
 * EPFO, ESIC, a state PT portal or TRACES, so it cannot know that a return was
 * submitted — and a tick claiming otherwise is exactly what would stop someone
 * checking. Everything here is about the deadline and about what would make a
 * filing wrong.
 */
const STATUS: Record<
  Obligation["status"],
  { label: string; icon: typeof CheckCircle2; className: string; dot: string }
> = {
  blocked: {
    label: "Blocked",
    icon: FileWarning,
    className: "border-danger-200 bg-danger-50 text-danger-800 dark:border-danger-500/30 dark:bg-danger-500/10 dark:text-danger-300",
    dot: "bg-danger-500",
  },
  overdue: {
    label: "Overdue",
    icon: AlertTriangle,
    className: "border-danger-200 bg-danger-50 text-danger-800 dark:border-danger-500/30 dark:bg-danger-500/10 dark:text-danger-300",
    dot: "bg-danger-500",
  },
  due_soon: {
    label: "Due soon",
    icon: Clock,
    className: "border-warning-200 bg-warning-50 text-warning-800 dark:border-warning-500/30 dark:bg-warning-500/10 dark:text-warning-300",
    dot: "bg-warning-500",
  },
  ready: {
    label: "Nothing blocking",
    icon: CheckCircle2,
    className: "border-success-200 bg-success-50 text-success-800 dark:border-success-500/30 dark:bg-success-500/10 dark:text-success-300",
    dot: "bg-success-500",
  },
  open: {
    label: "Open",
    icon: CircleDashed,
    className: "border-ink-200 bg-ink-50 text-ink-700 dark:border-white/10 dark:bg-white/[0.04] dark:text-ink-300",
    dot: "bg-ink-400",
  },
  no_register: {
    label: "No register",
    icon: CircleDashed,
    className: "border-ink-200 bg-ink-50 text-ink-600 dark:border-white/10 dark:bg-white/[0.04] dark:text-ink-400",
    dot: "bg-ink-300",
  },
};

function dueIn(days: number): string {
  if (days === 0) return "due today";
  if (days > 0) return `${days} day${days === 1 ? "" : "s"} left`;
  return `${Math.abs(days)} day${days === -1 ? "" : "s"} past`;
}

export function CompliancePanel({
  data,
  isLoading,
  error,
}: {
  data?: Readiness;
  isLoading: boolean;
  error?: Error | null;
}) {
  if (error) {
    return (
      <AlertBanner variant="error" title="Could not load filing readiness">
        {error.message}
      </AlertBanner>
    );
  }
  if (isLoading || !data) return <Skeleton className="h-64" />;

  return (
    <Panel
      title={`Filing readiness — ${data.period_label}`}
      description="Readiness, not confirmation. Every date is the statutory one for this wage month; every flag is something this product can see, which is a missing register, an unresolved shortfall or an unsigned period."
    >
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {data.obligations.map((obligation) => {
          const status = STATUS[obligation.status];
          const Icon = status.icon;
          return (
            <div
              key={obligation.key}
              className={cn("rounded-xl border p-3.5", status.className)}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold">{obligation.label}</p>
                  <p className="text-[11px] opacity-75">
                    {obligation.authority} · {obligation.cadence}
                  </p>
                </div>
                <span className="flex flex-shrink-0 items-center gap-1 rounded-full bg-white/70 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide dark:bg-black/25">
                  <Icon size={11} /> {status.label}
                </span>
              </div>

              <div className="mt-3 flex items-baseline gap-2">
                <CalendarClock size={13} className="opacity-70" />
                <span className="text-sm font-semibold tabular-nums">
                  {new Date(obligation.due_date).toLocaleDateString("en-IN", {
                    day: "numeric", month: "short", year: "numeric",
                  })}
                </span>
                <span className="text-[11px] opacity-75">{dueIn(obligation.days_left)}</span>
              </div>
              <p className="mt-1 text-[11px] opacity-75">{obligation.due_basis}</p>

              {obligation.open_findings > 0 && (
                <p className="mt-2 border-t border-current/15 pt-2 text-[11px] font-medium">
                  {obligation.open_findings} unresolved finding
                  {obligation.open_findings === 1 ? "" : "s"} under this head
                  {obligation.at_risk_amount > 0 && (
                    <> — {formatINR(obligation.at_risk_amount, true)} at stake</>
                  )}
                </p>
              )}
            </div>
          );
        })}
      </div>

      <p className="mt-4 rounded-lg border border-ink-200/70 bg-ink-50 px-3 py-2 text-xs text-ink-600 dark:border-white/10 dark:bg-white/[0.03] dark:text-ink-400">
        {data.disclaimer}
      </p>
    </Panel>
  );
}
