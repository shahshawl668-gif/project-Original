/**
 * PeopleOps Studio: the client for /api/studio (the screens' own API).
 *
 * The integration API itself (/api/integration/v1) is for other systems and
 * accepts only integration keys; these pages manage those keys and read what
 * the keys did, but never call the integration API with a key.
 */
import { apiFetch, apiJson } from "@/lib/api";

export type RunStatus =
  | "queued" | "running" | "completed" | "partially_completed" | "failed" | "cancelled" | "awaiting_approval";

export type Counts = {
  received: number | null; accepted: number | null; rejected: number | null; skipped: number | null;
  created: number | null; updated: number | null; unchanged: number | null; removed: number | null;
};

export type Run = {
  id: string;
  kind: string;
  object_type: string | null;
  status: RunStatus;
  stage: string | null;
  trigger: string;
  actor: { type: "user" | "machine"; label: string; credential_prefix: string | null };
  environment: string;
  company_id: string;
  source: { system: string | null; object: string | null; batch_id: string | null };
  period_month: string | null;
  effective_from: string | null;
  counts: Counts | null;
  versions: Record<string, unknown>;
  error: { category: string; message: string; recommended_action: string | null } | null;
  attempts: number;
  retry_of_run_id: string | null;
  links: Record<string, unknown> & {
    validation_job_id?: string | null; validation_run_id?: string | null;
    master_upload_id?: string; attendance_register_id?: string; ctc_upload_id?: string;
    register_upload_id?: string; ignored_columns?: string[]; warnings?: string[];
  };
  request_id: string | null;
  queued_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  // detail only
  options?: Record<string, unknown>;
  retries?: { id: string; status: RunStatus; queued_at: string }[];
  rejection_summary?: { disposition: string; code: string; count: number }[];
};

export type Rejection = {
  id: string; row_number: number; record_key: string | null; disposition: "rejected" | "skipped";
  code: string; field: string | null; message: string; source_ref: Record<string, string>;
  retried_in_run_id: string | null; payload_retained: boolean; retain_until: string | null;
  record?: unknown;
};

export type Credential = {
  id: string; label: string; prefix: string; state: "active" | "rotating" | "expired" | "revoked";
  expires_at: string; last_used_at: string | null; revoked_at: string | null; revoke_reason: string | null;
  rotated_from_id: string | null; rotated_to_id: string | null; created_at: string | null;
};

export type IssuedCredential = Credential & { key: string; shown_once: true };

export type ServiceAccount = {
  id: string; name: string; description: string | null; environment: "development" | "test" | "production";
  status: "active" | "disabled"; scopes: string[]; companies: { id: string; name: string }[];
  hidden_companies: number; credentials: Credential[]; created_at: string | null;
};

export type Scope = { scope: string; grants: string; writes: boolean };

export type Section = { key: string; label: string; href: string | null; available: boolean; summary: string };

export type Overview = {
  company: { id: string; name: string };
  service_accounts: { total: number; active: number };
  keys: { active: number; expiring_within_14_days: { prefix: string; expires_at: string }[] };
  runs_last_7_days: Partial<Record<RunStatus, number>>;
  last_run: Run | null;
  needs_attention: Run[];
  worker_enabled: boolean;
  integration_api: { base_path: string; openapi: string; docs: string;
    limits: { requests_per_minute: number; max_request_mb: number; max_records: number } };
  sections: Section[];
};

export type Page<T> = { items: T[]; page: number; page_size: number; total: number; pages: number };

const send = <T,>(path: string, method: string, body?: unknown) =>
  apiJson<T>(path, { method, body: body === undefined ? undefined : JSON.stringify(body) });

export const studioApi = {
  overview: () => apiJson<Overview>("/api/studio/overview"),
  scopes: () => apiJson<Scope[]>("/api/studio/scopes"),
  accounts: () => apiJson<ServiceAccount[]>("/api/studio/service-accounts"),
  createAccount: (body: { name: string; description?: string | null; environment: string; entity_ids: string[]; scopes: string[] }) =>
    send<ServiceAccount>("/api/studio/service-accounts", "POST", body),
  updateAccount: (id: string, body: { description?: string | null; entity_ids?: string[]; scopes?: string[]; status?: string }) =>
    send<ServiceAccount>(`/api/studio/service-accounts/${encodeURIComponent(id)}`, "PATCH", body),
  issueKey: (accountId: string, body: { label: string; expires_in_days: number }) =>
    send<IssuedCredential>(`/api/studio/service-accounts/${encodeURIComponent(accountId)}/keys`, "POST", body),
  rotateKey: (id: string, body: { grace_hours: number; expires_in_days: number }) =>
    send<{ new: IssuedCredential; previous: Credential }>(`/api/studio/keys/${encodeURIComponent(id)}/rotate`, "POST", body),
  revokeKey: (id: string, reason: string) =>
    send<Credential>(`/api/studio/keys/${encodeURIComponent(id)}/revoke`, "POST", { reason }),
  runs: (params: Record<string, string | number | undefined>) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== "") qs.set(k, String(v)); });
    return apiJson<Page<Run>>(`/api/studio/runs?${qs.toString()}`);
  },
  run: (id: string) => apiJson<Run>(`/api/studio/runs/${encodeURIComponent(id)}`),
  rejections: (id: string, page = 1, disposition?: string) =>
    apiJson<Page<Rejection>>(`/api/studio/runs/${encodeURIComponent(id)}/rejections?page=${page}&page_size=100${disposition ? `&disposition=${disposition}` : ""}`),
  rejectedRecord: (runId: string, rejectionId: string) =>
    apiJson<Rejection>(`/api/studio/runs/${encodeURIComponent(runId)}/rejections/${encodeURIComponent(rejectionId)}/record`),
  retryRejected: (id: string) => send<Run>(`/api/studio/runs/${encodeURIComponent(id)}/retry-rejected`, "POST"),
  cancel: (id: string) => send<Run>(`/api/studio/runs/${encodeURIComponent(id)}/cancel`, "POST"),
  /** The published contract. Public: no key is needed to read it. */
  openapi: async (): Promise<OpenApi> => {
    const res = await apiFetch("/api/integration/v1/openapi.json");
    if (!res.ok) throw new Error(`Could not load the API contract (HTTP ${res.status})`);
    return res.json();
  },
};

export type OpenApiOperation = {
  summary?: string; description?: string; tags?: string[];
  parameters?: { name: string; in: string; required?: boolean; description?: string; schema?: { type?: string; pattern?: string; default?: unknown } }[];
  requestBody?: { content?: Record<string, { example?: unknown; examples?: Record<string, { summary?: string; value: unknown }> }> };
  responses?: Record<string, { description?: string }>;
};

export type OpenApi = {
  info: { title: string; version: string; description: string };
  servers?: { url: string }[];
  tags?: { name: string; description?: string }[];
  paths: Record<string, Record<string, OpenApiOperation>>;
};

export const STATUS_LABEL: Record<RunStatus, string> = {
  queued: "Queued",
  running: "Running",
  completed: "Completed",
  partially_completed: "Partially completed",
  failed: "Failed",
  cancelled: "Cancelled",
  awaiting_approval: "Awaiting approval",
};

export const STATUS_VARIANT: Record<RunStatus, "success" | "warning" | "destructive" | "secondary" | "primary"> = {
  queued: "secondary",
  running: "primary",
  completed: "success",
  partially_completed: "warning",
  failed: "destructive",
  cancelled: "secondary",
  awaiting_approval: "warning",
};

export const OBJECT_LABEL: Record<string, string> = {
  employee_master: "Employee master",
  ctc: "CTC",
  attendance: "Attendance",
  salary_register: "Salary register",
  validation: "Validation",
};

export function runTitle(run: Pick<Run, "kind" | "object_type">): string {
  if (run.kind === "import") return `${OBJECT_LABEL[run.object_type ?? ""] ?? run.object_type} import`;
  if (run.kind === "validation") return "Validation";
  return run.kind.replace(/_/g, " ");
}

/** Where integrators send requests from outside: this site's relay, which forwards to the API. */
export function integrationBaseUrl(basePath: string): string {
  if (typeof window === "undefined") return basePath;
  return `${window.location.origin}/api/proxy${basePath}`;
}
