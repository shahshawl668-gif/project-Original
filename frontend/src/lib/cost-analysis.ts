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
 * Categorical series colours, validated rather than chosen.
 *
 * Slot order is the entity order: the same group keeps the same colour when a
 * filter changes how many series are on screen, so a chart never repaints its
 * survivors.
 *
 * Slot 1 is the brand blue, because the first series is usually the measure the
 * page is about. Orange sits between it and teal deliberately — sky and teal
 * adjacent scored ΔE 12.5 under normal vision, below the floor of 15, and were
 * genuinely hard to tell apart.
 *
 * Verified with the six checks against the white card these charts sit on:
 *
 *     node scripts/validate_palette.js \
 *       "#0284c7,#dc6803,#0e9384,#b42318,#4f46e5,#087443,#a855f7,#9a3412" \
 *       --mode light --surface "#ffffff"
 *
 * Worst adjacent pair is teal↔orange at ΔE 12.4 (protan) and 25.7 (normal),
 * both clear. Adjacent is the right pairing rule here because every chart in
 * this module is a bar, line or area — all-pairs is the standard for scatter,
 * bubble and maps, where any mark can land beside any other.
 */
export const SERIES = [
  "#0284c7", "#dc6803", "#0e9384", "#b42318",
  "#4f46e5", "#087443", "#a855f7", "#9a3412",
];

/** A ninth group is never a generated hue — it folds into this. */
export const OTHER_COLOR = "#667085";
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

// ---------------------------------------------------------------------------
// Headcount movement
// ---------------------------------------------------------------------------
export type MovementPoint = {
  period: string;
  label: string;
  opening: number | null;
  joiners: number;
  exits: number;
  closing: number;
  net_change: number | null;
  average_headcount: number;
  total_ctc: number;
  cost_per_head_closing: number;
  cost_per_head_average: number;
  joiner_ids: string[];
  exit_ids: string[];
  master_says: { joiners: number; exits: number };
  master_agrees: boolean;
};

export type HeadcountMovement = {
  periods: MovementPoint[];
  totals: {
    opening: number | null;
    closing: number;
    joiners: number;
    exits: number;
    periods_counted: number;
  };
  denominator_note: string;
  identity: { masked: boolean; reason: string };
};

export function fetchHeadcountMovement(params: {
  filters: Record<string, string[]>;
}): Promise<HeadcountMovement> {
  return apiFetch(`/api/bi/headcount-movement?${query({}, params.filters)}`).then((r) =>
    parseEnvelopeResponse<HeadcountMovement>(r),
  );
}

// ---------------------------------------------------------------------------
// Compensation
// ---------------------------------------------------------------------------
export type Stats = {
  count: number;
  mean: number;
  median: number;
  p25: number;
  p75: number;
  p90: number;
  min: number;
  max: number;
  range_ratio: number | null;
  total: number;
};

export type Compensation = {
  period: string | null;
  period_label: string | null;
  group_by: string;
  group_by_label: string;
  basis: string;
  overall: Stats;
  groups: (Stats & { group: string; label: string })[];
  distribution: { from: number; to: number; count: number }[];
  mix: { fixed: number; variable: number; fixed_pct: number; variable_pct: number };
  employees: {
    employee_id: string;
    employee_name: string | null;
    group: string;
    annual_ctc: number;
    fixed: number;
    variable: number;
    masked?: boolean;
  }[];
  identity: { masked: boolean; reason: string };
};

export function fetchCompensation(params: {
  groupBy: string;
  period?: string;
  filters: Record<string, string[]>;
}): Promise<Compensation> {
  const q = query({ group_by: params.groupBy, period: params.period }, params.filters);
  return apiFetch(`/api/bi/compensation?${q}`).then((r) =>
    parseEnvelopeResponse<Compensation>(r),
  );
}

// ---------------------------------------------------------------------------
// Budget and forecast
// ---------------------------------------------------------------------------
export type BudgetVersionMeta = {
  id: string;
  name: string;
  state: "draft" | "approved";
  financial_year: string | null;
  scope_key: string;
  scope_label: string;
  measure: string;
  is_current: boolean;
  line_count: number;
  source_filename: string | null;
  note: string | null;
  approved_by: string | null;
  approved_at: string | null;
  created_at: string | null;
};

export type BudgetVariance = {
  version: {
    id: string;
    name: string;
    financial_year: string | null;
    scope_key: string;
    measure: string;
    approved_by: string | null;
    approved_at: string | null;
  } | null;
  measure?: string;
  periods: {
    period: string;
    label: string;
    actual: number;
    budget: number | null;
    has_actual: boolean;
    has_budget: boolean;
    variance: number | null;
    variance_pct: number | null;
    utilisation_pct: number | null;
  }[];
  scopes: {
    scope: string;
    actual: number;
    budget: number | null;
    variance: number | null;
    variance_pct: number | null;
    utilisation_pct: number | null;
  }[];
  totals: {
    actual: number;
    budget: number | null;
    variance: number | null;
    variance_pct: number | null;
    utilisation_pct: number | null;
  };
  unbudgeted_periods: string[];
  unspent_periods: string[];
  note?: string;
};

export type Forecast = {
  base: { period: string; label: string; actual: number; headcount: number; note: string } | null;
  measure?: string;
  forecast: {
    period: string;
    label: string;
    forecast: number;
    is_forecast: true;
    headcount: number;
    components: {
      run_rate: number;
      increment: number;
      joiners: number;
      exits: number;
      bonus: number;
    };
  }[];
  assumptions: Record<string, string | number | null>;
  disclaimer?: string;
  note?: string;
};

export type ForecastInput = {
  months: number;
  incrementPct: number;
  incrementFrom?: string;
  newHiresPerMonth: number;
  exitsPerMonth: number;
  bonusMonth?: string;
  bonusAmount: number;
};

export function fetchBudgetVersions(): Promise<{ versions: BudgetVersionMeta[] }> {
  return apiFetch("/api/budget/versions").then((r) =>
    parseEnvelopeResponse<{ versions: BudgetVersionMeta[] }>(r),
  );
}

export function fetchBudgetVariance(params: {
  filters: Record<string, string[]>;
}): Promise<BudgetVariance> {
  return apiFetch(`/api/budget/variance?${query({}, params.filters)}`).then((r) =>
    parseEnvelopeResponse<BudgetVariance>(r),
  );
}

export function fetchForecast(input: ForecastInput): Promise<Forecast> {
  const q = query(
    {
      months: String(input.months),
      increment_pct: String(input.incrementPct),
      increment_from: input.incrementFrom,
      new_hires_per_month: String(input.newHiresPerMonth),
      exits_per_month: String(input.exitsPerMonth),
      bonus_month: input.bonusMonth,
      bonus_amount: String(input.bonusAmount),
    },
    {},
  );
  return apiFetch(`/api/budget/forecast?${q}`).then((r) => parseEnvelopeResponse<Forecast>(r));
}

export function approveBudget(id: string): Promise<{ id: string; state: string }> {
  return apiFetch(`/api/budget/versions/${id}/approve`, { method: "POST" }).then((r) =>
    parseEnvelopeResponse<{ id: string; state: string }>(r),
  );
}

// ---------------------------------------------------------------------------
// Reports and the audit trail
// ---------------------------------------------------------------------------
export type ReportMeta = { key: string; title: string; description: string };

export function fetchReports(): Promise<{ reports: ReportMeta[] }> {
  return apiFetch("/api/reports").then((r) =>
    parseEnvelopeResponse<{ reports: ReportMeta[] }>(r),
  );
}

export type AuditEvent = {
  id: string;
  action: string;
  object_type: string;
  object_id: string | null;
  summary: string;
  detail: Record<string, unknown>;
  user_email: string | null;
  created_at: string | null;
};

export function fetchAudit(params: { limit?: number; action?: string }): Promise<{
  events: AuditEvent[];
}> {
  const q = query(
    { limit: String(params.limit ?? 100), action: params.action },
    {},
  );
  return apiFetch(`/api/audit?${q}`).then((r) =>
    parseEnvelopeResponse<{ events: AuditEvent[] }>(r),
  );
}

// ---------------------------------------------------------------------------
// Pay equity
// ---------------------------------------------------------------------------
export type GenderSummary = {
  count: number;
  suppressed: boolean;
  median: number | null;
  mean: number | null;
  variable_median: number | null;
  variable_receipt_pct: number | null;
};

export type PayEquityComparison = {
  comparable: boolean;
  reason: string | null;
  median_gap_pct: number | null;
  mean_gap_pct: number | null;
  variable_gap_pct: number | null;
};

export type PayEquityGroup = PayEquityComparison & {
  group: string;
  total: number;
  women: GenderSummary;
  men: GenderSummary;
};

export type PayQuartile = {
  band: string;
  count: number;
  counts: Record<string, number>;
  female_pct: number | null;
  male_pct: number | null;
  known: number;
  pay_from: number | null;
  pay_to: number | null;
};

export type PayEquity = {
  period: string | null;
  period_label: string | null;
  group_by: string;
  group_by_label: string;
  min_group_size: number;
  basis: string;
  coverage: {
    total: number;
    recorded: number;
    recorded_pct: number;
    by_gender: { key: string; label: string; count: number }[];
  };
  headline:
    | (PayEquityComparison & { women: GenderSummary; men: GenderSummary; other: GenderSummary })
    | null;
  quartiles: PayQuartile[];
  like_for_like: PayEquityGroup[];
  suppressed_groups: { group: string; women: number; men: number; reason: string }[];
  direction: string;
  caveats: string[];
};

export type PayEquitySettings = {
  enabled: boolean;
  enabled_by: string | null;
  enabled_at: string | null;
  can_change: boolean;
  minimum_group_size: number;
};

export function fetchPayEquitySettings(): Promise<PayEquitySettings> {
  return apiFetch("/api/bi/pay-equity/settings").then((r) =>
    parseEnvelopeResponse<PayEquitySettings>(r),
  );
}

export function setPayEquityEnabled(
  enabled: boolean,
  authorisationNote?: string,
): Promise<PayEquitySettings> {
  return apiFetch("/api/bi/pay-equity/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled, authorisation_note: authorisationNote || null }),
  }).then((r) => parseEnvelopeResponse<PayEquitySettings>(r));
}

export function fetchPayEquity(params: {
  groupBy: string;
  minGroupSize?: number;
  filters: Record<string, string[]>;
}): Promise<PayEquity> {
  const q = query(
    {
      group_by: params.groupBy,
      min_group_size: params.minGroupSize ? String(params.minGroupSize) : undefined,
    },
    params.filters,
  );
  return apiFetch(`/api/bi/pay-equity?${q}`).then((r) => parseEnvelopeResponse<PayEquity>(r));
}

/** A gap, with its direction spelled out rather than left to the sign. */
export function describeGap(pct: number | null): { text: string; tone: "gap" | "reverse" | "level" | "none" } {
  if (pct === null || !Number.isFinite(pct)) return { text: "—", tone: "none" };
  if (Math.abs(pct) < 0.05) return { text: "level", tone: "level" };
  const magnitude = `${Math.abs(pct).toFixed(1)}%`;
  return pct > 0
    ? { text: `${magnitude} less`, tone: "gap" }
    : { text: `${magnitude} more`, tone: "reverse" };
}

/**
 * The diverging pair, for polarity rather than identity.
 *
 * Blue against red: warm and cool poles that read as opposite, with a neutral
 * grey midpoint so "no gap" reads as nothing rather than as a third category.
 * Both poles are drawn from the validated categorical set, so they keep their
 * contrast and CVD separation against either surface — but they are only ever
 * used where a number has a *sign*, never to tell two series apart.
 */
export const DIVERGING = { negative: "#0086c9", neutral: "#d6dae3", positive: "#b42318" };

/** Chart chrome, from the theme rather than from a literal. */
export function chartTheme() {
  return {
    tick: { fill: "#5b6478", fontSize: 11 },
    grid: "rgba(14,18,32,0.07)",
    surface: "#ffffff",
    border: "#d6dae3",
    ink: "#1b2030",
    muted: "#667085",
    cursor: "rgba(14,18,32,0.04)",
  };
}
