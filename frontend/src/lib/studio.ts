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
  workflow?: {
    steps: WorkflowStep[]; failure_branch: WorkflowStep[]; trigger: Record<string, unknown>;
    period: string | null; validation_run_id: string | null;
  } | null;
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

export function runTitle(run: Pick<Run, "kind" | "object_type"> & { source?: Run["source"] }): string {
  if (run.kind === "workflow") return `Workflow “${run.source?.object ?? ""}”`;
  if (run.kind === "import") return `${OBJECT_LABEL[run.object_type ?? ""] ?? run.object_type} import`;
  if (run.kind === "sync") return `${OBJECT_LABEL[run.object_type ?? ""] ?? run.object_type} sync`;
  if (run.kind === "validation") return "Validation";
  return run.kind.replace(/_/g, " ");
}

/** Where integrators send requests from outside: this site's relay, which forwards to the API. */
export function integrationBaseUrl(basePath: string): string {
  if (typeof window === "undefined") return basePath;
  return `${window.location.origin}/api/proxy${basePath}`;
}

// ---------------------------------------------------------------------------
// Phase 2: destinations, connections, streams, mappings
// ---------------------------------------------------------------------------
export type Destination = { id: string; host: string; note: string | null; created_at: string | null };

export type Stream = {
  id: string; name: string; object_type: string; path: string; records_path: string;
  pagination: { type?: string; size?: number; param?: string; size_param?: string; cursor_path?: string };
  sync_mode: "full" | "incremental"; watermark_field: string | null; watermark_param: string | null;
  checkpoint: { watermark?: string; last_run_id?: string; at?: string };
  import_options: { mode?: string; period?: string; deletions?: string; validate?: boolean };
  mapping_key: string | null; mapping_version: number | null;
  schedule: { every?: "hour" | "day" | "week"; at?: string; weekday?: number; timezone?: string };
  next_run_at: string | null; max_attempts: number; max_pages: number; enabled: boolean; last_run_id: string | null;
};

export type Connection = {
  id: string; name: string; system_kind: string; provider: "rest" | "file"; environment: string;
  base_url: string | null; auth_method: string; auth_config: Record<string, unknown>;
  secret_hint: Record<string, string | null>;
  oauth: { connected: boolean; expires_at: string | null; has_refresh_token: boolean } | null;
  secret_updated_at: string | null; direction: string; status: "active" | "disabled";
  health: "healthy" | "failing" | "untested"; last_tested_at: string | null;
  last_test_result: { ok: boolean; message: string; code?: string; sample_fields?: string[] } | null;
  last_success_at: string | null; last_failure_at: string | null; last_error: string | null;
  streams: Stream[]; recent_runs?: Run[];
};

export type MappingField = {
  target: string; source?: string; type?: string; required?: boolean; default?: unknown;
  formats?: string[]; lookup?: Record<string, string>; on_unmatched?: "reject" | "keep" | "blank";
  formula?: string; cases?: { when: { source: string; op: string; value?: unknown }; value: unknown }[];
  else?: unknown; pad_to?: number; aliases?: string[]; codes?: Record<string, string>;
};

export type MappingSpec = { fields: MappingField[]; record_id?: string; keep_unmapped?: boolean };

export type MappingVersion = {
  id: string; key: string; name: string; object_type: string; version: number;
  status: "draft" | "published" | "retired"; spec: MappingSpec; effective_from: string | null;
  change_reason: string | null; created_by: string | null; published_by: string | null;
  published_at: string | null; retired_at: string | null; created_at: string | null; label: string;
};

export type MappingProfile = {
  key: string; name: string; object_type: string; versions: MappingVersion[]; in_force: MappingVersion | null;
};

export type PreviewResult = {
  rows: number; mapped: number; rejected: number; truncated: boolean;
  results: { row: number; output: Record<string, unknown> | null; errors: { code: string; field: string; message: string }[];
    source_record_id: string | null; defaults_used: string[] }[];
};

export const studioConnApi = {
  destinations: () => apiJson<{ hosts: Destination[]; private_destinations_allowed: boolean;
    secret_store: { available: boolean; note: string } }>("/api/studio/destinations"),
  addDestination: (host: string, note?: string) => send<Destination>("/api/studio/destinations", "POST", { host, note }),
  removeDestination: (id: string) => send<{ removed: boolean }>(`/api/studio/destinations/${encodeURIComponent(id)}`, "DELETE"),
  meta: () => apiJson<{ auth_methods: Record<string, { config: string[]; secrets: string[] }>; system_kinds: string[]; providers: string[] }>("/api/studio/connections/meta"),
  list: () => apiJson<Connection[]>("/api/studio/connections"),
  get: (id: string) => apiJson<Connection>(`/api/studio/connections/${encodeURIComponent(id)}`),
  create: (body: Record<string, unknown>) => send<Connection>("/api/studio/connections", "POST", body),
  update: (id: string, body: Record<string, unknown>) => send<Connection>(`/api/studio/connections/${encodeURIComponent(id)}`, "PATCH", body),
  test: (id: string, streamId?: string) =>
    send<{ ok: boolean; message: string; code?: string; sample_fields?: string[] }>(
      `/api/studio/connections/${encodeURIComponent(id)}/test${streamId ? `?stream_id=${encodeURIComponent(streamId)}` : ""}`, "POST"),
  sample: (id: string, streamId: string) =>
    send<{ records: Record<string, unknown>[]; fields: string[] }>(`/api/studio/connections/${encodeURIComponent(id)}/sample?stream_id=${encodeURIComponent(streamId)}`, "POST"),
  oauthStart: (id: string, redirect_uri: string) =>
    send<{ authorize_url: string }>(`/api/studio/connections/${encodeURIComponent(id)}/oauth/start`, "POST", { redirect_uri }),
  oauthFinish: (state: string, code: string) => send<Connection>("/api/studio/oauth/callback", "POST", { state, code }),
  createStream: (connectionId: string, body: Record<string, unknown>) =>
    send<Stream>(`/api/studio/connections/${encodeURIComponent(connectionId)}/streams`, "POST", body),
  updateStream: (id: string, body: Record<string, unknown>) => send<Stream>(`/api/studio/streams/${encodeURIComponent(id)}`, "PATCH", body),
  syncNow: (id: string) => send<Run>(`/api/studio/streams/${encodeURIComponent(id)}/sync`, "POST"),
  resetCheckpoint: (id: string) => send<Stream>(`/api/studio/streams/${encodeURIComponent(id)}/reset-checkpoint`, "POST"),
};

export const studioMapApi = {
  list: () => apiJson<MappingProfile[]>("/api/studio/mappings"),
  get: (id: string) => apiJson<MappingVersion>(`/api/studio/mappings/${encodeURIComponent(id)}`),
  targets: (objectType: string) =>
    apiJson<{ targets: { target: string; type: string }[]; types: string[]; operators: string[]; attendance_categories: string[] }>(
      `/api/studio/mappings/targets?object_type=${encodeURIComponent(objectType)}`),
  create: (body: { key: string; name: string; object_type: string; spec: MappingSpec; change_reason?: string; effective_from?: string | null }) =>
    send<MappingVersion>("/api/studio/mappings", "POST", body),
  update: (id: string, body: { spec?: MappingSpec; name?: string; change_reason?: string; effective_from?: string | null }) =>
    send<MappingVersion>(`/api/studio/mappings/${encodeURIComponent(id)}`, "PATCH", body),
  newVersion: (id: string, change_reason: string) => send<MappingVersion>(`/api/studio/mappings/${encodeURIComponent(id)}/new-version`, "POST", { change_reason }),
  publish: (id: string) => send<MappingVersion>(`/api/studio/mappings/${encodeURIComponent(id)}/publish`, "POST"),
  retire: (id: string, reason: string) => send<MappingVersion>(`/api/studio/mappings/${encodeURIComponent(id)}/retire`, "POST", { reason }),
  compare: (id: string, other: string) =>
    apiJson<{ from: MappingVersion; to: MappingVersion; changes: { target: string; change: string; before?: unknown; after?: unknown }[] }>(
      `/api/studio/mappings/${encodeURIComponent(id)}/compare?other=${encodeURIComponent(other)}`),
  preview: (spec: MappingSpec, object_type: string, records: unknown[]) =>
    send<PreviewResult>("/api/studio/mappings/preview", "POST", { spec, object_type, records }),
  previewFile: async (id: string, file: File): Promise<PreviewResult> => {
    const fd = new FormData();
    fd.append("file", file);
    return apiJson<PreviewResult>(`/api/studio/mappings/${encodeURIComponent(id)}/preview`, { method: "POST", body: fd });
  },
  importFile: async (file: File, meta: Record<string, unknown>): Promise<Run> => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("meta", JSON.stringify(meta));
    return apiJson<Run>("/api/studio/imports", { method: "POST", body: fd });
  },
};

export const AUTH_LABEL: Record<string, string> = {
  none: "No authentication",
  api_key_header: "API key in a header",
  bearer: "Bearer token",
  basic: "Basic — an integration user issued by the system (never a person's password)",
  oauth2_client_credentials: "OAuth 2.0 — client credentials",
  oauth2_authorization_code: "OAuth 2.0 — sign in at the provider (authorisation code + PKCE)",
};

// ---------------------------------------------------------------------------
// Phase 2b: webhooks
// ---------------------------------------------------------------------------
export type Webhook = {
  id: string; name: string; url: string; events: string[]; payload_version: string; environment: string;
  status: "active" | "disabled"; max_attempts: number; secret_rotated_at: string | null;
  last_delivery_at: string | null; last_delivery_status: string | null; deliveries: Record<string, number>;
};
export type Delivery = {
  id: string; webhook_id: string; event_id: string; event_type: string | null;
  status: "pending" | "delivered" | "failed" | "replayed"; attempts: number; next_attempt_at: string | null;
  last_status_code: number | null; last_error: string | null; last_response_ms: number | null;
  delivered_at: string | null; replay_of_id: string | null; created_at: string | null; payload: unknown;
};
export type InboundEndpoint = {
  id: string; name: string; url: string; action: { type: string; object_type: string; mapping_key: string | null; options: Record<string, unknown> };
  environment: string; status: "active" | "disabled"; last_received_at: string | null;
};

export const studioHookApi = {
  catalogue: () => apiJson<{ events: { type: string; description: string }[]; payload_version: string; delivery: string; retry_schedule_seconds: number[] }>("/api/studio/webhooks/events"),
  list: () => apiJson<Webhook[]>("/api/studio/webhooks"),
  create: (body: { name: string; url: string; events: string[]; environment?: string }) =>
    send<Webhook & { secret: string }>("/api/studio/webhooks", "POST", body),
  update: (id: string, body: Record<string, unknown>) => send<Webhook>(`/api/studio/webhooks/${encodeURIComponent(id)}`, "PATCH", body),
  rotate: (id: string, overlap_hours: number) => send<{ secret: string }>(`/api/studio/webhooks/${encodeURIComponent(id)}/rotate-secret`, "POST", { overlap_hours }),
  test: (id: string) => send<{ event_id: string }>(`/api/studio/webhooks/${encodeURIComponent(id)}/test`, "POST"),
  deliveries: (webhookId?: string, status?: string, page = 1) => {
    const qs = new URLSearchParams({ page: String(page), page_size: "50" });
    if (webhookId) qs.set("webhook_id", webhookId);
    if (status) qs.set("status", status);
    return apiJson<Page<Delivery>>(`/api/studio/webhooks/deliveries?${qs.toString()}`);
  },
  replay: (deliveryId: string) => send<Delivery>(`/api/studio/deliveries/${encodeURIComponent(deliveryId)}/replay`, "POST"),
  replayFailed: (id: string) => send<{ replayed: number }>(`/api/studio/webhooks/${encodeURIComponent(id)}/replay-failed`, "POST"),
  inbound: () => apiJson<InboundEndpoint[]>("/api/studio/inbound"),
  createInbound: (body: { name: string; object_type: string; mapping_key?: string | null; options: Record<string, unknown> }) =>
    send<InboundEndpoint & { secret: string }>("/api/studio/inbound", "POST", body),
  updateInbound: (id: string, status: string) => send<InboundEndpoint>(`/api/studio/inbound/${encodeURIComponent(id)}`, "PATCH", { status }),
  receipts: (id: string) => apiJson<{ id: string; event_id: string; run_id: string | null; received_at: string | null }[]>(`/api/studio/inbound/${encodeURIComponent(id)}/receipts`),
};

// ---------------------------------------------------------------------------
// Phase 3 — workflows, notifications, the month's integration picture
// ---------------------------------------------------------------------------
export type WorkflowStep = {
  index: number; type: string; label: string; status: string; attempt?: number; branch?: string;
  started_at?: string; finished_at?: string; message?: string; ref?: { run_id?: string; job_id?: string; event_id?: string };
};

export type WorkflowAction = {
  type: string; label?: string; retries?: number; timeout_minutes?: number; params?: Record<string, unknown>;
};

export type WorkflowCondition = { field: string; op: string; value?: unknown };

export type WorkflowDefinition = {
  trigger: { type: string; schedule?: Record<string, unknown>; required?: string[] };
  conditions: WorkflowCondition[];
  actions: WorkflowAction[];
  on_failure: WorkflowAction[];
};

export type Workflow = {
  id: string; name: string; description: string | null; environment: string;
  status: "draft" | "active" | "disabled"; definition: WorkflowDefinition; active_definition: WorkflowDefinition | null;
  active_version: number; has_changes: boolean; max_runs_per_hour: number; timeout_minutes: number;
  next_run_at: string | null; last_fired_at: string | null; last_skip: { at: string; reason: string } | null;
  last_run: { id: string; status: RunStatus; at: string | null } | null;
  published_at: string | null; updated_at: string | null;
  recent_runs?: Run[];
};

export type WorkflowCatalogue = {
  triggers: Record<string, string>;
  actions: Record<string, { label: string; help: string; failure_branch: boolean }>;
  not_available: Record<string, string>;
  ops: string[]; severities: string[]; inputs: string[]; reports: Record<string, string>; roles: string[];
};

export type DryRun = {
  would_run: boolean;
  conditions: (WorkflowCondition & { actual: unknown; holds: boolean })[];
  steps: { step: number; type: string; label: string; period?: string | null; warning?: string;
           recipients?: string[]; title?: string; stream?: string | null; owner?: string | null; now?: Record<string, number> }[];
  failure_branch: string[];
};

export type Notification = {
  id: string; severity: "info" | "warning" | "error"; title: string; body: string | null; link: string | null;
  source_run_id: string | null; read: boolean; created_at: string | null;
};

export type PeriodIntegration = {
  period: string;
  runs: Run[];
  latest_by_input: Record<string, Run>;
  attention: { run_id: string; object_type: string; status: RunStatus; rejected: number }[];
  connections: { id: string; name: string; health: string; last_error: string | null }[];
};

export const studioFlowApi = {
  catalogue: () => apiJson<WorkflowCatalogue>("/api/studio/workflows/catalogue"),
  list: () => apiJson<Workflow[]>("/api/studio/workflows"),
  get: (id: string) => apiJson<Workflow>(`/api/studio/workflows/${encodeURIComponent(id)}`),
  create: (body: { name: string; description?: string | null; definition: WorkflowDefinition }) =>
    send<Workflow>("/api/studio/workflows", "POST", body),
  update: (id: string, body: Record<string, unknown>) => send<Workflow>(`/api/studio/workflows/${encodeURIComponent(id)}`, "PATCH", body),
  publish: (id: string) => send<Workflow>(`/api/studio/workflows/${encodeURIComponent(id)}/publish`, "POST"),
  enable: (id: string, on: boolean) => send<Workflow>(`/api/studio/workflows/${encodeURIComponent(id)}/${on ? "enable" : "disable"}`, "POST"),
  run: (id: string, period?: string) => send<Run>(`/api/studio/workflows/${encodeURIComponent(id)}/run`, "POST", { period: period || null }),
  dryRun: (definition: WorkflowDefinition, sample: Record<string, unknown> | null, period?: string) =>
    send<DryRun>("/api/studio/workflows/dry-run", "POST", { definition, sample, period: period || null }),
  notifications: () => apiJson<{ unread: number; items: Notification[] }>("/api/studio/notifications"),
  markRead: (ids?: string[]) => send<{ marked: number }>("/api/studio/notifications/read", "POST", { ids: ids ?? null }),
  period: (month: string) => apiJson<PeriodIntegration>(`/api/studio/period/${encodeURIComponent(month)}`),
};

export const STEP_VARIANT: Record<string, "success" | "warning" | "destructive" | "secondary" | "primary"> = {
  completed: "success", warning: "warning", failed: "destructive", cancelled: "secondary", skipped: "secondary",
  pending: "secondary", running: "primary", waiting: "primary",
};

// ---------------------------------------------------------------------------
// Phase 4 — developer workspace, environments, releases
// ---------------------------------------------------------------------------
export type FormulaResult = {
  expression: string; ok: boolean; error?: string; variables?: string[]; functions?: string[]; in_words?: string;
  results: { row: number; value?: number; error?: string; inputs?: Record<string, number>; missing?: string[] }[];
  truncated?: boolean;
};

export type DevReference = {
  functions: Record<string, string>; operators: string[]; not_allowed: string[]; max_length: number; variables: string;
  scripting: { enabled: boolean; reason: string; requires: string[]; instead: string };
};

export type EnvName = "development" | "test" | "production";

export type ReleaseImpactItem = {
  kind: string; name: string; source_version: number | null; target_version?: number | null;
  change: "create" | "update" | "unchanged" | "retire" | "disable"; diff: Record<string, unknown>[];
  blocking: string[]; warnings: string[]; tested?: { run_id: string; status: RunStatus } | null;
};

export type Release = {
  id: string; title: string; notes: string | null;
  status: "draft" | "awaiting_approval" | "approved" | "promoted" | "rejected" | "cancelled";
  source: { id: string; name: string; environment: EnvName }; target: { id: string; name: string; environment: EnvName };
  items: { kind: string; name: string; source_version: number | null }[];
  result: { kind: string; name: string; outcome: string; version?: number }[] | null;
  rollback_of_id: string | null; created_by: string | null; decided_by: string | null; decision_note: string | null;
  promoted_by: string | null; created_at: string | null; decided_at: string | null; promoted_at: string | null;
  can_roll_back: boolean;
  impact?: { items: ReleaseImpactItem[]; blocking: number; warnings: number };
};

export const studioDevApi = {
  reference: () => apiJson<DevReference>("/api/studio/developer/reference"),
  formula: (expression: string, samples: unknown[]) => send<FormulaResult>("/api/studio/developer/formula", "POST", { expression, samples }),
  conditions: (conditions: WorkflowCondition[], samples: unknown[]) =>
    send<{ ok: boolean; error?: string; results: { row: number; holds: boolean; conditions: (WorkflowCondition & { actual: unknown; holds: boolean })[] }[] }>(
      "/api/studio/developer/conditions", "POST", { conditions, samples }),
  lookup: (table: Record<string, string>, values: unknown[], on_unmatched: string) =>
    send<{ ok: boolean; error?: string; results: { row: number; value: unknown; result?: unknown; matched?: boolean; error?: string }[] }>(
      "/api/studio/developer/lookup", "POST", { table, values, on_unmatched }),
};

export const studioReleaseApi = {
  environment: () => apiJson<{ environment: EnvName; companies: { id: string; name: string; environment: EnvName; manage: boolean }[] }>("/api/studio/environment"),
  setEnvironment: (environment: EnvName) => send<{ environment: EnvName }>("/api/studio/environment", "PUT", { environment }),
  list: () => apiJson<Release[]>("/api/studio/releases"),
  candidates: () => apiJson<{ environment: EnvName; mappings: { name: string; label: string; version: number; object_type: string }[]; workflows: { name: string; version: number; status: string }[] }>("/api/studio/releases/candidates"),
  create: (body: { target_entity_id: string; title: string; notes?: string | null; items: { kind: string; name: string }[] }) =>
    send<Release>("/api/studio/releases", "POST", body),
  get: (id: string) => apiJson<Release>(`/api/studio/releases/${encodeURIComponent(id)}`),
  act: (id: string, action: "submit" | "promote" | "rollback" | "cancel") => send<Release>(`/api/studio/releases/${encodeURIComponent(id)}/${action}`, "POST"),
  decide: (id: string, approve: boolean, note?: string) => send<Release>(`/api/studio/releases/${encodeURIComponent(id)}/decide`, "POST", { approve, note: note || null }),
};

export const RELEASE_VARIANT: Record<Release["status"], "success" | "warning" | "destructive" | "secondary" | "primary"> = {
  draft: "secondary", awaiting_approval: "warning", approved: "primary", promoted: "success", rejected: "destructive", cancelled: "secondary",
};
