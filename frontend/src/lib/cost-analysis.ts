import { apiFetch, parseEnvelopeResponse } from "@/lib/api";

export type Granularity = "month" | "quarter" | "year";

/** Every figure the taxonomy carries, keyed by measure. */
export type Measures = Record<string, number>;

export type CostSeriesPoint = {
  period: string;
  value: number;
  headcount: number;
  measures: Measures;
};

export type CostGroup = {
  group: string;
  total: number;
  share_pct: number;
  measures: Measures;
  series: CostSeriesPoint[];
};

export type PeriodTotal = {
  period: string;
  label: string;
  headcount: number;
  measures: Measures;
};

export type CostAnalysis = {
  group_by: string;
  group_by_label: string;
  granularity: Granularity;
  measure: string;
  measure_label: string;
  periods: { key: string; label: string }[];
  groups: string[];
  matrix: CostGroup[];
  period_totals: PeriodTotal[];
  totals: Measures & { headcount: number; cost_per_head: number };
  sources: { reported: number; computed: number };
};

export type MeasureMeta = {
  key: string;
  label: string;
  layer: "earnings" | "employer" | "deduction";
  hint: string;
};

export type MeasureCatalogue = {
  measures: MeasureMeta[];
  derived: { key: string; label: string; parts: string[] }[];
};

export type DimensionMeta = { key: string; label: string; values: string[] };

export type DeltaRow = {
  key: string;
  label: string;
  layer: string;
  group?: string;
  a: number;
  b: number;
  delta: number;
  delta_pct: number | null;
  headcount_a?: number;
  headcount_b?: number;
};

export type CostCompare = {
  group_by: string;
  group_by_label: string;
  measure: string;
  measure_label: string;
  a: { period: string; label: string; present: boolean; headcount: number; measures: Measures };
  b: { period: string; label: string; present: boolean; headcount: number; measures: Measures };
  by_measure: DeltaRow[];
  by_derived: DeltaRow[];
  by_group: DeltaRow[];
  headcount: { a: number; b: number; delta: number };
};

export type Obligation = {
  key: string;
  label: string;
  authority: string;
  cadence: string;
  note: string;
  due_date: string;
  due_basis: string;
  days_left: number;
  status: "no_register" | "blocked" | "overdue" | "due_soon" | "ready" | "open";
  open_findings: number;
  at_risk_amount: number;
};

export type Readiness = {
  period: string;
  period_label: string;
  as_of: string;
  register_uploaded: boolean;
  signed_off: boolean;
  signoff_state: string | null;
  obligations: Obligation[];
  disclaimer: string;
};

export type PeriodOption = { period: string; label: string };

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

/**
 * The three layers of cost, and what each is made of.
 *
 * Ordered so a reader moves the way the money does: what was earned, what the
 * employer paid on top, what came back out of the earnings. Keys match the
 * backend taxonomy in services/cost_model.py; labels come from the API so they
 * are never stated twice.
 */
export const LAYERS: { key: "earnings" | "employer" | "deduction"; label: string; blurb: string }[] = [
  { key: "earnings", label: "Earnings", blurb: "What the register paid." },
  { key: "employer", label: "Employer contributions", blurb: "Cost on top of gross, never seen by the employee." },
  { key: "deduction", label: "Employee deductions", blurb: "Taken out of gross — not added to it." },
];

function query(params: Record<string, string | undefined>, filters: Record<string, string[]>) {
  const q = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value) q.set(key, value);
  for (const [key, values] of Object.entries(filters)) {
    for (const value of values) q.append(key, value);
  }
  return q.toString();
}

export function fetchCostAnalysis(params: {
  groupBy: string;
  granularity: Granularity;
  measure: string;
  dateFrom?: string;
  dateTo?: string;
  filters: Record<string, string[]>;
}): Promise<CostAnalysis> {
  const q = query(
    {
      group_by: params.groupBy,
      granularity: params.granularity,
      measure: params.measure,
      date_from: params.dateFrom,
      date_to: params.dateTo,
    },
    params.filters,
  );
  return apiFetch(`/api/bi/cost-analysis?${q}`).then((r) => parseEnvelopeResponse<CostAnalysis>(r));
}

export function fetchCostCompare(params: {
  periodA: string;
  periodB: string;
  groupBy: string;
  measure: string;
  filters: Record<string, string[]>;
}): Promise<CostCompare> {
  const q = query(
    {
      period_a: params.periodA,
      period_b: params.periodB,
      group_by: params.groupBy,
      measure: params.measure,
    },
    params.filters,
  );
  return apiFetch(`/api/bi/cost-compare?${q}`).then((r) => parseEnvelopeResponse<CostCompare>(r));
}

export function fetchDimensions(): Promise<{ dimensions: DimensionMeta[] }> {
  return apiFetch("/api/bi/dimensions").then((r) =>
    parseEnvelopeResponse<{ dimensions: DimensionMeta[] }>(r),
  );
}

export function fetchMeasures(): Promise<MeasureCatalogue> {
  return apiFetch("/api/bi/measures").then((r) => parseEnvelopeResponse<MeasureCatalogue>(r));
}

export function fetchPeriods(): Promise<{ periods: PeriodOption[] }> {
  return apiFetch("/api/bi/periods").then((r) =>
    parseEnvelopeResponse<{ periods: PeriodOption[] }>(r),
  );
}

export function fetchReadiness(period: string): Promise<Readiness> {
  return apiFetch(`/api/bi/compliance?period=${period}`).then((r) =>
    parseEnvelopeResponse<Readiness>(r),
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

/** A signed change, with the sign kept — a fall is not a smaller rise. */
export function formatDelta(value: number, compact = true): string {
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${formatINR(Math.abs(value), compact)}`;
}

export function formatPct(value: number | null): string {
  // A percentage against a zero base is not a large number, it is no number.
  if (value === null || !Number.isFinite(value)) return "—";
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${Math.abs(value).toFixed(1)}%`;
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
  const sumMeasures = (pick: (g: CostGroup) => Measures | undefined): Measures => {
    const out: Measures = {};
    for (const g of tail) {
      for (const [key, value] of Object.entries(pick(g) ?? {})) {
        out[key] = (out[key] ?? 0) + value;
      }
    }
    return out;
  };

  const folded: CostGroup = {
    group: OTHER_LABEL,
    total: tail.reduce((n, g) => n + g.total, 0),
    share_pct: tail.reduce((n, g) => n + g.share_pct, 0),
    measures: sumMeasures((g) => g.measures),
    series: periods.map((period) => {
      const at = (g: CostGroup) => g.series.find((p) => p.period === period);
      return {
        period,
        value: tail.reduce((n, g) => n + (at(g)?.value ?? 0), 0),
        headcount: tail.reduce((n, g) => n + (at(g)?.headcount ?? 0), 0),
        measures: sumMeasures((g) => at(g)?.measures),
      };
    }),
  };
  return [...head, folded];
}
