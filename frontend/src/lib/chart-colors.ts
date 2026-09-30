/**
 * Chart colours for every chart in the product — one system.
 *
 * - One measure is one colour: a single series (a bar per department, a line
 *   over months) is drawn in the primary blue; its title names it.
 * - Several series take the validated categorical palette (`SERIES`, from
 *   cost analysis, checked for colour-vision separation) in its fixed slot
 *   order. A ninth never gets a generated hue: it folds into "Other".
 * - A breakdown whose values are states — severity, review state — takes the
 *   status colours, and its labels are always shown, so colour never carries
 *   the meaning alone.
 */
import { OTHER_COLOR, OTHER_LABEL, SERIES } from "@/lib/cost-analysis";

export const CHART = {
  primary: SERIES[0],
  grid: "#eef0f3",
  axis: "#636c7e", // tick labels are text: 4.5:1 or better on white
  text: "#474f61",
} as const;

const STATUS: Record<string, string> = {
  critical: "#d03b3b",
  high: "#d03b3b",
  open: "#d03b3b",
  failed: "#d03b3b",
  warning: "#fab219",
  medium: "#fab219",
  "cannot validate": "#fab219",
  info: "#2a78d6",
  acknowledged: "#2a78d6",
  "in progress": "#2a78d6",
  low: "#0ca30c",
  passed: "#0ca30c",
  resolved: "#0ca30c",
  waived: "#8a93a4",
};

/** Status colours when every value is a known state; otherwise null. */
export function statusColors(labels: string[]): string[] | null {
  const keys = labels.map((l) => l.trim().toLowerCase());
  return keys.length && keys.every((k) => k in STATUS) ? keys.map((k) => STATUS[k]) : null;
}

/**
 * Colours for a categorical breakdown in fixed slot order, with anything past
 * the palette folded into one "Other" entry. Returns the rows to draw.
 */
export function categorical<T extends { name: string; value: number | null }>(rows: T[]): (T & { color: string })[] {
  const status = statusColors(rows.map((r) => r.name));
  if (status) return rows.map((r, i) => ({ ...r, color: status[i] }));
  if (rows.length <= SERIES.length) return rows.map((r, i) => ({ ...r, color: SERIES[i] }));
  const head = rows.slice(0, SERIES.length - 1).map((r, i) => ({ ...r, color: SERIES[i] }));
  const rest = rows.slice(SERIES.length - 1);
  const other = rest.reduce((a, r) => a + (r.value ?? 0), 0);
  return [...head, { ...rest[0], name: `${OTHER_LABEL} (${rest.length})`, value: other, color: OTHER_COLOR }];
}

export const tooltipStyle = {
  contentStyle: {
    background: "#ffffff",
    border: "1px solid #dfe2e8",
    borderRadius: 8,
    boxShadow: "0 12px 32px -8px rgb(16 24 40 / 0.16)",
    fontSize: 12,
    color: "#111522",
  },
  labelStyle: { color: "#474f61", fontWeight: 600 },
  cursor: { fill: "rgb(16 24 40 / 0.04)" },
};
