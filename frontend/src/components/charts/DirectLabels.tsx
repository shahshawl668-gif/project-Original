"use client";

import { usePlotArea, useXAxisScale, useYAxisScale } from "recharts";

import { CHART } from "@/lib/chart-colors";

/**
 * Series names written beside the chart, level with where each series ends.
 *
 * With two to four series a legend alone makes the reader match colours back
 * and forth; a name at the end of each line reads at a glance, and does not
 * lean on colour at all. Past four the labels crowd, so the legend carries
 * them alone (and it stays present either way).
 *
 * Place it inside the chart, after the series, and give the chart a right
 * margin of about `DIRECT_LABEL_MARGIN`. Text wears the text colour; a short
 * rule in the series colour ties it to its line.
 */
export const DIRECT_LABEL_MARGIN = 112;
const GAP = 14;

export type LabelledSeries = { key: string; label: string; color: string };

export function DirectLabels({
  data,
  series,
  xKey,
  stacked = false,
}: {
  data: Record<string, unknown>[];
  series: LabelledSeries[];
  xKey: string;
  stacked?: boolean;
}) {
  const x = useXAxisScale();
  const y = useYAxisScale();
  const area = usePlotArea();
  if (!x || !y || !area || series.length < 2 || series.length > 4 || !data.length) return null;

  const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
  const points: { label: string; color: string; at: number }[] = [];
  if (stacked) {
    // A stack ends together: label each band at its middle in the last period.
    const row = [...data].reverse().find((r) => series.some((s) => num(r[s.key]) !== null));
    if (!row) return null;
    let below = 0;
    for (const s of series) {
      const v = num(row[s.key]) ?? 0;
      const mid = y(below + v / 2);
      below += v;
      if (mid !== undefined && v > 0) points.push({ label: s.label, color: s.color, at: mid });
    }
  } else {
    for (const s of series) {
      const row = [...data].reverse().find((r) => num(r[s.key]) !== null);
      const at = row ? y(num(row[s.key])) : undefined;
      if (at !== undefined) points.push({ label: s.label, color: s.color, at });
    }
  }
  if (x(data[data.length - 1][xKey], { position: "middle" }) === undefined) return null;

  // Keep labels apart, top to bottom, inside the plot.
  points.sort((a, b) => a.at - b.at);
  const top = area.y + 6;
  const bottom = area.y + area.height - 4;
  for (let i = 0; i < points.length; i++) {
    const floor = i === 0 ? top : points[i - 1].at + GAP;
    points[i].at = Math.max(points[i].at, floor);
  }
  for (let i = points.length - 1; i >= 0; i--) {
    const ceiling = i === points.length - 1 ? bottom : points[i + 1].at - GAP;
    points[i].at = Math.min(points[i].at, ceiling);
  }

  const left = area.x + area.width + 8;
  return (
    <g aria-hidden="true">
      {points.map((p) => (
        <g key={p.label}>
          <line x1={left} x2={left + 10} y1={p.at} y2={p.at} stroke={p.color} strokeWidth={3} strokeLinecap="round" />
          <text x={left + 15} y={p.at} dominantBaseline="middle" fontSize={11} fill={CHART.text}>
            {p.label.length > 15 ? `${p.label.slice(0, 14)}…` : p.label}
          </text>
        </g>
      ))}
    </g>
  );
}
