import { apiFetch, parseEnvelopeResponse } from "@/lib/api";

export type Granularity = "month" | "quarter" | "year";

export type CostSeriesPoint = {
  period: string;
  total: number;
  regular: number;
  arrears: number;
  headcount: number;
};

export type CostGroup = {
  group: string;
  total: number;
  share_pct: number;
  series: CostSeriesPoint[];
};

export type CostAnalysis = {
  group_by: string;
  group_by_label: string;
  granularity: Granularity;
  periods: { key: string; label: string }[];
  groups: string[];
  matrix: CostGroup[];
  totals: {
    regular: number;
    arrears: number;
    total: number;
    headcount: number;
    cost_per_head: number;
  };
};

export type DimensionMeta = { key: string; label: string; values: string[] };

/**
 * Categorical series colours, validated against the data-viz six checks in both
 * themes (see scripts/validate_palette.js). Slot order is the entity order:
 * the same group keeps the same colour when a filter changes how many series
 * are on screen, so a chart never repaints its survivors.
 */
export const SERIES_LIGHT = [
  "#4f46e5", "#0e9384", "#dc6803", "#b42318",
  "#0086c9", "#087443", "#a855f7", "#9a3412",
];
export const SERIES_DARK = [
  "#6366f1", "#0d9488", "#d97706", "#e11d48",
  "#0284c7", "#65a30d", "#a855f7", "#ea580c",
];

/** A ninth group is never a generated hue — it folds into this. */
export const OTHER_COLOR_LIGHT = "#667085";
export const OTHER_COLOR_DARK = "#98a2b3";
export const OTHER_LABEL = "Other";

export function fetchCostAnalysis(params: {
  groupBy: string;
  granularity: Granularity;
  dateFrom?: string;
  dateTo?: string;
  filters: Record<string, string[]>;
}): Promise<CostAnalysis> {
  const q = new URLSearchParams();
  q.set("group_by", params.groupBy);
  q.set("granularity", params.granularity);
  if (params.dateFrom) q.set("date_from", params.dateFrom);
  if (params.dateTo) q.set("date_to", params.dateTo);
  for (const [key, values] of Object.entries(params.filters)) {
    for (const value of values) q.append(key, value);
  }
  return apiFetch(`/api/bi/cost-analysis?${q.toString()}`).then((r) =>
    parseEnvelopeResponse<CostAnalysis>(r),
  );
}

export function fetchDimensions(): Promise<{ dimensions: DimensionMeta[] }> {
  return apiFetch("/api/bi/dimensions").then((r) =>
    parseEnvelopeResponse<{ dimensions: DimensionMeta[] }>(r),
  );
}

/** Indian digit grouping, which is what every figure here is read in. */
export function formatINR(value: number, compact = false): string {
  if (compact) {
    if (Math.abs(value) >= 1e7) return `₹${(value / 1e7).toFixed(2)} Cr`;
    if (Math.abs(value) >= 1e5) return `₹${(value / 1e5).toFixed(2)} L`;
  }
  return `₹${Math.round(value).toLocaleString("en-IN")}`;
}

/**
 * Cap the series at eight and fold the rest into one "Other" band.
 *
 * Past eight, a categorical palette stops being readable — the ninth hue is
 * never generated, because two colours nobody can tell apart is worse than an
 * honest aggregate.
 */
export function capSeries(matrix: CostGroup[], limit = 8): CostGroup[] {
  if (matrix.length <= limit) return matrix;

  const head = matrix.slice(0, limit - 1);
  const tail = matrix.slice(limit - 1);
  const periods = head[0]?.series.map((p) => p.period) ?? [];

  const folded: CostGroup = {
    group: OTHER_LABEL,
    total: tail.reduce((n, g) => n + g.total, 0),
    share_pct: tail.reduce((n, g) => n + g.share_pct, 0),
    series: periods.map((period) => {
      const at = (g: CostGroup) => g.series.find((p) => p.period === period);
      return {
        period,
        total: tail.reduce((n, g) => n + (at(g)?.total ?? 0), 0),
        regular: tail.reduce((n, g) => n + (at(g)?.regular ?? 0), 0),
        arrears: tail.reduce((n, g) => n + (at(g)?.arrears ?? 0), 0),
        headcount: tail.reduce((n, g) => n + (at(g)?.headcount ?? 0), 0),
      };
    }),
  };
  return [...head, folded];
}
