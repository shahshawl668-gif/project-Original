import { apiJson } from "@/lib/api";

/** The Report Builder's API: one approved dataset, previews, versioned saved definitions. */

export type BuilderField = { key: string; label: string; numeric: boolean };
export type BuilderDataset = {
  key: string; label: string; grain: string; note: string;
  fields: BuilderField[]; dimensions: { key: string; label: string }[];
};
export type Calculation = { key: string; label: string; expression: string };
export type Spec = {
  dataset: "payroll_cost"; dimension: string; fields: string[];
  filters: Record<string, string[]>; date_from: string | null; date_to: string | null;
  sort: string; order: "asc" | "desc"; calculations: Calculation[];
};
export type PreviewStatus = "ok" | "missing_data" | "no_matching_records";
export type Preview = {
  status: PreviewStatus; rows: Record<string, string | number | null>[]; record_count: number;
  truncated_preview?: boolean; control_totals: Record<string, number> | null; grain: string;
};
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
};
export const JOB_ACTIVE: ReadonlySet<string> = new Set(["queued", "running"]);
export type ReportVersion = { version: number; name: string; specification: Spec; created_at: string | null };

/** The server shows at most this many rows in a preview; the export has no limit. */
export const PREVIEW_LIMIT = 200;
export const MAX_RANGE_MONTHS = 24;
export const MAX_CALCULATIONS = 3;
/** Metrics a calculation may name — the server rejects anything else. */
export const CALC_METRICS = ["gross", "deductions", "net", "employer_cost", "ctc", "headcount", "person_months"];
export const MONEY_FIELDS = new Set(["gross", "deductions", "net", "employer_cost", "ctc", "cost_per_head"]);

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
  queue: (id: string) => apiJson<ReportJob>(`/api/reports/builder/saved/${id}/jobs`, { method: "POST" }),
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
export function unknownMetrics(expression: string): string[] {
  const names = expression.match(/[A-Za-z_][A-Za-z0-9_]*/g) ?? [];
  return Array.from(new Set(names.filter((n) => !CALC_METRICS.includes(n))));
}
