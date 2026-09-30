"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { ArrowUpRight, ArrowDownRight, ChevronRight, Minus } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export type StatTone = "neutral" | "brand" | "success" | "warning" | "danger";

const TONE_DOT: Record<StatTone, string> = {
  neutral: "bg-ink-300",
  brand: "bg-brand-500",
  success: "bg-success-500",
  warning: "bg-warning-500",
  danger: "bg-danger-500",
};

const TONE_VALUE: Record<StatTone, string> = {
  neutral: "text-ink-900",
  brand: "text-ink-900",
  success: "text-success-700",
  warning: "text-warning-800",
  danger: "text-danger-700",
};

type Trend = { value: string; direction: "up" | "down" | "flat"; label?: string; good?: "up" | "down" };

/**
 * One number, and what it is.
 *
 * `label` names the metric; `qualifier` names its basis (period, scope,
 * "actual" vs "annualised") so the figure is never read without its units.
 * `value` may be `null`, which renders as "Not available" — an absent figure
 * must not look like a zero. With `href`, the whole tile drills through.
 */
export function Stat({
  label,
  value,
  qualifier,
  hint,
  tone = "neutral",
  trend,
  icon: Icon,
  href,
  className,
  footer,
}: {
  label: string;
  value: ReactNode | null;
  qualifier?: ReactNode;
  hint?: ReactNode;
  tone?: StatTone;
  trend?: Trend;
  icon?: LucideIcon;
  href?: string;
  className?: string;
  footer?: ReactNode;
}) {
  const good = trend?.good ?? "up";
  const TrendIcon = trend?.direction === "up" ? ArrowUpRight : trend?.direction === "down" ? ArrowDownRight : Minus;
  const trendTone =
    !trend || trend.direction === "flat"
      ? "text-ink-500"
      : trend.direction === good
        ? "text-success-700"
        : "text-danger-700";
  const body = (
    <>
      <div className="flex items-center gap-1.5 text-xs font-medium text-ink-500">
        <span className={cn("h-1.5 w-1.5 flex-shrink-0 rounded-full", TONE_DOT[tone])} aria-hidden />
        {Icon ? <Icon size={13} className="text-ink-500" aria-hidden /> : null}
        <span className="truncate">{label}</span>
        {href ? <ChevronRight size={13} className="ml-auto flex-shrink-0 text-ink-300 transition-colors group-hover:text-ink-500" aria-hidden /> : null}
      </div>
      <div className="mt-1.5 flex items-baseline gap-2">
        {value === null || value === undefined ? (
          <span className="text-sm font-medium text-ink-500">Not available</span>
        ) : (
          <span className={cn("num text-[22px] font-semibold leading-none tracking-tight", TONE_VALUE[tone])}>
            {typeof value === "number" ? value.toLocaleString("en-IN") : value}
          </span>
        )}
        {trend ? (
          <span className={cn("inline-flex items-center gap-0.5 text-xs font-medium", trendTone)}>
            <TrendIcon size={12} aria-hidden />
            {trend.value}
            {trend.label ? <span className="font-normal text-ink-500">{trend.label}</span> : null}
          </span>
        ) : null}
      </div>
      {qualifier ? <p className="mt-1 text-[11.5px] text-ink-500">{qualifier}</p> : null}
      {hint ? <div className="mt-1.5 text-xs leading-relaxed text-ink-500">{hint}</div> : null}
      {footer ? <div className="mt-3 border-t border-ink-100 pt-2.5 text-xs">{footer}</div> : null}
    </>
  );
  const cls = cn("group block rounded-xl border border-ink-200 bg-white p-4 shadow-soft", href && "lift", className);
  return href ? (
    <Link href={href} className={cls}>
      {body}
    </Link>
  ) : (
    <div className={cls}>{body}</div>
  );
}

/** Kept for existing callers; maps the old tone names onto `Stat`. */
export function KpiCard({
  icon,
  label,
  value,
  hint,
  tone = "slate",
  trend,
  className,
  footer,
}: {
  icon?: LucideIcon;
  label: string;
  value: string | number;
  hint?: string;
  tone?: "indigo" | "violet" | "emerald" | "amber" | "rose" | "sky" | "slate";
  trend?: { value: string; direction: "up" | "down" | "flat"; label?: string };
  spark?: number[];
  className?: string;
  footer?: ReactNode;
}) {
  const map: Record<string, StatTone> = {
    indigo: "brand", violet: "brand", sky: "brand", emerald: "success", amber: "warning", rose: "danger", slate: "neutral",
  };
  return <Stat icon={icon} label={label} value={value} hint={hint} tone={map[tone]} trend={trend} className={className} footer={footer} />;
}
