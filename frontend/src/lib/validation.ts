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
  cannot_validate_checks: number | null;
  not_applicable_checks: number | null;
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
  /** False when the engine does not price this check: show "Impact not calculated", never ₹0. */
  impact_calculated: boolean;
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
  changed_since_signoff: InputChange[];
  readiness: Readiness;
};

// ─── Coverage: five outcomes per check ────────────────────────────────────────

export type Outcome = "passed" | "failed" | "cannot_validate" | "not_applicable" | "disabled";

export const OUTCOME_LABEL: Record<Outcome, string> = {
  passed: "Passed",
  failed: "Failed",
  cannot_validate: "Cannot validate",
  not_applicable: "Not applicable",
  disabled: "Disabled",
};

export type RuleCoverage = {
  rule_id: string;
  name: string;
  family: string;
  material: boolean;
  runs_in_validation: boolean;
  counts: Record<Outcome, number>;
};

export type CoverageSummary = {
  totals: Record<Outcome, number>;
  coverage_pct: number | null;
  material_cannot_validate: number;
  missing_inputs: Record<string, number>;
  rules: RuleCoverage[];
};

export type ExposureSummary = {
  gross: number;
  open: number;
  overlap_excluded: number;
  impact_not_calculated: number;
  raw_sum_before_deduplication: number;
};

export type Verdict = { outcome: Outcome; reason: string };

// ─── Why this result? ─────────────────────────────────────────────────────────

export type FindingExplanation = {
  context: {
    company: string; employee_id: string; employee_name: string | null; period_month: string;
    run_id: string; run_number: number; run_status: string; engine_version: string | null;
    validated_at: string | null;
  };
  source: {
    recorded: boolean; filename?: string | null; sheet?: string | null; file_sha256?: string;
    revision?: number; row?: number | null; field?: string | null; source_column?: string | null;
    value?: unknown;
  };
  rule: {
    rule_id: string; rule_name: string; severity: string; component: string | null;
    custom_rule: Record<string, unknown> | null;
    policy: Record<string, unknown> | null;
  };
  inputs: Record<string, unknown>;
  calculation: {
    family: string | null; steps: string[]; basis: Record<string, unknown>;
    tolerance: unknown; reconstructed_from: string;
  };
  values: {
    expected: string | null; actual: string | null; difference: string | null;
    financial_impact: number | null; impact_calculated: boolean; impact_label: string | null;
  };
  explanation: string | null;
  suggested_fix: string | null;
  review: {
    state: string | null; note: string | null; waiver_reason: string | null; waived_until: string | null;
    was_waived_in_this_run: boolean; first_seen: string | null; occurrences: number | null;
    history: { from: string | null; to: string; reason: string | null; waived_until: string | null; by: string | null; at: string | null }[];
  };
  approval: {
    state: string | null; signed_by: string | null; signed_at: string | null;
    history: { from: string | null; to: string; reason: string | null; at: string | null }[];
  };
};

// ─── Approval ─────────────────────────────────────────────────────────────────

export type ApprovalPolicy = {
  signoff_requires_independent_approver: boolean;
  matrix_publish_requires_independent_approver: boolean;
};

export type ReadinessBlocker = { code: string; message: string; acceptable: boolean };

export type Readiness = {
  period_month: string;
  ready: boolean;
  blockers: ReadinessBlocker[];
  run_id: string | null;
  run_number: number | null;
  freshness: Freshness | null;
  coverage: { coverage_pct: number | null; material_cannot_validate: number | null; totals: Record<Outcome, number> | null } | null;
  policy?: ApprovalPolicy;
};

export type SignOff = {
  id: string;
  period_month: string;
  state: "draft" | "pending_approval" | "signed" | "reopened";
  signed_by_email: string | null;
  signed_at: string | null;
  prepared_at: string | null;
  employee_count: number | null;
  open_findings: number | null;
  accepted_exposure: number;
  snapshot_digest: string | null;
  notes: string | null;
};

export type SignOffDetail = {
  signoff: SignOff;
  snapshot: Record<string, unknown> & {
    prepared_by?: string;
    readiness?: { accepted_gaps?: { reason: string } | null };
    approval?: { independent?: boolean; preparer?: string | null; approver?: string | null; policy?: ApprovalPolicy };
  };
  history: { from_state: string | null; to_state: string; reason: string | null; actor_email: string | null; snapshot_digest: string | null; created_at: string | null }[];
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
      only_unverifiable?: boolean;
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
  explain: (runId: string, findingId: string) =>
    get<FindingExplanation>(
      `/api/validation/runs/${encodeURIComponent(runId)}/findings/${encodeURIComponent(findingId)}/explain`,
    ),
  periodStatus: (period: string) =>
    get<PeriodStatus>(`/api/validation/periods/${encodeURIComponent(period)}/status`),
  exportRun: (runId: string) => apiBlob(`/api/validation/runs/${encodeURIComponent(runId)}/export.xlsx`),
};

/** Month sign-off: preparation, independent approval, reopening and the evidence pack. */
export const signoffApi = {
  readiness: (period: string) => get<Readiness>(`/api/signoff/${encodeURIComponent(period)}/readiness`),
  /** Null when the month has never been submitted. */
  get: async (period: string): Promise<SignOffDetail | null> => {
    const res = await apiFetch(`/api/signoff/${encodeURIComponent(period)}`);
    if (res.status === 404) return null;
    return parseEnvelopeResponse<SignOffDetail>(res);
  },
  submit: (body: { period_month: string; notes?: string | null; accept_incomplete_reason?: string | null }) =>
    post<SignOff>("/api/signoff/submit", body),
  sign: (body: { period_month: string; notes?: string | null; accept_incomplete_reason?: string | null }) =>
    post<SignOff>("/api/signoff/sign", body),
  reopen: (body: { period_month: string; reason: string }) => post<SignOff>("/api/signoff/reopen", body),
  evidencePack: (period: string) => apiBlob(`/api/signoff/${encodeURIComponent(period)}/evidence-pack`),
  policy: () => get<ApprovalPolicy>("/api/org/approval-policy"),
  setPolicy: async (body: Partial<ApprovalPolicy>) =>
    parseEnvelopeResponse<ApprovalPolicy>(
      await apiFetch("/api/org/approval-policy", { method: "PUT", body: JSON.stringify(body) }),
    ),
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
