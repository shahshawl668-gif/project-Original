/**
 * API helpers for the Config-Driven Statutory Engine.
 */
import { apiFetch } from "./api";

export interface PFRateConfig {
  employee_rate: string;
  employer_rate: string;
  eps_rate: string;
  edli_rate: string;
  admin_rate: string;
}

export interface PFWageConfig {
  use_pf_applicable_flag: boolean;
  include_components: string[];
  exclude_components: string[];
  wage_ceiling: string;
  restrict_to_ceiling: boolean;
}

export interface PFEligibilityConfig {
  expression: string;
  exempt_employment_types: string[];
}

export interface VoluntaryPFConfig {
  enabled: boolean;
  components: string[];
}

export interface PFConfig {
  rates: PFRateConfig;
  wage: PFWageConfig;
  eligibility: PFEligibilityConfig;
  voluntary: VoluntaryPFConfig;
  above_ceiling_mode: "none" | "employee_choice" | "employer_choice";
}

export interface ESICRateConfig {
  employee_rate: string;
  employer_rate: string;
}

export interface ESICWageConfig {
  use_esic_applicable_flag: boolean;
  include_components: string[];
  exclude_components: string[];
  wage_ceiling: string;
}

export interface ESICRoundingConfig {
  mode: "up" | "down" | "nearest";
  expression: string;
}

export interface ESICEligibilityConfig {
  expression: string;
  exempt_employment_types: string[];
  full_month_on_entry: boolean;
  continue_month_on_exit: boolean;
}

export interface ESICConfig {
  rates: ESICRateConfig;
  wage: ESICWageConfig;
  rounding: ESICRoundingConfig;
  eligibility: ESICEligibilityConfig;
}

export interface ComponentMappingEntry {
  upload_column: string;
  component_name: string;
  pf_applicable: boolean;
  esic_applicable: boolean;
  included_in_wages: boolean;
  taxable: boolean;
}

export interface ComponentMappingConfig {
  entries: ComponentMappingEntry[];
  ignore_columns: string[];
}

export interface TenantStatutoryConfig {
  pf: PFConfig;
  esic: ESICConfig;
  component_mapping: ComponentMappingConfig;
}

export interface StatutoryConfigResponse extends TenantStatutoryConfig {
  tenant_id: string;
  updated_at: string | null;
}

export interface ConfigSummary {
  pf: Record<string, string | boolean>;
  esic: Record<string, string | boolean>;
}

// ── Defaults ──────────────────────────────────────────────────────────────────

export const defaultPFConfig: PFConfig = {
  rates: {
    employee_rate: "0.12",
    employer_rate: "0.12",
    eps_rate: "0.0833",
    edli_rate: "0.005",
    admin_rate: "0.005",
  },
  wage: {
    use_pf_applicable_flag: true,
    include_components: [],
    exclude_components: [],
    wage_ceiling: "15000",
    restrict_to_ceiling: true,
  },
  eligibility: {
    expression: "pf_wage > 0",
    exempt_employment_types: [],
  },
  voluntary: {
    enabled: false,
    components: [],
  },
  above_ceiling_mode: "none",
};

export const defaultESICConfig: ESICConfig = {
  rates: {
    employee_rate: "0.0075",
    employer_rate: "0.0325",
  },
  wage: {
    use_esic_applicable_flag: true,
    include_components: [],
    exclude_components: [],
    wage_ceiling: "21000",
  },
  rounding: {
    mode: "up",
    expression: "",
  },
  eligibility: {
    expression: "esic_wage > 0 and esic_wage <= esic_ceiling",
    exempt_employment_types: [],
    full_month_on_entry: true,
    continue_month_on_exit: true,
  },
};

// ── API ───────────────────────────────────────────────────────────────────────

export async function getStatutoryConfig(): Promise<StatutoryConfigResponse> {
  const r = await apiFetch("/api/config/statutory");
  if (!r.ok) throw new Error("Failed to load statutory config");
  return r.json();
}

export async function saveStatutoryConfig(cfg: TenantStatutoryConfig): Promise<StatutoryConfigResponse> {
  const r = await apiFetch("/api/config/statutory", {
    method: "PUT",
    body: JSON.stringify(cfg),
  });
  if (!r.ok) throw new Error("Failed to save statutory config");
  return r.json();
}

export async function resetStatutoryConfig(): Promise<StatutoryConfigResponse> {
  const r = await apiFetch("/api/config/statutory/reset", { method: "POST" });
  if (!r.ok) throw new Error("Failed to reset config");
  return r.json();
}

export async function getConfigSummary(): Promise<ConfigSummary> {
  const r = await apiFetch("/api/config/statutory/summary");
  if (!r.ok) throw new Error("Failed to load config summary");
  return r.json();
}

export async function testExpression(
  expression: string,
  context: Record<string, unknown>,
): Promise<{ result: unknown; result_type: string; ok: boolean; error?: string }> {
  const r = await apiFetch("/api/config/statutory/test-expression", {
    method: "POST",
    body: JSON.stringify({ expression, context }),
  });
  return r.json();
}
