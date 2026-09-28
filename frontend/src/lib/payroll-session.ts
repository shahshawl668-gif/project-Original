import { getActiveEntityId } from "@/lib/api";

const KEYS = [
  "payroll_results",
  "payroll_findings",
  "payroll_findings_summary",
  "payroll_risk_scores",
  "payroll_validate_request",
  "payroll_meta",
] as const;
const ENTITY_KEY = "payroll_results_entity_id";

/** Temporary results are available only to the company that ran validation. */
export function hasCurrentPayrollResults(): boolean {
  if (typeof window === "undefined") return false;
  const active = getActiveEntityId();
  return !!active && sessionStorage.getItem(ENTITY_KEY) === active;
}

export function tagPayrollResultsForCurrentEntity(): void {
  const active = getActiveEntityId();
  if (!active) throw new Error("Select a company before validating payroll.");
  sessionStorage.setItem(ENTITY_KEY, active);
}

export function clearPayrollResults(): void {
  if (typeof window === "undefined") return;
  for (const key of KEYS) sessionStorage.removeItem(key);
  sessionStorage.removeItem(ENTITY_KEY);
}
