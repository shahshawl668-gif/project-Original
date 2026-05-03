"use client";

import { cn } from "@/lib/utils";
import type { LucideIcon } from "lucide-react";
import { ArrowUpRight, ArrowDownRight, Minus } from "lucide-react";
import type { ReactNode } from "react";

type Tone = "indigo" | "violet" | "emerald" | "amber" | "rose" | "sky" | "slate";

const TONE: Record<
  Tone,
  { icon: string; ring: string; gradient: string; chip: string; chipText: string }
> = {
  indigo: {
    icon: "text-brand-600",
    ring: "ring-brand-100",
    gradient: "from-brand-500/15 via-brand-100/0 to-transparent",
    chip: "bg-brand-50",
    chipText: "text-brand-700",
  },
  violet: {
    icon: "text-accent-600",
    ring: "ring-accent-100",
    gradient: "from-accent-500/15 via-accent-100/0 to-transparent",
    chip: "bg-accent-50",
    chipText: "text-accent-700",
  },
  emerald: {
    icon: "text-success-600",
    ring: "ring-success-100",
    gradient: "from-success-500/15 via-success-100/0 to-transparent",
    chip: "bg-success-50",
    chipText: "text-success-700",
  },
  amber: {
    icon: "text-warning-600",
    ring: "ring-warning-100",
    gradient: "from-warning-500/15 via-warning-100/0 to-transparent",
    chip: "bg-warning-50",
    chipText: "text-warning-700",
  },
  rose: {
    icon: "text-danger-600",
    ring: "ring-danger-100",
    gradient: "from-danger-500/15 via-danger-100/0 to-transparent",
    chip: "bg-danger-50",
    chipText: "text-danger-700",
  },
  sky: {
    icon: "text-sky-600",
    ring: "ring-sky-100",
    gradient: "from-sky-500/15 via-sky-100/0 to-transparent",
    chip: "bg-sky-50",
    chipText: "text-sky-700",
  },
  slate: {
    icon: "text-ink-600",
    ring: "ring-ink-100",
    gradient: "from-ink-200/40 via-ink-100/0 to-transparent",
    chip: "bg-ink-100",
    chipText: "text-ink-700",
  },
};

type Trend = {
  value: string;
  direction: "up" | "down" | "flat";
  label?: string;
};

export function KpiCard({
  icon: Icon,
  label,
  value,
  hint,
  tone = "indigo",
  trend,
  spark,
  className,
  footer,
}: {
  icon: LucideIcon;
  label: string;
  value: string | number;
  hint?: string;
  tone?: Tone;
  trend?: Trend;
  spark?: number[]; // 0-100 normalised values
  className?: string;
  footer?: ReactNode;
}) {
  const t = TONE[tone];
  const TrendIcon =
    trend?.direction === "up" ? ArrowUpRight : trend?.direction === "down" ? ArrowDownRight : Minus;
  const trendColor =
    trend?.direction === "up"
      ? "text-success-600 bg-success-50 ring-success-100"
      : trend?.direction === "down"
        ? "text-danger-600 bg-danger-50 ring-danger-100"
        : "text-ink-500 bg-ink-100 ring-ink-200";

  return (
    <div
      className={cn(
        "lift group relative overflow-hidden rounded-2xl border border-ink-200/70 bg-white p-5 shadow-soft ring-1 ring-ink-900/[0.03]",
        className,
      )}
    >
      <div
        aria-hidden
        className={cn(
          "pointer-events-none absolute -right-12 -top-12 h-44 w-44 rounded-full bg-gradient-to-br opacity-80 blur-2xl transition-opacity group-hover:opacity-100",
          t.gradient,
        )}
      />
      <div className="relative flex items-start justify-between">
        <div
          className={cn(
            "flex h-10 w-10 items-center justify-center rounded-xl bg-white ring-1 shadow-sm",
            t.ring,
          )}
        >
          <Icon size={18} strokeWidth={2} className={t.icon} />
        </div>
        {trend && (
          <span
            className={cn(
              "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ring-1",
              trendColor,
            )}
          >
            <TrendIcon size={11} strokeWidth={2.5} />
            {trend.value}
          </span>
        )}
      </div>
      <p className="num relative mt-5 text-[2rem] font-bold leading-none tracking-tightest text-ink-900">
        {typeof value === "number" ? value.toLocaleString("en-IN") : value}
      </p>
      <div className="relative mt-2 flex items-center justify-between gap-3">
        <p className="text-[13px] font-medium text-ink-700">{label}</p>
        {trend?.label && (
          <span className="text-[10px] font-medium text-ink-400">{trend.label}</span>
        )}
      </div>
      {hint && <p className="relative mt-1.5 text-[11px] leading-relaxed text-ink-500">{hint}</p>}
      {spark && spark.length > 1 && (
        <Sparkline points={spark} tone={tone} className="relative mt-4 h-9 w-full" />
      )}
      {footer && <div className="relative mt-4 border-t border-ink-100 pt-3">{footer}</div>}
    </div>
  );
}

function Sparkline({ points, tone, className }: { points: number[]; tone: Tone; className?: string }) {
  const w = 100;
  const h = 28;
  const max = Math.max(...points, 1);
  const min = Math.min(...points, 0);
  const range = Math.max(max - min, 1);
  const step = w / Math.max(points.length - 1, 1);
  const path = points
    .map((p, i) => {
      const x = i * step;
      const y = h - ((p - min) / range) * h;
      return `${i === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");
  const color =
    tone === "indigo"
      ? "#6366f1"
      : tone === "violet"
        ? "#a855f7"
        : tone === "emerald"
          ? "#16a34a"
          : tone === "amber"
            ? "#d97706"
            : tone === "rose"
              ? "#dc2626"
              : tone === "sky"
                ? "#0284c7"
                : "#64748b";
  const id = `spark-grad-${tone}`;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className={className} aria-hidden>
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.35" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={`${path} L ${w} ${h} L 0 ${h} Z`} fill={`url(#${id})`} />
      <path d={path} fill="none" stroke={color} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
