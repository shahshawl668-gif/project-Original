"use client";

import type { ComponentType } from "react";

import { Card, CardContent } from "@/components/ui/card";
import { formatDelta, formatINR, formatPct } from "@/lib/cost-analysis";
import { cn } from "@/lib/utils";

export function StatTile({
  icon: Icon,
  label,
  value,
  hint,
  delta,
  deltaPct,
  tone = "neutral",
}: {
  icon: ComponentType<{ size?: number | string; className?: string }>;
  label: string;
  value: string;
  hint?: string;
  delta?: number;
  deltaPct?: number | null;
  tone?: "neutral" | "cost" | "positive";
}) {
  // A rising cost is not good news, so the colour follows what the number means
  // for the reader rather than its arithmetic sign.
  const deltaTone =
    delta === undefined || delta === 0
      ? "text-ink-500 dark:text-ink-400"
      : (tone === "cost") === delta > 0
        ? "text-danger-600 dark:text-danger-400"
        : "text-success-700 dark:text-success-400";

  return (
    <Card>
      <CardContent className="space-y-1 py-4">
        <span className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-wide text-ink-400">
          <Icon size={13} /> {label}
        </span>
        <p className="font-display text-2xl font-semibold tabular-nums text-ink-900 dark:text-white">
          {value}
        </p>
        {delta !== undefined ? (
          <p className={cn("text-xs font-medium tabular-nums", deltaTone)}>
            {formatDelta(delta)}
            {deltaPct !== undefined && <span className="ml-1.5 opacity-80">{formatPct(deltaPct)}</span>}
            {hint && <span className="ml-1.5 font-normal text-ink-500 dark:text-ink-400">{hint}</span>}
          </p>
        ) : (
          hint && <p className="text-xs text-ink-500 dark:text-ink-400">{hint}</p>
        )}
      </CardContent>
    </Card>
  );
}

/** A section wrapper, so every panel on the page reads the same way. */
export function Panel({
  title,
  description,
  children,
  className,
  actions,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
  className?: string;
  actions?: React.ReactNode;
}) {
  return (
    <Card className={className}>
      <CardContent className="py-5">
        <div className="flex items-start justify-between gap-4 pb-3">
          <div className="space-y-1">
            <h3 className="text-base font-semibold text-ink-900 dark:text-white">{title}</h3>
            {description && (
              <p className="text-xs text-ink-500 dark:text-ink-400">{description}</p>
            )}
          </div>
          {actions}
        </div>
        {children}
      </CardContent>
    </Card>
  );
}

/**
 * One layer of the taxonomy as a table.
 *
 * Every layer is read the same way — line, amount, share of the layer — so the
 * three of them can be compared without re-learning a format each time.
 */
export function MeasureTable({
  rows,
  total,
  totalLabel,
  shareOf,
}: {
  rows: { key: string; label: string; hint?: string; amount: number }[];
  total: number;
  totalLabel: string;
  shareOf?: number;
}) {
  const denominator = shareOf ?? total;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-ink-200 text-[10px] uppercase tracking-wide text-ink-400 dark:border-white/10">
            <th className="py-2 text-left font-semibold">Component</th>
            <th className="py-2 text-right font-semibold">Amount</th>
            <th className="py-2 text-right font-semibold">Share</th>
          </tr>
        </thead>
        <tbody className="tabular-nums">
          {rows.map((row) => (
            <tr key={row.key} className="border-b border-ink-100 last:border-0 dark:border-white/5">
              <td className="py-2 pr-3">
                <span className="text-ink-800 dark:text-ink-100">{row.label}</span>
                {row.hint && (
                  <span className="block text-[11px] text-ink-500 dark:text-ink-400">{row.hint}</span>
                )}
              </td>
              <td className="py-2 text-right align-top text-ink-900 dark:text-white">
                {formatINR(row.amount, true)}
              </td>
              <td className="py-2 text-right align-top text-ink-500 dark:text-ink-400">
                {denominator ? `${((row.amount / denominator) * 100).toFixed(1)}%` : "—"}
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="border-t-2 border-ink-300 font-semibold dark:border-white/20">
            <td className="py-2 text-ink-900 dark:text-white">{totalLabel}</td>
            <td className="py-2 text-right tabular-nums text-ink-900 dark:text-white">
              {formatINR(total, true)}
            </td>
            <td className="py-2 text-right text-ink-500 dark:text-ink-400">
              {denominator ? `${((total / denominator) * 100).toFixed(1)}%` : "—"}
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

export function CostTooltip({
  active,
  payload,
  label,
  isDark,
  single,
  plain,
}: {
  active?: boolean;
  payload?: { name: string; value: number; color: string }[];
  label?: string;
  isDark: boolean;
  single?: boolean;
  /** The values are counts, not money — headcount does not wear a rupee sign. */
  plain?: boolean;
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
                    <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: p.color }} />
                    {p.name}
                  </span>
                </td>
                <td className="text-right font-medium">
                  {plain ? (p.value ?? 0).toLocaleString("en-IN") : formatINR(p.value ?? 0, true)}
                </td>
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

/**
 * A pay range as one mark: the middle half filled, the whole span whiskered,
 * the median ticked.
 *
 * This is the chart a compensation team actually reads. A bar of medians alone
 * hides the spread, which is the thing a grade structure is judged on — two
 * departments can share a median and have completely different bands.
 *
 * The bar itself spans P25 to P75, so its pixel width is a known number of
 * rupees; everything else is placed by scaling from that. The axis is linear,
 * so the arithmetic is exact rather than approximate.
 */
export function RangeBar(props: {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  fill?: string;
  payload?: { p25: number; p75: number; median: number; min: number; max: number };
  surface: string;
  ink: string;
}) {
  const { x = 0, y = 0, width = 0, height = 0, fill, payload, surface, ink } = props;
  if (!payload) return null;

  const span = payload.p75 - payload.p25;
  const mid = y + height / 2;
  const cap = Math.max(4, height * 0.38);

  // A group whose middle half is a single value — most often a group of one —
  // has no width to scale from. It gets a tick at its pay rather than a blank
  // row, because "one person, paid this" is an answer and an empty row is not.
  if (span <= 0 || width <= 0) {
    return (
      <g>
        <line x1={x} x2={x} y1={mid - cap} y2={mid + cap} stroke={fill} strokeWidth={3} />
      </g>
    );
  }

  const perRupee = width / span;
  const at = (value: number) => x + (value - payload.p25) * perRupee;
  const medianX = at(payload.median);

  return (
    <g>
      {/* Whiskers to the extremes, hairline so the filled range still leads. */}
      <line x1={at(payload.min)} x2={x} y1={mid} y2={mid} stroke={fill} strokeWidth={1.5} opacity={0.55} />
      <line x1={x + width} x2={at(payload.max)} y1={mid} y2={mid} stroke={fill} strokeWidth={1.5} opacity={0.55} />
      <line x1={at(payload.min)} x2={at(payload.min)} y1={mid - cap} y2={mid + cap}
            stroke={fill} strokeWidth={1.5} opacity={0.55} />
      <line x1={at(payload.max)} x2={at(payload.max)} y1={mid - cap} y2={mid + cap}
            stroke={fill} strokeWidth={1.5} opacity={0.55} />
      <rect x={x} y={y} width={width} height={height} rx={3} fill={fill} fillOpacity={0.85} />
      {/* The median, in surface colour so it reads as a division of the range
          rather than as another series. */}
      <line x1={medianX} x2={medianX} y1={y} y2={y + height} stroke={surface} strokeWidth={2.5} />
      <line x1={medianX} x2={medianX} y1={y} y2={y + height} stroke={ink} strokeWidth={1} opacity={0.5} />
    </g>
  );
}

/**
 * A bar that reads its sign: one hue each side of a zero line, neutral at rest.
 *
 * Used only where a number has a direction — a variance, a gap — never to tell
 * two categories apart.
 */
export function DivergingBar(props: {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  value?: number;
  palette: { negative: string; neutral: string; positive: string };
}) {
  const { x = 0, y = 0, width = 0, height = 0, value = 0, palette } = props;
  const fill = Math.abs(value) < 0.05 ? palette.neutral : value > 0 ? palette.positive : palette.negative;
  return <rect x={x} y={y} width={width} height={height} rx={3} fill={fill} fillOpacity={0.9} />;
}

/** A one-line hint that a chart responds to being clicked. */
export function ClickHint({ children }: { children: React.ReactNode }) {
  return (
    <p className="pb-2 text-[11px] text-ink-500 dark:text-ink-400">
      <span aria-hidden>↘ </span>{children}
    </p>
  );
}
