import { apiDownload, apiFetch, apiJson, parseEnvelopeResponse } from "@/lib/api";

/**
 * Disbursement validation: is this salary payment file safe to release?
 *
 * The product checks the file and keeps a clean copy; it never sends anything
 * to a bank. Shapes mirror /api/disbursement exactly, including what was *not*
 * checked (`unchecked`, rule status NOT_RUN / DISABLED), which the page shows
 * every time rather than leaving out.
 */

export type Verdict = "CLEAR_TO_RELEASE" | "RELEASE_WITH_HOLDS" | "DO_NOT_RELEASE";
export type Severity = "STOP_FILE" | "HOLD_ROW" | "FLAG" | "NOT_RUN" | "DISABLED";
export type RuleStatus = "RAN" | "NOT_RUN" | "NOT_APPLICABLE" | "DISABLED";

export type Rule = {
  rule_id: string;
  title: string;
  level: string;
  default_severity: Severity;
  allowed: Severity[];
  needs: string[];
};

export type Catalogue = {
  rules: Rule[];
  defaults: Record<string, unknown>;
  profiles: { key: string; name: string; note: string; bank_template: string | null; builtin: boolean }[];
  templates: { key: string; name: string; note: string; layout: string; builtin: boolean }[];
  inputs: { slot: Slot; label: string; required: boolean }[];
  retention_days: number;
};

export type Slot = "bank_file" | "register" | "bank_master" | "change_log" | "previous" | "hold_list" | "offcycle";

export type Settings = {
  profile_key: string;
  template_key: string | null;
  overrides: Record<string, unknown> & {
    severities?: Record<string, Severity>;
    enabled?: Record<string, boolean>;
  };
  custom_profiles: Record<string, unknown>;
  custom_templates: Record<string, unknown>;
  updated_by: string | null;
  updated_at: string | null;
  independence_required: boolean;
};

export type Totals = {
  due_total: string;
  due_count: number;
  file_total: string;
  file_rows: number;
  unreadable_amounts: number;
  held_amount: string;
  held_rows: number;
  held_employees: number;
  release_amount: string;
  release_rows: number;
  release_employees: number;
  flags: number;
  previous_total: string | null;
  previous_total_basis: string | null;
  amount_basis: string;
  variance_vs_previous: string | null;
  variance_pct_vs_previous: number | null;
};

export type Approval = {
  approver: string;
  approver_email: string;
  approver_role: string | null;
  approved_at: string | null;
  fingerprint: string;
  acknowledged: string[];
  independent: boolean;
  independence_required: boolean;
  comment: string | null;
  release_amount: string;
  release_employees: number;
};

export type Run = {
  id: string;
  period: string;
  value_date: string | null;
  verdict: Verdict;
  status: "checked" | "approved";
  profile_key: string;
  template_key: string;
  bank_filename: string | null;
  totals: Totals;
  rule_status: Record<string, RuleStatus>;
  unchecked: string[];
  clean_filename: string | null;
  clean_sha256: string | null;
  clean_available: boolean;
  files_expire_at: string | null;
  files_cleared_at: string | null;
  previous_run_id: string | null;
  run_by: string;
  created_at: string | null;
  approval: Approval | null;
};

export type Finding = {
  rule_id: string;
  severity: Severity;
  employee_id: string;
  employee_name: string;
  field: string;
  expected: string;
  actual: string;
  reason: string;
  rows: number[];
  amount: string;
};

export type ReportRule = { rule_id: string; title: string; severity: Severity; status: RuleStatus; reason: string; findings: number };
export type BridgeLine = { label: string; amount: string | null; count: number; total?: boolean };

export type Report = {
  verdict: Verdict;
  totals: Totals;
  bridge: BridgeLine[];
  rules: ReportRule[];
  findings: Finding[];
  notes: { source: string; message: string; row: number | null; employee_id: string | null }[];
  inputs: { slot: string; label: string; filename: string; sha256: string; rows: number | null }[];
  settings: Record<string, unknown>;
  profile: string;
  template: string;
};

export type Held = { employee_id: string; employee_name: string; rows: number[]; amount: string; reasons: string[] };

export type RunDetail = Run & {
  report: Report;
  held: Held[];
  superseded_by: string | null;
  independence_required: boolean;
  can_approve: boolean;
};

export const VERDICT_TEXT: Record<Verdict, string> = {
  CLEAR_TO_RELEASE: "Clear to release",
  RELEASE_WITH_HOLDS: "Release with holds",
  DO_NOT_RELEASE: "Do not release",
};

export const SEVERITY_TEXT: Record<Severity, string> = {
  STOP_FILE: "Stops the file",
  HOLD_ROW: "Held",
  FLAG: "Flag",
  NOT_RUN: "Not run",
  DISABLED: "Switched off",
};

export const SEVERITY_TONE: Record<Severity, string> = {
  STOP_FILE: "bg-danger-100 text-danger-800",
  HOLD_ROW: "bg-warning-100 text-warning-900",
  FLAG: "bg-brand-50 text-brand-800",
  NOT_RUN: "bg-ink-100 text-ink-800",
  DISABLED: "bg-ink-100 text-ink-700",
};

/** Rupees and paise, Indian grouping. A payment file is checked to the paisa, so it is shown to the paisa. */
export function money(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return String(value);
  const text = Math.abs(n).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${n < 0 ? "−" : ""}₹${text}`;
}

const BASE = "/api/disbursement";

export const fetchCatalogue = () => apiJson<Catalogue>(`${BASE}/catalogue`);
export const fetchSettings = () => apiJson<Settings>(`${BASE}/settings`);
export const fetchRuns = (period?: string) =>
  apiJson<{ runs: Run[] }>(`${BASE}/runs${period ? `?period=${encodeURIComponent(period)}` : ""}`);
export const fetchRun = (id: string) => apiJson<RunDetail>(`${BASE}/runs/${id}`);

export async function saveSettings(body: Pick<Settings, "profile_key" | "template_key" | "overrides" | "custom_profiles" | "custom_templates">): Promise<Settings> {
  return apiJson<Settings>(`${BASE}/settings`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function createRun(input: {
  period: string;
  valueDate?: string;
  profileKey?: string;
  usePreviousApproved: boolean;
  files: Partial<Record<Slot, File>>;
}): Promise<Run> {
  const form = new FormData();
  form.append("period", input.period);
  if (input.valueDate) form.append("value_date", input.valueDate);
  if (input.profileKey) form.append("profile_key", input.profileKey);
  form.append("use_previous_approved", input.usePreviousApproved ? "true" : "false");
  for (const [slot, file] of Object.entries(input.files)) {
    if (file) form.append(slot, file, file.name);
  }
  const res = await apiFetch(`${BASE}/runs`, { method: "POST", body: form });
  return parseEnvelopeResponse<Run>(res);
}

export async function approveRun(id: string, body: {
  approver_name: string;
  fingerprint: string;
  acknowledged: string[];
  comment?: string;
}): Promise<Run> {
  return apiJson<Run>(`${BASE}/runs/${id}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export type DownloadKind = "clean" | "exceptions.csv" | "exceptions.xlsx" | "summary.pdf";

export const downloadRun = (id: string, kind: DownloadKind) =>
  apiDownload(`${BASE}/runs/${id}/download/${kind}`, kind === "clean" ? "clean_bank_file" : kind);
