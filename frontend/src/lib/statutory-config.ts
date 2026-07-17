/**
 * API helpers for the Config-Driven Statutory Engine.
 */
import { apiJson } from "./api";

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
  return apiJson<StatutoryConfigResponse>("/api/config/statutory");
}

export async function saveStatutoryConfig(cfg: TenantStatutoryConfig): Promise<StatutoryConfigResponse> {
  return apiJson<StatutoryConfigResponse>("/api/config/statutory", {
    method: "PUT",
    body: JSON.stringify(cfg),
  });
}

export async function resetStatutoryConfig(): Promise<StatutoryConfigResponse> {
  return apiJson<StatutoryConfigResponse>("/api/config/statutory/reset", { method: "POST" });
}

export async function getConfigSummary(): Promise<ConfigSummary> {
  return apiJson<ConfigSummary>("/api/config/statutory/summary");
}

export async function testExpression(
  expression: string,
  context: Record<string, unknown>,
): Promise<{ result?: unknown; result_type?: string; eval_ok: boolean; error?: string }> {
  return apiJson("/api/config/statutory/test-expression", {
    method: "POST",
    body: JSON.stringify({ expression, context }),
  });
}

// ── Income tax (FY-versioned) ────────────────────────────────────────────────

export interface TaxSlab {
  up_to: string | null; // null = no upper bound
  rate: string;
}

export interface RebateConfig {
  taxable_income_limit: string;
  max_rebate: string;
  marginal_relief: boolean;
}

export interface SurchargeBracket {
  up_to: string | null;
  rate: string;
}

export interface RegimeConfig {
  label: string;
  slabs: TaxSlab[];
  standard_deduction: string;
  rebate: RebateConfig;
  surcharge_brackets: SurchargeBracket[];
  allow_chapter_via: boolean;
}

export interface DeductionCapsConfig {
  section_80c: string;
  section_80d: string;
  section_80ccd_1b: string;
  home_loan_interest: string;
}

export interface TaxYearConfig {
  financial_year: string;
  cess_rate: string;
  old_regime: RegimeConfig;
  new_regime: RegimeConfig;
  deduction_caps: DeductionCapsConfig;
  notes: string;
}

export interface IncomeTaxConfig {
  default_year: string;
  years: Record<string, TaxYearConfig>;
}

export async function getIncomeTaxConfig(): Promise<IncomeTaxConfig> {
  return apiJson<IncomeTaxConfig>("/api/config/statutory/income-tax");
}

export async function saveIncomeTaxConfig(cfg: IncomeTaxConfig): Promise<IncomeTaxConfig> {
  return apiJson<IncomeTaxConfig>("/api/config/statutory/income-tax", {
    method: "PUT",
    body: JSON.stringify(cfg),
  });
}

export async function upsertTaxYear(
  financialYear: string,
  year: TaxYearConfig,
  makeDefault = false,
): Promise<IncomeTaxConfig> {
  return apiJson<IncomeTaxConfig>(`/api/config/statutory/income-tax/years/${financialYear}`, {
    method: "PUT",
    body: JSON.stringify({ year, make_default: makeDefault }),
  });
}

export async function deleteTaxYear(financialYear: string): Promise<IncomeTaxConfig> {
  return apiJson<IncomeTaxConfig>(`/api/config/statutory/income-tax/years/${financialYear}`, {
    method: "DELETE",
  });
}

export async function resetIncomeTaxConfig(): Promise<IncomeTaxConfig> {
  return apiJson<IncomeTaxConfig>("/api/config/statutory/income-tax/reset", { method: "POST" });
}

export interface TaxBreakup {
  regime: "old" | "new";
  financial_year: string;
  annual_gross: number;
  standard_deduction: number;
  chapter_via: number;
  taxable_income: number;
  slab_tax: number;
  rebate_87a: number;
  surcharge: number;
  cess: number;
  total_tax_annual: number;
  monthly_tds: number;
  notes: string[];
}

export interface RegimeComparison {
  old: TaxBreakup;
  new: TaxBreakup;
  cheaper_regime: "old" | "new";
  annual_saving: number;
  financial_year: string;
}

export async function compareRegimes(
  annualGross: number,
  financialYear?: string,
): Promise<RegimeComparison> {
  return apiJson<RegimeComparison>("/api/income-tax/compare", {
    method: "POST",
    body: JSON.stringify({ annual_gross: annualGross, financial_year: financialYear ?? null }),
  });
}

// ── Rule-engine thresholds ───────────────────────────────────────────────────

export interface RuleThresholdsConfig {
  structural: {
    min_pf_wage_pct_of_gross: string;
    recommended_pf_wage_pct: string;
    allowance_heavy_pct: string;
  };
  tolerances: {
    gross_mismatch: string;
    net_mismatch: string;
    statutory_mismatch: string;
  };
  trends: {
    component_change_pct: string;
    salary_spike_ratio: string;
    salary_drop_ratio: string;
  };
  tds: {
    annual_income_threshold: string;
    arrear_annualisation_factor: string;
  };
  gratuity: {
    exemption_cap: string;
  };
  identity: Record<string, string>;
  pf_deep: Record<string, string>;
  esi_deep: Record<string, string>;
  pt_caps: { annual_cap: string; no_pt_states: string[] };
  bonus: Record<string, string>;
  gratuity_formula: Record<string, string>;
  tds_deep: Record<string, string>;
}

export async function getRuleThresholds(): Promise<RuleThresholdsConfig> {
  return apiJson<RuleThresholdsConfig>("/api/config/statutory/rule-thresholds");
}

export async function saveRuleThresholds(cfg: RuleThresholdsConfig): Promise<RuleThresholdsConfig> {
  return apiJson<RuleThresholdsConfig>("/api/config/statutory/rule-thresholds", {
    method: "PUT",
    body: JSON.stringify(cfg),
  });
}

export async function resetRuleThresholds(): Promise<RuleThresholdsConfig> {
  return apiJson<RuleThresholdsConfig>("/api/config/statutory/rule-thresholds/reset", {
    method: "POST",
  });
}
