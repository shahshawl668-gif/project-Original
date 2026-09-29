/**
 * Company validation rules: the client for /api/validation-matrix.
 *
 * A rule is data the server evaluates — never code. Operands read a field, a
 * component, a deduction, a fixed value, last month's value, the employee
 * master, or a whitelisted arithmetic expression over those.
 */
import { apiFetch, apiJson, parseEnvelopeResponse } from "@/lib/api";

export type Source = "field" | "component" | "deduction" | "literal" | "previous" | "master" | "expr";
export type Operator = "eq" | "ne" | "gt" | "gte" | "lt" | "lte" | "present" | "in" | "not_in";
export type Operand = { source: Source; key?: string; value?: string; of?: "field" | "component" | "deduction" };
export type Comparison = { left: Operand; operator: Operator; right: Operand; tolerance: string };
export type Group = { mode: "all" | "any"; negate: boolean; items: (Comparison | Group)[] };
export type OnMissing = "cannot_validate" | "skip" | "fail";

export const isGroup = (n: Comparison | Group | null | undefined): n is Group =>
  !!n && typeof n === "object" && "items" in n;

export type Rule = {
  id: string; rule_key: string; version: number; name: string; category: "custom" | "statutory";
  status: "draft" | "pending" | "published" | "retired";
  effective_from: string; effective_to: string | null; state: string | null;
  condition: Comparison | Group | null; assertion: Comparison;
  applies_to: Record<string, string[]> | null; on_missing: OnMissing; editor_mode: "basic" | "advanced";
  severity: string; blocks_signoff: boolean; responsible_team: string | null; suggested_fix: string | null;
  source_reference: string | null; change_reason: string; created_by: string;
  approved_at: string | null; cloned_from_id: string | null; retired_at: string | null; retire_reason: string | null;
};

export type Catalog = {
  built_in: { family: string; examples: string[] }[];
  built_in_rules: { rule_id: string; name: string; family: string }[];
  fields: string[]; components: string[]; deductions: string[];
  master_fields: string[]; dimensions: string[]; expression_variables: string[];
  limits: { max_depth: number; max_conditions: number };
};

export type RuleTemplate = {
  key: string; label: string; requires: string[]; available: boolean; missing_components: string[];
  rule: Partial<Rule> & { assertion: Comparison; condition_group?: Group };
};

export type Conflict = {
  kind: "contradiction" | "duplicate" | "broken_reference";
  message: string;
  rules: { id: string; rule_key: string; version: number; status: string }[];
};

export type Impact = {
  period_month: string; employees_evaluated: number; compared_with: Rule | null;
  outcomes: Record<"passed" | "failed" | "cannot_validate" | "skipped" | "out_of_scope", number>;
  would_flag: number; would_be_unverifiable: number; currently_flagged: number;
  newly_flagged: number; no_longer_flagged: number; unchanged: number;
  sample: { employee_id: string; reason: string; actual_value: string; expected_value: string }[];
};

export type ImportPreview = {
  preview: boolean;
  rows?: { row: number; rule_key: string; name: string; status: "new" | "new_version" | "unchanged" | "error"; errors: string[]; changes?: string[]; current_version?: number }[];
  summary: Record<"new" | "new_version" | "unchanged" | "error", number>;
  created?: string[];
};

export type CopyResult = {
  dry_run: boolean;
  targets: { entity_id: string; entity_name: string | null; status: "ok" | "not_available"; rules: { rule_key: string; status: string; reason?: string; version?: number }[] }[];
};

export type RuleDraft = {
  rule_key: string; name: string; category: "custom" | "statutory"; effective_from: string;
  effective_to?: string | null; state?: string | null; conditions?: Comparison[]; condition_mode?: "all" | "any";
  condition_group?: Group | null; assertion: Comparison; applies_to?: Record<string, string[]> | null;
  on_missing: OnMissing; editor_mode: "basic" | "advanced"; severity: string; blocks_signoff: boolean;
  suggested_fix?: string | null; source_reference?: string | null; change_reason: string;
};

const post = <T,>(path: string, body?: unknown) =>
  apiJson<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const matrixApi = {
  catalog: () => apiJson<Catalog>("/api/validation-matrix/catalog"),
  templates: () => apiJson<RuleTemplate[]>("/api/validation-matrix/templates"),
  rules: () => apiJson<Rule[]>("/api/validation-matrix"),
  conflicts: () => apiJson<Conflict[]>("/api/validation-matrix/conflicts"),
  create: (body: RuleDraft) => post<Rule>("/api/validation-matrix", body),
  act: (id: string, verb: "submit" | "publish") => post<Rule>(`/api/validation-matrix/${id}/${verb}`),
  returnToDraft: (id: string, reason: string) => post<Rule>(`/api/validation-matrix/${id}/return`, { reason }),
  clone: (id: string, change_reason: string, rule_key?: string) =>
    post<Rule>(`/api/validation-matrix/${id}/clone`, { change_reason, rule_key: rule_key || undefined }),
  rollback: (id: string, reason: string) => post<Rule>(`/api/validation-matrix/${id}/rollback`, { reason }),
  retire: (id: string, effective_to: string, reason: string) =>
    post<Rule>(`/api/validation-matrix/${id}/retire`, { effective_to, reason }),
  impact: (id: string, period_month: string) => post<Impact>(`/api/validation-matrix/${id}/impact`, { period_month }),
  compare: (a: string, b: string) =>
    apiJson<{ a: Rule; b: Rule; changes: { field: string; a: unknown; b: unknown }[] }>(
      `/api/validation-matrix/compare?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`),
  importFile: async (file: File, dryRun: boolean) => {
    const form = new FormData();
    form.append("file", file);
    return parseEnvelopeResponse<ImportPreview>(
      await apiFetch(`/api/validation-matrix/import?dry_run=${dryRun}`, { method: "POST", body: form }),
    );
  },
  copy: (body: { rule_ids: string[]; target_entity_ids: string[]; change_reason: string; dry_run: boolean }) =>
    post<CopyResult>("/api/validation-matrix/copy", body),
};

export const OPERATOR_LABEL: Record<Operator, string> = {
  eq: "Equals", ne: "Does not equal", gt: "Greater than", gte: "At least", lt: "Less than", lte: "At most",
  present: "Has a value", in: "In approved list", not_in: "Outside list",
};

export const ON_MISSING_LABEL: Record<OnMissing, string> = {
  cannot_validate: "Report “cannot validate” (recommended)",
  skip: "Skip the employee — no finding",
  fail: "Treat as a failure",
};

/** A one-line reading of a comparison, for lists and diffs. */
export function describeOperand(o: Operand): string {
  switch (o.source) {
    case "literal": return `“${o.value ?? ""}”`;
    case "expr": return `(${o.value ?? ""})`;
    case "previous": return `last month's ${o.key}`;
    case "master": return `master ${o.key}`;
    default: return (o.key ?? "").replaceAll("_", " ");
  }
}

export function describeComparison(c: Comparison): string {
  if (c.operator === "present") return `${describeOperand(c.left)} has a value`;
  const tol = c.tolerance && c.tolerance !== "0" ? ` (±${c.tolerance})` : "";
  return `${describeOperand(c.left)} ${OPERATOR_LABEL[c.operator].toLowerCase()} ${describeOperand(c.right)}${tol}`;
}

export function describeCondition(n: Comparison | Group | null): string {
  if (!n) return "always";
  if (!isGroup(n)) return describeComparison(n);
  const inner = n.items.map((i) => (isGroup(i) ? `(${describeCondition(i)})` : describeComparison(i)))
    .join(n.mode === "all" ? " AND " : " OR ");
  return n.negate ? `NOT (${inner})` : inner;
}
