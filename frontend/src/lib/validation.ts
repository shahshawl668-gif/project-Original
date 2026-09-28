/**
 * Validation jobs and runs, read from the server.
 *
 * Results used to live in the browser's sessionStorage: a whole register's
 * findings, copied into one tab. Closing the tab lost them, a second tab could
 * not see them, and a 20,000-employee result was megabytes of JSON parsed on a
 * phone. Now a validation is a job on the server and its result is a run with
 * an id; pages ask for the slice they show.
 */
import { apiBlob, apiFetch, parseEnvelopeResponse } from "@/lib/api";

export type JobState = "queued" | "running" | "succeeded" | "failed" | "cancelled";

export type ValidationJob = {
  id: string;
  state: JobState;
  stage: string;
  stage_label: string;
  period_month: string | null;
  run_type: string;
  upload_id: string | null;
  employee_total: number;
  employee_done: number;
  percent: number;
  run_id: string | null;
  error: string | null;
  error_code: string | null;
  attempts: number;
  max_attempts: number;
  cancel_requested: boolean;
  retry_of_job_id: string | null;
  queue_position: number | null;
  can_cancel: boolean;
  can_retry: boolean;
  queued_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  worker_enabled: boolean;
};

export type RegisterUpload = {
  id: string;
  period_month: string | null;
  revision: number;
  run_type: string;
  filename: string | null;
  sheet_name: string | null;
  file_sha256: string;
  file_size: number;
  row_count: number;
  rows_sha256: string;
  missing_required: string[];
  warnings: string[];
  stored_as_register: boolean;
  uploaded_at: string | null;
};

export type InputChange = { input: string; label: string; detail: string };

export type Freshness = {
  is_current_for_inputs: boolean;
  revalidation_required: boolean;
  changes: InputChange[];
  latest_upload_id: string | null;
};

export type ValidationRun = {
  id: string;
  period_month: string;
  run_number: number;
  status: "current" | "superseded";
  source: string;
  run_type: string | null;
  employee_count: number;
  total_findings: number;
  critical_count: number;
  warning_count: number;
  total_financial_impact: number | null;
  open_financial_impact: number | null;
  engine_version: string | null;
  job_id: string | null;
  superseded_by_run_id: string | null;
  superseded_at: string | null;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  inputs_recorded: boolean;
  upload?: RegisterUpload | null;
  summary?: Record<string, unknown>;
  freshness?: Freshness;
  period_runs?: { id: string; run_number: number; status: string; created_at: string | null; total_findings: number }[];
};

export type Computed = {
  pf_wage: number | null;
  pf_type: string | null;
  pf_amount_employee: number | null;
  pf_amount_employer: number | null;
  pf_breakup: { wage_capped: number; eps: number; epf: number; edli: number; admin: number } | null;
  esic_wage: number | null;
  esic_eligible: boolean | null;
  esic_employee: number | null;
  esic_employer: number | null;
  pt_applicable_state: string | null;
  pt_due: number | null;
  lwf_applicable_state: string | null;
  lwf_employee: number | null;
  lwf_employer: number | null;
  paid_days: number | null;
  lop_days: number | null;
  gross_total: number | null;
  score_breakdown: Record<string, number> | null;
};

export type RunEmployee = {
  employee_id: string;
  employee_name: string | null;
  department: string | null;
  work_state: string | null;
  row_kind: string | null;
  risk_score: number;
  risk_level: "LOW" | "MEDIUM" | "HIGH";
  failed_checks: number;
  critical_count: number;
  warning_count: number;
  passed_checks: number;
  financial_impact: number | null;
  gross: number | null;
  net_pay: number | null;
  computed?: Computed;
};

export type RunFinding = {
  id: string;
  fingerprint: string;
  employee_id: string;
  employee_name: string | null;
  rule_id: string;
  rule_name: string;
  component: string | null;
  category: string;
  severity: "CRITICAL" | "WARNING" | "INFO";
  status: string;
  expected_value: string | null;
  actual_value: string | null;
  difference: string | null;
  financial_impact: number | null;
  reason: string | null;
  suggested_fix: string | null;
  was_waived: boolean;
  state: string | null;
  occurrence_count: number | null;
};

export type Page<T> = {
  page: number;
  page_size: number;
  total: number;
  pages: number;
  items: T[];
};

export type EmployeePage = Page<RunEmployee> & {
  risk_levels: Record<string, number>;
  employee_results_recorded: boolean;
};

export type FindingPage = Page<RunFinding> & {
  rules: { rule_id: string; rule_name: string; severity: string; count: number }[];
};

export type PeriodStatus = {
  period_month: string;
  stage: string;
  stage_label: string;
  upload: RegisterUpload | null;
  active_job: ValidationJob | null;
  last_job: ValidationJob | null;
  current_run: ValidationRun | null;
  open_findings: number;
  freshness: Freshness | null;
  signoff_state: string | null;
};

export type ComparedFinding = {
  fingerprint: string;
  employee_id: string;
  employee_name: string | null;
  rule_id: string;
  rule_name: string;
  component: string | null;
  severity: string;
  expected_value: string | null;
  actual_value: string | null;
  difference: string | null;
  financial_impact: number | null;
  before?: ComparedFinding;
};

export type RunComparison = {
  base: ValidationRun;
  target: ValidationRun;
  counts: Record<"new" | "resolved" | "changed" | "unchanged", number>;
  financial_impact: Record<"new" | "resolved" | "changed" | "unchanged", number>;
  items: Record<"new" | "resolved" | "changed" | "unchanged", ComparedFinding[]>;
  truncated: Record<string, boolean>;
};

function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === null || v === undefined || v === "" || v === false) continue;
    p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

async function get<T>(path: string): Promise<T> {
  return parseEnvelopeResponse<T>(await apiFetch(path));
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  return parseEnvelopeResponse<T>(
    await apiFetch(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) }),
  );
}

export const validationApi = {
  enqueue: (body: {
    period_month: string;
    upload_id?: string | null;
    run_type?: string;
    effective_month_from?: string | null;
    effective_month_to?: string | null;
  }) => post<{ job: ValidationJob; already_queued: boolean }>("/api/validation/jobs", body),
  job: (id: string) => get<ValidationJob>(`/api/validation/jobs/${encodeURIComponent(id)}`),
  jobs: (params: { active?: boolean; period_month?: string; limit?: number } = {}) =>
    get<ValidationJob[]>(`/api/validation/jobs${qs(params)}`),
  cancel: (id: string) => post<ValidationJob>(`/api/validation/jobs/${encodeURIComponent(id)}/cancel`),
  retry: (id: string) =>
    post<{ job: ValidationJob; already_queued: boolean }>(`/api/validation/jobs/${encodeURIComponent(id)}/retry`),
  runs: (params: { period_month?: string; include_superseded?: boolean; limit?: number } = {}) =>
    get<ValidationRun[]>(
      `/api/validation/runs${qs({ ...params, include_superseded: params.include_superseded === false ? "false" : params.include_superseded })}`,
    ),
  run: (id: string) => get<ValidationRun>(`/api/validation/runs/${encodeURIComponent(id)}`),
  employees: (
    runId: string,
    params: {
      page?: number; page_size?: number; sort?: string; order?: "asc" | "desc"; q?: string;
      risk_level?: string; only_with_findings?: boolean; include_computed?: boolean;
    } = {},
  ) => get<EmployeePage>(`/api/validation/runs/${encodeURIComponent(runId)}/employees${qs(params)}`),
  employee: (runId: string, employeeId: string) =>
    get<{ run: ValidationRun; employee: RunEmployee; result: Record<string, unknown>; source_row: Record<string, unknown> | null }>(
      `/api/validation/runs/${encodeURIComponent(runId)}/employees/${encodeURIComponent(employeeId)}`,
    ),
  findings: (
    runId: string,
    params: {
      page?: number; page_size?: number; sort?: string; order?: "asc" | "desc"; severity?: string;
      rule_id?: string; employee_id?: string; rule_prefix?: string; q?: string;
    } = {},
  ) => get<FindingPage>(`/api/validation/runs/${encodeURIComponent(runId)}/findings${qs(params)}`),
  compare: (base: string, target: string, show = "all") =>
    get<RunComparison>(`/api/validation/runs/compare${qs({ base, target, show })}`),
  periodStatus: (period: string) =>
    get<PeriodStatus>(`/api/validation/periods/${encodeURIComponent(period)}/status`),
  exportRun: (runId: string) => apiBlob(`/api/validation/runs/${encodeURIComponent(runId)}/export.xlsx`),
};

export const monthLabel = (iso: string | null | undefined) => {
  if (!iso) return "—";
  const d = new Date(`${iso.slice(0, 10)}T00:00:00`);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString("en-IN", { month: "short", year: "numeric" });
};

export const inr = (n: number | null | undefined, digits = 0) =>
  n == null
    ? "—"
    : `₹${n.toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
