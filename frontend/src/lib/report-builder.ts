import { apiJson } from "@/lib/api";

/** The Report Builder's API: approved datasets, previews, versioned saved definitions, schedules. */

export type Unit = "inr" | "number" | "pct" | "month" | "text";
export type BuilderField = {
  key: string; label: string; numeric: boolean; unit?: Unit; calc?: boolean;
  across_periods?: boolean; across_groups?: boolean;
};
export type BuilderDataset = {
  key: string; label: string; grain: string; note: string;
  fields: BuilderField[]; dimensions: { key: string; label: string }[];
  default_breakdown: string; default_fields: string[]; filters: boolean;
};
export type CalcUnit = "inr" | "number" | "pct";
export type Calculation = { key: string; label: string; expression: string; unit?: CalcUnit };
export type Layout = "table" | "pivot";
export type ChartKind = "none" | "bar" | "line";
export type Spec = {
  dataset: string; dimension: string; fields: string[];
  filters: Record<string, string[]>; date_from: string | null; date_to: string | null;
  sort: string; order: "asc" | "desc"; calculations: Calculation[];
  layout?: Layout; pivot_value?: string | null; chart?: ChartKind;
};
export type PreviewStatus = "ok" | "missing_data" | "no_matching_records";
export type Column = { key: string; label: string; unit: Unit; across_periods: boolean; across_groups: boolean };
export type Pivot = {
  value: string; label: string; unit: Unit; periods: string[];
  rows: { dimension: string; cells: Record<string, number | null>; total: number | null }[];
  column_totals: Record<string, number | null> | null; grand_total: number | null;
  row_totals: boolean; note: string | null;
};
export type ChartData =
  | { type: "bar"; value: string; label: string; unit: Unit; period: string; bars: { group: string; value: number | null }[]; omitted: number }
  | { type: "line"; value: string; label: string; unit: Unit; periods: string[]; series: { group: string; points: (number | null)[] }[]; omitted: number };
export type Preview = {
  status: PreviewStatus; rows: Record<string, string | number | null>[]; record_count: number;
  truncated_preview?: boolean; control_totals: Record<string, number> | null; grain: string;
  columns?: Column[]; pivot?: Pivot | null; chart?: ChartData | null;
};
export type OutputFormat = "xlsx" | "pdf";
export type Schedule = {
  id: string; frequency: "monthly" | "weekly"; day: number; hour: number; months: number;
  format: OutputFormat; enabled: boolean; next_run_at: string | null; last_run_at: string | null;
  last_job_id: string | null; last_error: string | null; delivery: string;
};
export type ScheduleInput = Pick<Schedule, "frequency" | "day" | "hour" | "months" | "format" | "enabled">;
export type SavedReport = {
  id: string; name: string; description: string | null; version: number;
  visibility: "private" | "shared"; status: "draft" | "published";
  specification: Spec; updated_at: string | null; created_at: string | null;
};
/** A queued Excel generation. The file is fixed once made and kept until it expires. */
export type JobState = "queued" | "running" | "succeeded" | "failed" | "cancelled" | "expired";
export type ReportJob = {
  id: string; definition_id: string; definition_name: string; definition_version: number;
  state: JobState; stage: string; attempt: number; record_count: number | null;
  artifact_bytes: number | null; queued_at: string | null; finished_at: string | null;
  expires_at: string | null; error_message: string | null; cancel_requested: boolean;
  format?: OutputFormat; origin?: "person" | "schedule";
};
export const JOB_ACTIVE: ReadonlySet<string> = new Set(["queued", "running"]);
export type ReportVersion = { version: number; name: string; specification: Spec; created_at: string | null };

/** The server shows at most this many rows in a preview; the export has no limit. */
export const PREVIEW_LIMIT = 200;
export const MAX_RANGE_MONTHS = 24;
export const MAX_CALCULATIONS = 3;
export const UNIT_LABEL: Record<CalcUnit, string> = { inr: "Rupees (₹)", number: "A count or number", pct: "A percentage" };

export const builderApi = {
  datasets: () => apiJson<{ datasets: BuilderDataset[] }>("/api/reports/builder/datasets"),
  saved: () => apiJson<{ reports: SavedReport[] }>("/api/reports/builder/saved"),
  versions: (id: string) => apiJson<{ versions: ReportVersion[] }>(`/api/reports/builder/saved/${id}/versions`),
  preview: (specification: Spec) =>
    apiJson<Preview>("/api/reports/builder/preview", { method: "POST", body: JSON.stringify({ specification }) }),
  save: (id: string | null, body: { name: string; description: string | null; specification: Spec; visibility: string; status: string }) =>
    apiJson<SavedReport>(id ? `/api/reports/builder/saved/${id}` : "/api/reports/builder/saved", {
      method: id ? "PUT" : "POST", body: JSON.stringify(body),
    }),
  clone: (id: string) => apiJson<SavedReport>(`/api/reports/builder/saved/${id}/clone`, { method: "POST" }),
  queue: (id: string, format: OutputFormat = "xlsx") =>
    apiJson<ReportJob>(`/api/reports/builder/saved/${id}/jobs`, { method: "POST", body: JSON.stringify({ format }) }),
  schedule: (id: string) => apiJson<{ schedule: Schedule | null }>(`/api/reports/builder/saved/${id}/schedule`),
  setSchedule: (id: string, body: ScheduleInput) =>
    apiJson<{ schedule: Schedule }>(`/api/reports/builder/saved/${id}/schedule`, { method: "PUT", body: JSON.stringify(body) }),
  removeSchedule: (id: string) => apiJson<{ schedule: null }>(`/api/reports/builder/saved/${id}/schedule`, { method: "DELETE" }),
  jobs: () => apiJson<{ jobs: ReportJob[] }>("/api/reports/builder/jobs"),
  cancel: (jobId: string) => apiJson<ReportJob>(`/api/reports/builder/jobs/${jobId}/cancel`, { method: "POST" }),
  retry: (jobId: string) => apiJson<ReportJob>(`/api/reports/builder/jobs/${jobId}/retry`, { method: "POST" }),
};

/** Months between two ISO dates, inclusive of both ends. */
export function monthsBetween(from: string, to: string): number {
  const [fy, fm] = from.split("-").map(Number);
  const [ty, tm] = to.split("-").map(Number);
  return (ty - fy) * 12 + (tm - fm) + 1;
}

/** Names in an expression the server would refuse, so the step can say so before a round trip. */
export function unknownMetrics(expression: string, allowed: string[]): string[] {
  const names = expression.match(/[A-Za-z_][A-Za-z0-9_]*/g) ?? [];
  return Array.from(new Set(names.filter((n) => !allowed.includes(n))));
}
