import { apiFetch, parseEnvelopeResponse } from "@/lib/api";

/**
 * Bank file and journal voucher reconciliation.
 *
 * Every shape here mirrors the API exactly, including the parts that report an
 * *absence*: a month with no bank file comes back with `ready: false` and a
 * sentence saying so, and the UI shows that sentence rather than an empty
 * panel. An empty panel reads as a clean month.
 */

// ---------------------------------------------------------------------------
// Shared
// ---------------------------------------------------------------------------
export type Severity = "high" | "medium" | "low";

export type ReconException = {
  code: string;
  label: string;
  severity: Severity;
  title: string;
  detail: string | null;
  meaning: string | null;
  action: string | null;
  employee_id: string | null;
  employee_name: string | null;
  scope: string | null;
  expected: number | null;
  actual: number | null;
  difference: number | null;
  context: Record<string, unknown>;
};

export type ExceptionCounts = {
  total: number;
  by_severity: Record<Severity, number>;
  by_code: Record<string, number>;
};

export type ExceptionKind = {
  code: string;
  label: string;
  severity: Severity;
  meaning: string;
  action: string;
};

// ---------------------------------------------------------------------------
// Bank side
// ---------------------------------------------------------------------------
export type BankFieldMeta = {
  key: string;
  label: string;
  required: boolean;
  hint: string;
};

export type OptionMeta = { key: string; label: string; hint?: string };

export type BankFieldCatalogue = {
  fields: BankFieldMeta[];
  kinds: OptionMeta[];
  layouts: OptionMeta[];
  amount_units: OptionMeta[];
  amount_signs: OptionMeta[];
  id_transforms: OptionMeta[];
};

export type BankProfile = {
  id: string;
  name: string;
  bank_label: string | null;
  note: string | null;
  kind: string;
  layout: string;
  delimiter: string;
  encoding: string;
  has_header: boolean;
  skip_rows: number;
  trailer_rows: number;
  column_map: Record<string, string | number | number[]>;
  amount_unit: string;
  amount_sign: string;
  date_format: string | null;
  employee_id_transform: string;
  row_filter: Record<string, unknown>;
  is_default: boolean;
  created_at: string | null;
};

export type BankPreset = Omit<BankProfile, "id" | "is_default" | "created_at"> & {
  key: string;
};

export type BankFileMeta = {
  id: string;
  period: string;
  period_label: string;
  kind: string;
  filename: string | null;
  row_count: number;
  total: number;
  stated_total: number | null;
  problems: string[];
  note: string | null;
  profile_id: string | null;
  uploaded_by: string | null;
  created_at: string | null;
};

export type BankFileRow = {
  row_number: number;
  employee_id: string | null;
  employee_name: string | null;
  account_number: string | null;
  ifsc: string | null;
  amount: number;
  reference: string | null;
  status: string | null;
  value_date: string | null;
};

export type ProfileTest = {
  filename: string;
  row_count: number;
  skipped_by_filter: number;
  total: number;
  stated_total: number | null;
  header: string[];
  problems: string[];
  rows: BankFileRow[];
  truncated: boolean;
};

export type MappingSuggestion = {
  header: string[];
  sample: string[][];
  column_map: Record<string, string>;
  unmapped_columns?: string[];
  note: string;
};

export type BankReconciliation = {
  period: string;
  period_label: string;
  file: {
    id: string;
    filename: string | null;
    kind: string;
    row_count: number;
    total: number;
    stated_total: number | null;
  };
  summary: {
    register_employees: number;
    bank_rows: number;
    matched: number;
    unmatched_in_register: number;
    unmatched_in_file: number;
    due_total: number;
    paid_total: number;
    matched_total: number;
    difference: number;
    reconciled: boolean;
    tolerance: number;
  };
  counts: ExceptionCounts;
  exceptions: ReconException[];
};

// ---------------------------------------------------------------------------
// Ledger side
// ---------------------------------------------------------------------------
export type JvMeasureMeta = OptionMeta & {
  layer: string;
  hint: string;
  derived: boolean;
  /** The base measures this one stands for. Empty for `net`, which stands for none. */
  parts: string[];
};

export type JvOptions = {
  posting_bases: OptionMeta[];
  split_modes: OptionMeta[];
  detail_levels: OptionMeta[];
  sign_conventions: OptionMeta[];
  voucher_date_rules: OptionMeta[];
  rounding_modes: OptionMeta[];
  net_pay_sources: OptionMeta[];
  export_formats: OptionMeta[];
  group_by: OptionMeta[];
  sides: OptionMeta[];
  measures: JvMeasureMeta[];
};

export type JvRule = {
  id?: string;
  sequence?: number;
  label: string;
  account_code: string;
  account_name: string | null;
  side: "debit" | "credit";
  measures: string[];
  filters: Record<string, string[]>;
  cost_center_from: string | null;
  active: boolean;
  note?: string | null;
};

export type JvTemplate = {
  id: string;
  name: string;
  note: string | null;
  state: "draft" | "approved";
  is_current: boolean;
  posting_basis: string;
  split_mode: string;
  group_by: string | null;
  detail_level: string;
  sign_convention: string;
  net_pay_source: string;
  voucher_date_rule: string;
  voucher_type: string;
  narration_template: string;
  export_format: string;
  balance_tolerance: number;
  rounding_mode: string;
  rounding_account: string | null;
  approved_by: string | null;
  approved_at: string | null;
  created_at: string | null;
  rule_count: number;
  rules?: JvRule[];
};

export type JvPreset = {
  key: string;
  name: string;
  note: string;
  posting_basis: string;
  split_mode: string;
  detail_level: string;
  group_by: string | null;
  sign_convention: string;
  net_pay_source: string;
  rules: JvRule[];
  rule_count: number;
};

export type VoucherLine = {
  account_code: string;
  account_name: string;
  label: string;
  side: "debit" | "credit";
  amount: number;
  debit: number;
  credit: number;
  cost_center: string | null;
  measures: string[];
  employee_id: string | null;
  employee_name: string | null;
};

export type Voucher = {
  number: string;
  date: string;
  type: string;
  scope: string | null;
  narration: string;
  lines: VoucherLine[];
  total_debit: number;
  total_credit: number;
  difference: number;
  balanced: boolean;
};

export type JvDocument = {
  period: string;
  period_label: string;
  options: Record<string, unknown>;
  employee_count: number;
  vouchers: Voucher[];
  total_debit: number;
  total_credit: number;
  difference: number;
  balanced: boolean;
  warnings: string[];
  cost_totals: Record<string, number>;
  template?: JvTemplate;
};

export type JvReconciliation = JvDocument & {
  counts: ExceptionCounts;
  exceptions: ReconException[];
  summary: {
    vouchers: number;
    lines: number;
    total_debit: number;
    total_credit: number;
    difference: number;
    payroll_cost: number;
    employee_count: number;
    reconciled: boolean;
  };
};

// ---------------------------------------------------------------------------
// Runs and the month as a whole
// ---------------------------------------------------------------------------
export type ReconRun = {
  id: string;
  period: string;
  period_label: string;
  kind: string;
  state: "open" | "closed";
  summary: Record<string, unknown>;
  bank_file_id: string | null;
  jv_template_id: string | null;
  exception_count: number;
  created_by: string | null;
  created_at: string | null;
  closed_by: string | null;
  closed_at: string | null;
  exceptions?: ReconException[];
};

export type Overview = {
  period: string | null;
  period_label?: string;
  ready?: boolean;
  message?: string;
  periods: { key: string; label: string }[];
  register?: { employees: number; net_due: number; stated_net_available: boolean };
  bank?: {
    files: BankFileMeta[];
    paid_total: number;
    ready: boolean;
    message: string | null;
  };
  jv?: { template: JvTemplate | null; ready: boolean; message: string | null };
  runs?: ReconRun[];
  reconciled?: boolean;
};

// ---------------------------------------------------------------------------
// Calls
// ---------------------------------------------------------------------------
const base = "/api/reconciliation";

function get<T>(path: string): Promise<T> {
  return apiFetch(`${base}${path}`).then((r) => parseEnvelopeResponse<T>(r));
}

export const fetchOverview = (period?: string) =>
  get<Overview>(`/overview${period ? `?period=${encodeURIComponent(period)}` : ""}`);

export const fetchBankFields = () => get<BankFieldCatalogue>("/bank/fields");

export const fetchBankPresets = () =>
  get<{ presets: BankPreset[]; caveat: string }>("/bank/presets");

export const fetchProfiles = () => get<{ profiles: BankProfile[] }>("/bank/profiles");

export const fetchBankFiles = (period?: string) =>
  get<{ files: BankFileMeta[] }>(`/bank/files${period ? `?period=${encodeURIComponent(period)}` : ""}`);

export const fetchBankFile = (id: string) =>
  get<BankFileMeta & { rows: BankFileRow[]; truncated: boolean }>(`/bank/files/${id}`);

export const fetchBankReconciliation = (fileId: string) =>
  get<BankReconciliation>(`/bank/reconcile?file_id=${fileId}`);

export const fetchJvOptions = () => get<JvOptions>("/jv/options");

export const fetchJvPresets = () =>
  get<{ presets: JvPreset[]; caveat: string }>("/jv/presets");

export const fetchTemplates = () => get<{ templates: JvTemplate[] }>("/jv/templates");

export const fetchTemplate = (id: string) => get<JvTemplate>(`/jv/templates/${id}`);

export const fetchJvReconciliation = (period: string, templateId?: string) =>
  get<JvReconciliation>(
    `/jv/reconcile?period=${encodeURIComponent(period)}${templateId ? `&template_id=${templateId}` : ""}`,
  );

export const fetchRuns = (period?: string) =>
  get<{ runs: ReconRun[] }>(`/runs${period ? `?period=${encodeURIComponent(period)}` : ""}`);

export const fetchRun = (id: string) => get<ReconRun>(`/runs/${id}`);

export const fetchExceptionKinds = () => get<{ kinds: ExceptionKind[] }>("/exceptions");

export function saveProfile(body: unknown, id?: string) {
  return apiFetch(`${base}/bank/profiles${id ? `/${id}` : ""}`, {
    method: id ? "PUT" : "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then((r) => parseEnvelopeResponse<BankProfile>(r));
}

export function deleteProfile(id: string) {
  return apiFetch(`${base}/bank/profiles/${id}`, { method: "DELETE" }).then((r) =>
    parseEnvelopeResponse<{ deleted: boolean }>(r),
  );
}

export function testProfile(file: File, profile: unknown) {
  const form = new FormData();
  form.append("file", file);
  form.append("profile_json", JSON.stringify(profile));
  return apiFetch(`${base}/bank/profiles/test`, { method: "POST", body: form }).then((r) =>
    parseEnvelopeResponse<ProfileTest>(r),
  );
}

export function suggestMapping(file: File, delimiter = ",") {
  const form = new FormData();
  form.append("file", file);
  form.append("delimiter", delimiter);
  return apiFetch(`${base}/bank/profiles/suggest`, { method: "POST", body: form }).then((r) =>
    parseEnvelopeResponse<MappingSuggestion>(r),
  );
}

export function uploadBankFile(file: File, period: string, profileId: string, note?: string) {
  const form = new FormData();
  form.append("file", file);
  form.append("period", period);
  form.append("profile_id", profileId);
  if (note) form.append("note", note);
  return apiFetch(`${base}/bank/files`, { method: "POST", body: form }).then((r) =>
    parseEnvelopeResponse<BankFileMeta>(r),
  );
}

export function deleteBankFile(id: string) {
  return apiFetch(`${base}/bank/files/${id}`, { method: "DELETE" }).then((r) =>
    parseEnvelopeResponse<{ deleted: boolean }>(r),
  );
}

export function saveTemplate(body: unknown, id?: string) {
  return apiFetch(`${base}/jv/templates${id ? `/${id}` : ""}`, {
    method: id ? "PUT" : "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then((r) => parseEnvelopeResponse<JvTemplate>(r));
}

export function approveTemplate(id: string) {
  return apiFetch(`${base}/jv/templates/${id}/approve`, { method: "POST" }).then((r) =>
    parseEnvelopeResponse<JvTemplate>(r),
  );
}

export function deleteTemplate(id: string) {
  return apiFetch(`${base}/jv/templates/${id}`, { method: "DELETE" }).then((r) =>
    parseEnvelopeResponse<{ deleted: boolean }>(r),
  );
}

export function runReconciliation(body: {
  period_month: string;
  kind: "bank" | "jv";
  bank_file_id?: string;
  jv_template_id?: string;
}) {
  return apiFetch(`${base}/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then((r) => parseEnvelopeResponse<ReconRun>(r));
}

export function closeRun(id: string) {
  return apiFetch(`${base}/runs/${id}/close`, { method: "POST" }).then((r) =>
    parseEnvelopeResponse<ReconRun>(r),
  );
}

// ---------------------------------------------------------------------------
// Presentation
// ---------------------------------------------------------------------------
/**
 * Severity, as a tone.
 *
 * High is danger because money may have moved wrongly. Low is deliberately
 * neutral rather than a softer red: a page where everything is red is a page
 * nobody reads the red on.
 */
export const SEVERITY_TONE: Record<Severity, string> = {
  high: "bg-danger-500/10 text-danger-700 ring-1 ring-danger-500/30 dark:text-danger-300",
  medium: "bg-warning-500/10 text-warning-800 ring-1 ring-warning-500/30 dark:text-warning-200",
  low: "bg-ink-500/10 text-ink-600 ring-1 ring-ink-500/20 dark:text-ink-300",
};

export const SEVERITY_LABEL: Record<Severity, string> = {
  high: "High",
  medium: "Medium",
  low: "Low",
};

/** The current month, as the period pickers here write it. */
export function currentPeriod(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

export function periodKey(iso: string): string {
  return iso.slice(0, 7);
}
