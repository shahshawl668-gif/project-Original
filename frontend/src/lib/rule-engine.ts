import { apiJson } from "@/lib/api";

export type FormulaRuleType = "PF" | "ESIC";
export type SlabRuleType = "PT" | "LWF";
export type Frequency = "monthly" | "yearly" | "half-yearly" | "quarterly";
export type ConditionOperator = ">" | "<" | ">=" | "<=" | "==" | "!=";

export type Condition = {
  field: string;
  operator: ConditionOperator;
  value: number;
};

export type Formula = {
  id: string;
  rule_type: FormulaRuleType;
  name: string | null;
  expression: string;
  conditions: Condition[];
  version: number;
  is_active: boolean;
  created_at: string;
};

export type Gender = "ALL" | "MALE" | "FEMALE";

export type SlabRow = {
  id?: string;
  min_salary: number | string;
  max_salary: number | string;
  // PT: employee deduction.   LWF: employee contribution per period.
  deduction_amount: number | string;
  // LWF only: employer contribution per period. NULL/0 for PT rows.
  employer_amount: number | string | null;
  frequency: Frequency;
  gender: Gender;
  applicable_months: number[] | null;
};

export type SlabsResponse = {
  state: string;
  rule_type: SlabRuleType;
  slabs: (SlabRow & { id: string })[];
};

export async function getFormulas(rule_type?: FormulaRuleType): Promise<Formula[]> {
  const qs = rule_type ? `?rule_type=${rule_type}` : "";
  return apiJson<Formula[]>(`/api/rule-engine/formulas${qs}`);
}

export async function createFormula(payload: {
  rule_type: FormulaRuleType;
  name?: string | null;
  expression: string;
  conditions: Condition[];
  activate?: boolean;
}): Promise<Formula> {
  return apiJson<Formula>("/api/rule-engine/formula", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function activateFormula(id: string): Promise<Formula> {
  return apiJson<Formula>(`/api/rule-engine/formula/${id}/activate`, { method: "POST" });
}

export async function deleteFormula(id: string): Promise<void> {
  await apiJson<{ deleted: string }>(`/api/rule-engine/formula/${id}`, { method: "DELETE" });
}

export type TestFormulaResult = {
  ok: boolean;
  result: number | null;
  conditions_passed: boolean | null;
  error: string | null;
};

export async function testFormula(payload: {
  expression: string;
  conditions: Condition[];
  variables: Record<string, number>;
}): Promise<TestFormulaResult> {
  return apiJson<TestFormulaResult>("/api/rule-engine/test-formula", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getSlabs(state: string, rule_type: SlabRuleType): Promise<SlabsResponse> {
  return apiJson<SlabsResponse>(
    `/api/rule-engine/slabs?state=${encodeURIComponent(state)}&rule_type=${rule_type}`
  );
}

export async function saveSlabs(payload: {
  state: string;
  rule_type: SlabRuleType;
  slabs: SlabRow[];
}): Promise<SlabsResponse> {
  return apiJson<SlabsResponse>("/api/rule-engine/slabs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getReferenceStates(): Promise<{
  pt_states: string[];
  lwf_states: string[];
  all_states: string[];
}> {
  return apiJson("/api/reference/states");
}

export async function listPtDefaultStates(): Promise<{ states: string[] }> {
  return apiJson("/api/rule-engine/defaults/pt-states");
}

export async function listLwfDefaultStates(): Promise<{ states: string[] }> {
  return apiJson("/api/rule-engine/defaults/lwf-states");
}

export async function listDefaultStates(): Promise<{ PT: string[]; LWF: string[] }> {
  return apiJson("/api/rule-engine/defaults/states");
}

export async function importDefaultSlabs(
  state: string,
  rule_type: SlabRuleType = "PT",
  overwrite = true
): Promise<SlabsResponse> {
  return apiJson<SlabsResponse>(
    `/api/rule-engine/slabs/import-defaults?state=${encodeURIComponent(
      state
    )}&rule_type=${rule_type}&overwrite=${overwrite}`,
    { method: "POST" }
  );
}

export async function importAllDefaultSlabs(
  rule_type: SlabRuleType = "PT",
  overwrite = false
): Promise<{
  rule_type: SlabRuleType;
  imported: Record<string, number>;
  total_states: number;
}> {
  return apiJson(
    `/api/rule-engine/slabs/import-defaults/all?rule_type=${rule_type}&overwrite=${overwrite}`,
    { method: "POST" }
  );
}

export async function resetDefaultSlabs(rule_type: SlabRuleType = "PT"): Promise<{
  rule_type: SlabRuleType;
  deleted_rows: number;
  imported: Record<string, number>;
  total_states: number;
}> {
  return apiJson(`/api/rule-engine/slabs/reset-defaults?rule_type=${rule_type}`, {
    method: "POST",
  });
}
