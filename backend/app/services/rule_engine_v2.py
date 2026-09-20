"""
India Payroll Intelligence & Compliance OS — Rule Engine v2
===========================================================
Named rules across multiple priority layers (PF, ESIC, PT, LWF, compliance).

Every finding exposes:
  rule_id          – e.g. "STAT-001"
  rule_name        – human label
  component        – affected column / concept
  expected_value   – what the engine computed
  actual_value     – what the register contains
  difference       – actual − expected (or %)
  severity         – CRITICAL | WARNING | INFO
  status           – FAIL | PASS
  reason           – plain-English explanation
  suggested_fix    – actionable remediation step
  financial_impact – estimated ₹ impact of this finding (0 when N/A)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.schemas.rule_thresholds import RuleThresholdsConfig
from app.services import identity_checks as idc

CENT = Decimal("0.01")
HALF_UP = __import__("decimal").ROUND_HALF_UP


# ── helpers ──────────────────────────────────────────────────────────────────

def _dec(v: Any) -> Decimal:
    if v is None or v == "":
        return Decimal("0")
    try:
        return Decimal(str(v))
    except Exception:
        return Decimal("0")


def _q(v: Decimal) -> Decimal:
    return v.quantize(CENT, rounding=HALF_UP)


def _fmt(v: Any) -> str:
    if isinstance(v, Decimal):
        return str(_q(v))
    if isinstance(v, float):
        return f"{v:.2f}"
    if v is None:
        return ""
    return str(v)


_RESERVED_COLS = {
    "employee_id", "emp_id", "employee_code", "employee_name", "name",
    "location", "location_state", "state", "state_pt", "state_lwf",
    "work_state", "employment_type", "department", "designation",
    "gender", "sex", "paid_days", "lop_days", "lop", "total_days",
    "month_days", "days_in_month", "gross", "gross_salary", "gross_pay",
    "total_gross", "net", "net_salary", "net_pay", "take_home",
    "pf_employee", "pf_employer", "pf_emp", "pf_employer_total",
    "esic_employee", "esic_employer", "pt", "pt_amount",
    "lwf_employee", "lwf_employer", "bonus", "gratuity",
    "tds", "income_tax", "risk_score",
    # identity / master-data columns (spec §1-2)
    "pan", "aadhaar", "aadhar", "uan", "esi_number", "esi_no", "ip_number",
    "bank_account", "account_number", "ifsc", "ifsc_code",
    "dob", "date_of_birth", "doj", "date_of_joining", "dol", "date_of_leaving",
    "tax_regime", "regime", "disability", "international_worker",
    "adolescent_permit", "death_or_disablement",
}

# ── data class ───────────────────────────────────────────────────────────────

@dataclass
class ValidationFinding:
    employee_id: str
    employee_name: str | None
    rule_id: str
    rule_name: str
    component: str
    expected_value: str
    actual_value: str
    difference: str
    severity: str           # CRITICAL | WARNING | INFO
    status: str             # FAIL | PASS
    reason: str
    suggested_fix: str = field(default="")
    financial_impact: float = field(default=0.0)

    @property
    def category(self) -> str:
        """missing | mismatch | issue — see services/finding_taxonomy.py."""
        from app.services.finding_taxonomy import categorise

        return categorise(self.rule_id, self.actual_value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "employee_id": self.employee_id,
            "employee_name": self.employee_name or "",
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "component": self.component,
            "expected_value": self.expected_value,
            "actual_value": self.actual_value,
            "difference": self.difference,
            "severity": self.severity,
            "status": self.status,
            "reason": self.reason,
            "suggested_fix": self.suggested_fix,
            "financial_impact": self.financial_impact,
        }


# ── main builder ─────────────────────────────────────────────────────────────

def _alternate_basis_match(
    actual: Decimal,
    pf_calc: dict[str, Any],
    rate_pct: float,
    tolerance: Decimal,
) -> tuple[str, str] | None:
    """
    Does ``actual`` equal PF computed on the opposite restriction basis?

    Returns (basis_used, basis_configured) when it does, else None. Only the
    two bases are compared — an amount that matches neither is an ordinary
    miscalculation and is reported as one.
    """
    full_wage = _dec(pf_calc.get("_pf_wage_full", pf_calc.get("pf_wage_capped", 0)))
    ceiling = _dec(pf_calc.get("_ceiling", 0))
    if full_wage <= 0 or ceiling <= 0 or full_wage <= ceiling:
        return None  # below the ceiling the two bases give the same answer

    rate = Decimal(str(rate_pct)) / Decimal("100")
    restricted_amt = _q(ceiling * rate)
    unrestricted_amt = _q(full_wage * rate)

    restricted_now = bool(pf_calc.get("_restrict", True))
    if restricted_now and (actual - unrestricted_amt).copy_abs() <= tolerance:
        return ("unrestricted (full wage)", "restricted to the ceiling")
    if not restricted_now and (actual - restricted_amt).copy_abs() <= tolerance:
        return ("restricted to the ceiling", "unrestricted (full wage)")
    return None


def build_findings(
    employee_id: str,
    employee_name: str | None,
    row: dict[str, Any],
    comp_by_key: dict[str, Any],
    regular: dict[str, Decimal],
    arrear_by_base: dict[str, Decimal],
    inc_arrear_total: Decimal,
    paid_days: Decimal | None,
    lop_days: Decimal | None,
    days_in_month: int,
    pf_calc: dict[str, Any],
    esic_calc: dict[str, Any],
    pt_due: Decimal,
    lwf_eamt: Decimal,
    lwf_oamt: Decimal,
    prior_components: dict[str, float] | None,
    prior_is_joiner: bool,
    lop_diffs: list[dict[str, Any]],
    inc_info: dict[str, Any],
    tds_risk: list[str],
    thresholds: RuleThresholdsConfig | None = None,
    period_month: Any = None,
    expected_monthly_tds: float | None = None,
    composition: Any = None,
) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []

    # Tenant-tunable rule thresholds (see /api/config/rule-thresholds)
    t = thresholds or RuleThresholdsConfig()
    tol_gross = t.tolerances.gross_mismatch
    tol_net = t.tolerances.net_mismatch
    tol_stat = t.tolerances.statutory_mismatch

    # Tenant-aware statutory thresholds (from compute_pf / compute_esic)
    pf_ceiling_cfg = _dec(pf_calc.get("_ceiling", 15000))
    esic_ceiling_cfg = _dec(esic_calc.get("_ceiling", 21000))
    pf_emp_rate = _dec(pf_calc.get("_emp_rate", 0.12))
    pf_emp_rate_pct = float(pf_emp_rate) * 100
    esic_emp_rate_pct = float(esic_calc.get("_emp_rate", 0.0075)) * 100
    esic_er_rate_pct = float(esic_calc.get("_er_rate", 0.0325)) * 100

    # ── inner helpers ─────────────────────────────────────────────────────────

    def fail(rule_id, rule_name, component, expected, actual,
             severity, reason, fix="", impact=0.0):
        try:
            diff = _fmt(_q(_dec(actual) - _dec(expected)))
        except Exception:
            diff = ""
        findings.append(ValidationFinding(
            employee_id=employee_id, employee_name=employee_name,
            rule_id=rule_id, rule_name=rule_name, component=component,
            expected_value=_fmt(expected), actual_value=_fmt(actual),
            difference=diff, severity=severity, status="FAIL",
            reason=reason, suggested_fix=fix, financial_impact=impact,
        ))

    def pass_(rule_id, rule_name, component, value, reason=""):
        findings.append(ValidationFinding(
            employee_id=employee_id, employee_name=employee_name,
            rule_id=rule_id, rule_name=rule_name, component=component,
            expected_value=_fmt(value), actual_value=_fmt(value),
            difference="0.00", severity="INFO", status="PASS",
            reason=reason, suggested_fix="", financial_impact=0.0,
        ))

    def info(rule_id, rule_name, component, expected, actual, reason, fix=""):
        findings.append(ValidationFinding(
            employee_id=employee_id, employee_name=employee_name,
            rule_id=rule_id, rule_name=rule_name, component=component,
            expected_value=expected, actual_value=actual,
            difference="", severity="INFO", status="FAIL",
            reason=reason, suggested_fix=fix, financial_impact=0.0,
        ))

    # ═══════════════════════════════════════════════════════════════════
    # P1 – DATA VALIDATION
    # ═══════════════════════════════════════════════════════════════════

    if not employee_id or employee_id == "UNKNOWN":
        fail("DATA-001", "Missing Employee ID", "employee_id",
             "Non-empty ID", "(blank)", "CRITICAL",
             "Employee ID is blank — this row cannot be matched to CTC, prior-month, or deduplicated.",
             "Ensure every row has a unique non-blank employee_id / emp_id / employee_code.")

    for key, val in regular.items():
        comp = comp_by_key.get(key)
        if comp and comp.included_in_wages and val < Decimal("0"):
            fail("DATA-003", "Negative Earning Component", key,
                 "≥ 0", _fmt(val), "CRITICAL",
                 f"Earning component '{key}' is negative ({_fmt(val)}). "
                 "Negative earnings in a regular run are invalid.",
                 f"Remove {key} from this run. Use a reversal/arrear run type for corrections.",
                 float(val.copy_abs()))

    if comp_by_key and not any(v > 0 for v in regular.values()):
        fail("DATA-004", "All Components Are Zero", "gross",
             "> 0", "0.00", "WARNING",
             "All salary components are zero. Possible no-pay, hold, or upload error.",
             "Verify attendance data. If employee is on LWP, mark as intentional.")

    # ═══════════════════════════════════════════════════════════════════
    # P2 – COMPONENT STRUCTURE
    # ═══════════════════════════════════════════════════════════════════

    for col in row:
        if col is None:
            continue
        col_s = str(col).strip().lower().replace(" ", "_")
        if col_s in _RESERVED_COLS or col_s.startswith("_"):
            continue
        is_arrear = col_s.endswith("_arrear") or ("increment" in col_s and "arrear" in col_s)
        if col_s not in comp_by_key and not is_arrear:
            info("COMP-001", "Unmapped Column in Register", col_s,
                 "mapped to a component", "not found in config",
                 f"Column '{col_s}' is not configured as a salary component and is excluded from all calculations.",
                 f"Go to Salary Components → Add '{col_s}' with correct flags (PF/ESIC/gross applicable).")

    for key, comp in comp_by_key.items():
        # Skip arrear components: detected by DB flag (if present) or naming convention
        if getattr(comp, "is_arrear", False) or "arrear" in key.lower():
            continue
        if comp.pf_applicable and key not in regular:
            info("COMP-002", "PF Component Missing from Register", key,
                 "present", "absent",
                 f"'{key}' is PF-applicable but absent from this row — PF wage is understated.",
                 f"Ensure '{key}' column is present in the uploaded file or map it using an alias.")

    # ═══════════════════════════════════════════════════════════════════
    # P2b – SALARY STRUCTURE ANALYSIS (PF Avoidance Detection)
    # ═══════════════════════════════════════════════════════════════════

    pf_wage_total = sum(
        (amt for k, amt in regular.items() if comp_by_key.get(k) and comp_by_key[k].pf_applicable),
        start=Decimal("0"),
    )
    calc_gross = sum(
        (amt for k, amt in regular.items() if comp_by_key.get(k) and comp_by_key[k].included_in_wages),
        start=Decimal("0"),
    )

    min_pf_pct = t.structural.min_pf_wage_pct_of_gross
    rec_pf_frac = t.structural.recommended_pf_wage_pct / Decimal("100")
    if calc_gross > Decimal("0") and pf_wage_total > Decimal("0"):
        basic_pct = float(pf_wage_total / calc_gross) * 100
        if basic_pct < float(min_pf_pct):
            fail("STRUCT-001", "Low PF Wage — Possible PF Avoidance", "pf_wage",
                 f"≥ {min_pf_pct}% of gross ({_fmt(_q(calc_gross * min_pf_pct / Decimal('100')))})",
                 _fmt(pf_wage_total),
                 "WARNING",
                 f"PF wage ({_fmt(pf_wage_total)}) is only {basic_pct:.1f}% of gross ({_fmt(calc_gross)}). "
                 f"Structures where Basic < {min_pf_pct}% of CTC are flagged by PF authorities as avoidance.",
                 f"Restructure Basic to be ≥ {t.structural.recommended_pf_wage_pct}-50% of CTC. "
                 "Consult CA before changing.",
                 float(_q((calc_gross * rec_pf_frac - pf_wage_total) * pf_emp_rate)))

    # Allowance-heavy structure
    allow_heavy_pct = t.structural.allowance_heavy_pct
    if calc_gross > Decimal("0") and pf_wage_total > Decimal("0"):
        allowances = calc_gross - pf_wage_total
        allow_pct = float(allowances / calc_gross) * 100
        if allow_pct > float(allow_heavy_pct):
            fail("STRUCT-002", "Allowance-Heavy Salary Structure", "allowances",
                 f"≤ {allow_heavy_pct}% of gross in allowances", f"{allow_pct:.1f}% of gross",
                 "WARNING",
                 f"Non-PF allowances are {allow_pct:.1f}% of gross. "
                 "High allowance structures attract scrutiny under PF Act and Income Tax.",
                 f"Balance the CTC mix: target Basic ≥ {t.structural.recommended_pf_wage_pct}%, "
                 "HRA ≤ 50% of Basic, allowances ≤ 30%.")

    # ═══════════════════════════════════════════════════════════════════
    # P3 – AGGREGATION
    # ═══════════════════════════════════════════════════════════════════

    for gk in ("gross", "gross_salary", "gross_pay", "total_gross"):
        reg_val = row.get(gk)
        if reg_val not in (None, ""):
            actual_gross = _dec(reg_val)
            delta = (actual_gross - calc_gross).copy_abs()
            if delta > tol_gross:
                fail("AGG-001", "Gross Pay Mismatch", "gross",
                     calc_gross, actual_gross, "CRITICAL",
                     f"Gross in register ({_fmt(actual_gross)}) ≠ sum of earnings ({_fmt(calc_gross)}). "
                     f"Difference: {_fmt(actual_gross - calc_gross)}.",
                     "Audit each earning component flag. Ensure all earnings are tagged 'Included in Wages'.",
                     float(delta))
            else:
                pass_("AGG-001", "Gross Pay", "gross", actual_gross)
            break

    total_deductions = (
        _dec(pf_calc.get("pf_employee", 0))
        + _dec(esic_calc.get("esic_employee", 0))
        + pt_due + lwf_eamt
    )
    calc_net = calc_gross - total_deductions
    for nk in ("net", "net_salary", "net_pay", "take_home"):
        reg_val = row.get(nk)
        if reg_val not in (None, ""):
            actual_net = _dec(reg_val)
            delta = (actual_net - calc_net).copy_abs()
            if delta > tol_net:
                fail("AGG-002", "Net Pay Mismatch", "net",
                     calc_net, actual_net, "CRITICAL",
                     f"Net in register ({_fmt(actual_net)}) ≠ Gross − Statutory ({_fmt(calc_net)}). "
                     f"Unexplained difference: {_fmt(actual_net - calc_net)}.",
                     "Check for loan/advance or non-statutory deductions not in config.",
                     float(delta))
            else:
                pass_("AGG-002", "Net Pay", "net", actual_net)
            break

    # ═══════════════════════════════════════════════════════════════════
    # P4 – STATUTORY COMPLIANCE
    # ═══════════════════════════════════════════════════════════════════

    # ── PF ───────────────────────────────────────────────────────────
    pf_emp_exp = _q(_dec(pf_calc.get("pf_employee", 0)))
    pf_er_exp  = _q(_dec(pf_calc.get("pf_employer_total", 0)))
    pf_capped  = _dec(pf_calc.get("pf_wage_capped", 0))

    pf_emp_raw = row.get("pf_employee") or row.get("pf_emp")
    if pf_emp_raw not in (None, ""):
        pf_emp_actual = _dec(pf_emp_raw)
        diff_pf = (pf_emp_actual - pf_emp_exp).copy_abs()
        if diff_pf > tol_stat:
            # Before calling it a miscalculation, check whether the figure is
            # simply the *other* restriction basis computed correctly. That
            # turns "PF is wrong by ₹1,438" into "PF was computed unrestricted
            # but this employee is on the restricted basis" — a different
            # problem with a different fix, and the one that actually recurs.
            alt = _alternate_basis_match(pf_emp_actual, pf_calc, pf_emp_rate_pct, tol_stat)
            if alt is not None:
                used, should_be = alt
                fail("PF-009", "PF Restriction Basis Mismatch", "pf_employee",
                     pf_emp_exp, pf_emp_actual, "CRITICAL",
                     f"PF employee ({_fmt(pf_emp_actual)}) matches the {used} basis, but this "
                     f"employee is set to {should_be} "
                     f"(source: {pf_calc.get('_basis_source', 'entity default')}).",
                     f"Either correct the deduction to ₹{_fmt(pf_emp_exp)}, or change this "
                     f"employee's PF basis to {used} if that is the agreed position.",
                     float(diff_pf))
            else:
                fail("STAT-001", "PF Employee Contribution Mismatch", "pf_employee",
                     pf_emp_exp, pf_emp_actual, "CRITICAL",
                     f"PF employee ({_fmt(pf_emp_actual)}) ≠ computed ({_fmt(pf_emp_exp)}) "
                     f"[PF wage {_fmt(pf_capped)} × {pf_emp_rate_pct:.2f}%]. PF type: {pf_calc.get('pf_type','?')}.",
                     f"Correct pf_employee to ₹{_fmt(pf_emp_exp)}. Verify PF wage = {_fmt(pf_capped)}.",
                     float(diff_pf))
        else:
            pass_("STAT-001", "PF Employee Contribution", "pf_employee", pf_emp_actual)
    elif pf_emp_exp > Decimal("0"):
        info("STAT-001", "PF Employee Column Absent", "pf_employee",
             _fmt(pf_emp_exp), "(missing)",
             "Register has no pf_employee column — PF deduction cannot be verified.",
             "Add 'pf_employee' column to your salary register template.")

    pf_er_raw = row.get("pf_employer") or row.get("pf_employer_total")
    if pf_er_raw not in (None, ""):
        pf_er_actual = _dec(pf_er_raw)
        diff_er = (pf_er_actual - pf_er_exp).copy_abs()
        if diff_er > tol_stat:
            fail("STAT-002", "PF Employer Contribution Mismatch", "pf_employer",
                 pf_er_exp, pf_er_actual, "CRITICAL",
                 f"PF employer ({_fmt(pf_er_actual)}) ≠ expected ({_fmt(pf_er_exp)}). "
                 "Verify EPF/EPS/EDLI split.",
                 f"Recompute: EPF = Employer total − EPS (8.33% of {_fmt(pf_capped)}).",
                 float(diff_er))
        else:
            pass_("STAT-002", "PF Employer Contribution", "pf_employer", pf_er_actual)

    if pf_wage_total > pf_capped and pf_calc.get("pf_type") == "uncapped" and pf_wage_total > pf_ceiling_cfg:
        fail(
            "STAT-003",
            f"PF Wage Above ₹{_fmt(pf_ceiling_cfg)} (Uncapped Mode)",
            "pf_wage",
            f"≤ ₹{_fmt(pf_ceiling_cfg)} or voluntary",
            _fmt(pf_wage_total),
            "WARNING",
            f"PF wage ({_fmt(pf_wage_total)}) > ₹{_fmt(pf_ceiling_cfg)} statutory ceiling "
            "but ceiling restriction is OFF.",
            "Enable 'Restrict PF to wage ceiling' in Statutory Engine unless voluntary PF is confirmed.",
            float((pf_wage_total - pf_ceiling_cfg) * _dec(pf_calc.get("_emp_rate", 0.12))),
        )
        pf_comps = [k for k, c in comp_by_key.items() if c.pf_applicable]
        if pf_comps:
            info("STAT-004", "PF Wage is Zero", "pf_wage",
                 "> 0", "0.00",
                 f"PF components ({', '.join(pf_comps)}) are all zero — no PF deducted.",
                 "Check that Basic/DA is present in the salary register for this employee.")

    # ── ESIC ─────────────────────────────────────────────────────────
    esic_emp_exp = _q(_dec(esic_calc.get("esic_employee", 0)))
    esic_er_exp  = _q(_dec(esic_calc.get("esic_employer", 0)))
    esic_eligible: bool = esic_calc.get("esic_eligible", False)
    esic_wage_total = sum(
        (amt for k, amt in regular.items() if comp_by_key.get(k) and comp_by_key[k].esic_applicable),
        start=Decimal("0"),
    )

    if not esic_eligible and esic_wage_total > Decimal("0"):
        info(
            "STAT-005",
            f"ESIC Ineligible — Above ₹{_fmt(esic_ceiling_cfg)}",
            "esic_wage",
             f"≤ ₹{_fmt(esic_ceiling_cfg)}", _fmt(esic_wage_total),
             f"ESIC wage ({_fmt(esic_wage_total)}) > ₹{_fmt(esic_ceiling_cfg)} statutory ceiling — "
             "employee is exempt under current config.",
             "Ensure no ESIC deduction appears for this employee.",
        )

    esic_emp_raw = row.get("esic_employee")
    if esic_emp_raw not in (None, ""):
        esic_emp_actual = _dec(esic_emp_raw)
        diff_esic = (esic_emp_actual - esic_emp_exp).copy_abs()
        if diff_esic > tol_stat:
            fail("STAT-006", "ESIC Employee Contribution Mismatch", "esic_employee",
                 esic_emp_exp, esic_emp_actual, "CRITICAL",
                 f"ESIC employee ({_fmt(esic_emp_actual)}) ≠ {_fmt(esic_wage_total)} × "
                 f"{esic_emp_rate_pct:.4f}% = {_fmt(esic_emp_exp)}.",
                 f"Correct esic_employee to ₹{_fmt(esic_emp_exp)}.",
                 float(diff_esic))
        else:
            pass_("STAT-006", "ESIC Employee Contribution", "esic_employee", esic_emp_actual)
    elif esic_eligible and esic_emp_exp > Decimal("0"):
        info("STAT-006", "ESIC Employee Column Absent", "esic_employee",
             _fmt(esic_emp_exp), "(missing)",
             "Register has no esic_employee column — ESIC deduction cannot be verified.",
             "Add 'esic_employee' column to your salary register template.")

    esic_er_raw = row.get("esic_employer")
    if esic_er_raw not in (None, ""):
        esic_er_actual = _dec(esic_er_raw)
        diff_er = (esic_er_actual - esic_er_exp).copy_abs()
        if diff_er > tol_stat:
            fail("STAT-007", "ESIC Employer Contribution Mismatch", "esic_employer",
                 esic_er_exp, esic_er_actual, "CRITICAL",
                 f"ESIC employer ({_fmt(esic_er_actual)}) ≠ {_fmt(esic_wage_total)} × "
                 f"{esic_er_rate_pct:.4f}% = {_fmt(esic_er_exp)}.",
                 f"Correct esic_employer to ₹{_fmt(esic_er_exp)}.",
                 float(diff_er))
        else:
            pass_("STAT-007", "ESIC Employer Contribution", "esic_employer", esic_er_actual)

    # ── PT ───────────────────────────────────────────────────────────
    pt_raw = row.get("pt") or row.get("pt_amount")
    if pt_raw not in (None, ""):
        pt_actual = _dec(pt_raw)
        if pt_due > Decimal("0") and (pt_actual - pt_due).copy_abs() > tol_stat:
            fail("STAT-008", "Professional Tax Mismatch", "pt",
                 pt_due, pt_actual, "WARNING",
                 f"PT in register ({_fmt(pt_actual)}) ≠ slab ({_fmt(pt_due)}).",
                 "Verify PT state + slab in Rule Engine → PT/LWF Slabs. Check gender/month rules.",
                 float((pt_actual - pt_due).copy_abs()))
        elif pt_due > Decimal("0"):
            pass_("STAT-008", "Professional Tax", "pt", pt_actual)
    elif pt_due > Decimal("0"):
        info("STAT-008", "PT Column Absent", "pt", _fmt(pt_due), "(missing)",
             f"Computed PT = {_fmt(pt_due)} but register has no 'pt' column.",
             "Add 'pt' or 'pt_amount' column to your salary register.")

    # ── LWF ──────────────────────────────────────────────────────────
    lwf_emp_raw = row.get("lwf_employee")
    if lwf_emp_raw not in (None, "") and lwf_eamt > Decimal("0"):
        lwf_emp_actual = _dec(lwf_emp_raw)
        diff_lwf = (lwf_emp_actual - lwf_eamt).copy_abs()
        if diff_lwf > tol_stat:
            fail("STAT-009", "LWF Employee Mismatch", "lwf_employee",
                 lwf_eamt, lwf_emp_actual, "WARNING",
                 f"LWF employee ({_fmt(lwf_emp_actual)}) ≠ slab ({_fmt(lwf_eamt)}).",
                 "Check LWF slab configuration for this state under Rule Engine → PT/LWF Slabs.",
                 float(diff_lwf))

    lwf_er_raw = row.get("lwf_employer")
    if lwf_er_raw not in (None, "") and lwf_oamt > Decimal("0"):
        lwf_er_actual = _dec(lwf_er_raw)
        diff_lwf_er = (lwf_er_actual - lwf_oamt).copy_abs()
        if diff_lwf_er > tol_stat:
            fail("STAT-010", "LWF Employer Mismatch", "lwf_employer",
                 lwf_oamt, lwf_er_actual, "WARNING",
                 f"LWF employer ({_fmt(lwf_er_actual)}) ≠ slab ({_fmt(lwf_oamt)}).",
                 "Check LWF employer slab for this state.",
                 float(diff_lwf_er))

    # ── TDS ──────────────────────────────────────────────────────────
    for flag in tds_risk:
        findings.append(ValidationFinding(
            employee_id=employee_id, employee_name=employee_name,
            rule_id="STAT-011", rule_name="TDS Risk — High Income Month",
            component="tds", expected_value="TDS deducted", actual_value="risk present",
            difference="", severity="WARNING", status="FAIL", reason=flag,
            suggested_fix="Recalculate TDS for this month including arrear income. "
                          "File revised TDS if already paid.",
            financial_impact=0.0,
        ))

    # ── GRATUITY (awareness flag) ─────────────────────────────────────
    gratuity_raw = row.get("gratuity")
    if gratuity_raw not in (None, "") and _dec(gratuity_raw) > Decimal("0"):
        gratuity_actual = _dec(gratuity_raw)
        max_gratuity = t.gratuity.exemption_cap
        if gratuity_actual > max_gratuity:
            fail("STAT-014", "Gratuity Exceeds ₹20 Lakh Statutory Cap", "gratuity",
                 _fmt(max_gratuity), _fmt(gratuity_actual), "WARNING",
                 f"Gratuity ({_fmt(gratuity_actual)}) exceeds the statutory tax-exempt cap of ₹20,00,000.",
                 "Cap tax-exempt gratuity at ₹20,00,000. Excess is taxable income.",
                 float(gratuity_actual - max_gratuity))

    # ═══════════════════════════════════════════════════════════════════
    # P5 – LOP / PRORATION
    # ═══════════════════════════════════════════════════════════════════

    if paid_days is not None and lop_days is not None:
        actual_sum = paid_days + lop_days
        if (actual_sum - Decimal(days_in_month)).copy_abs() > Decimal("0.01"):
            fail("LOP-001", "Paid Days + LOP Days ≠ Days in Month",
                 "paid_days + lop_days", days_in_month, _fmt(actual_sum), "WARNING",
                 f"paid_days ({paid_days}) + lop_days ({lop_days}) = {actual_sum}, "
                 f"expected {days_in_month}. Attendance data is inconsistent.",
                 "Reconcile attendance with HRMS. Paid + LOP must equal calendar days.")

    for d in lop_diffs:
        comp_key = d.get("component", "")
        exp_v = Decimal(str(d.get("expected", 0)))
        act_v = Decimal(str(d.get("actual", 0)))
        diff_v = act_v - exp_v
        findings.append(ValidationFinding(
            employee_id=employee_id, employee_name=employee_name,
            rule_id="LOP-002", rule_name="LOP Proration Mismatch",
            component=comp_key,
            expected_value=_fmt(exp_v), actual_value=_fmt(act_v),
            difference=_fmt(diff_v), severity="WARNING", status="FAIL",
            reason=f"'{comp_key}' prorated value should be {_fmt(exp_v)} "
                   f"(monthly × paid_days/{days_in_month}), got {_fmt(act_v)} (diff {_fmt(diff_v)}).",
            suggested_fix=f"Recompute {comp_key} = (Annual CTC / 12) × ({paid_days} / {days_in_month}).",
            financial_impact=float(diff_v.copy_abs()),
        ))

    # ═══════════════════════════════════════════════════════════════════
    # P6 – MONTH-ON-MONTH COMPARISON
    # ═══════════════════════════════════════════════════════════════════

    if prior_is_joiner:
        info("MOM-001", "New Joiner Detected", "employee",
             "Prior month record", "No prior record",
             "No prior-month record found. Confirm joining date and validate partial-month salary.",
             "Check joining date. If mid-month joiner, verify proration using LOP-002 rules.")

    if prior_components is not None and not prior_is_joiner:
        arrear_present = inc_arrear_total > Decimal("0") or any(v > 0 for v in arrear_by_base.values())

        for k, old_val_f in prior_components.items():
            old_val = Decimal(str(old_val_f))
            new_val = regular.get(k, Decimal("0"))
            if old_val == Decimal("0"):
                continue
            pct = float((new_val - old_val) / old_val) * 100

            change_pct = float(t.trends.component_change_pct)
            if abs(pct) > change_pct and not arrear_present:
                rule_id = "MOM-002" if pct > 0 else "MOM-003"
                rule_name = (f"Component Spike > {t.trends.component_change_pct}%" if pct > 0
                             else f"Component Drop > {t.trends.component_change_pct}%")
                findings.append(ValidationFinding(
                    employee_id=employee_id, employee_name=employee_name,
                    rule_id=rule_id, rule_name=rule_name, component=k,
                    expected_value=_fmt(old_val), actual_value=_fmt(new_val),
                    difference=f"{pct:+.1f}%", severity="WARNING", status="FAIL",
                    reason=f"'{k}' changed {pct:+.1f}% vs prior ({_fmt(old_val)} → {_fmt(new_val)}) without arrear.",
                    suggested_fix="Verify via approved increment letter. If arrear, process as increment_arrear run.",
                    financial_impact=float((new_val - old_val).copy_abs()),
                ))

        for k in regular:
            if k not in prior_components:
                info("MOM-004", "New Component This Month", k,
                     "0.00", _fmt(regular[k]),
                     f"'{k}' is new this month — not in prior register.",
                     f"Confirm '{k}' was intentionally added. Check component config mapping.")

        for k, old_val_f in prior_components.items():
            if k not in regular and float(old_val_f) > 0:
                findings.append(ValidationFinding(
                    employee_id=employee_id, employee_name=employee_name,
                    rule_id="MOM-005", rule_name="Component Missing vs Prior Month",
                    component=k,
                    expected_value=_fmt(Decimal(str(old_val_f))), actual_value="0.00",
                    difference=_fmt(-Decimal(str(old_val_f))),
                    severity="WARNING", status="FAIL",
                    reason=f"'{k}' was ₹{old_val_f:.2f} last month but is absent this month.",
                    suggested_fix=f"Verify if '{k}' was discontinued. If not, add it back.",
                    financial_impact=float(old_val_f),
                ))

    # ── Arrears, per employee ────────────────────────────────────────
    # Each row carries its own arrear window. These run for whoever has arrears
    # in this register, regardless of what the file as a whole was called.
    if composition is not None and composition.any_arrear:
        total_arrear = composition.arrear_total + composition.increment_arrear_total

        if composition.arrear_months is None:
            # Every arrear expectation is a monthly delta multiplied by a month
            # count. Without that count nothing can be verified, and guessing it
            # would fabricate an expected figure that looks authoritative.
            info("ARR-001", "Arrear Period Not Stated", "arrear",
                 "(a from/to date or month count)", "(none)",
                 f"₹{_fmt(total_arrear)} of arrears paid, but no arrear period is stated on the "
                 f"row, on the employee's CTC revision, or in the run parameters — the number of "
                 f"months cannot be established, so the amount cannot be verified.",
                 "Add an 'Arrear From' (and optionally 'Arrear To') or 'Arrear Months' column, "
                 "or upload the CTC revision that triggered the arrear.")
        elif composition.arrear_months <= 0:
            fail("ARR-002", "Arrear Period Invalid", "arrear",
                 "> 0 months", f"{composition.arrear_months} months", "WARNING",
                 f"The stated arrear period resolves to {composition.arrear_months} months.",
                 "Check the arrear from/to dates — the end month must not precede the start.",
                 0.0)
        elif composition.arrear_months > int(t.trends.max_arrear_months):
            info("ARR-003", "Arrear Period Unusually Long", "arrear",
                 f"\u2264 {int(t.trends.max_arrear_months)} months",
                 f"{composition.arrear_months} months",
                 f"Arrears span {composition.arrear_months} months "
                 f"(window from {composition.window_source}). Long recoveries attract scrutiny "
                 f"and may carry PF interest and damages for the delayed months.",
                 "Confirm the revision date, and check whether PF/ESIC on these arrears was "
                 "remitted in the months they relate to.")

        # Arrears shift PF and ESIC wages into earlier months. Where the wage was
        # already at or above the ceiling, the arrear carries no further PF — a
        # frequent and expensive over-deduction.
        pf_ceiling = _dec(pf_calc.get("_ceiling", 0))
        pf_wage_full = _dec(pf_calc.get("_pf_wage_full", 0))
        # Not merged into one condition: the nesting separates "does this
        # situation apply" from "is the restricted basis in force", and the
        # single line ruff suggests carries four conditions.
        if composition.has_arrear and pf_ceiling > 0 and pf_wage_full >= pf_ceiling:  # noqa: SIM102
            if bool(pf_calc.get("_restrict", True)):
                info("ARR-004", "Arrear PF Not Due — Wage Already At Ceiling", "arrear",
                     "no additional PF", _fmt(composition.arrear_total),
                     f"Regular PF wage ({_fmt(pf_wage_full)}) is already at or above the "
                     f"{_fmt(pf_ceiling)} ceiling, so arrears of {_fmt(composition.arrear_total)} "
                     f"attract no further PF on the restricted basis.",
                     "Confirm no PF was deducted on the arrear amount.")

    if inc_info.get("applicable"):
        exp_total = float(inc_info.get("expected_total", 0))
        act_total = float(inc_info.get("actual_total", 0))
        months_cnt = inc_info.get("months", 0)
        if abs(act_total - exp_total) > 1.0:
            fail("MOM-006", "Increment Arrear Mismatch", "increment_arrear",
                 exp_total, act_total, "WARNING",
                 f"Expected arrear ₹{exp_total:.2f} across {months_cnt} month(s) from CTC delta. "
                 f"Register shows ₹{act_total:.2f}.",
                 f"Recompute: (New monthly − Old monthly) × {months_cnt} months = ₹{exp_total:.2f}.",
                 abs(act_total - exp_total))

    # ═══════════════════════════════════════════════════════════════════
    # P7 – ADVANCED / ANOMALY DETECTION
    # ═══════════════════════════════════════════════════════════════════

    total_regular = sum(regular.values(), start=Decimal("0"))

    if (total_regular == Decimal("0") and prior_components is not None
            and not prior_is_joiner and any(v > 0 for v in prior_components.values())):
        fail("ADV-001", "Zero Salary — Continuing Employee", "gross",
             "> 0", "0.00", "WARNING",
             "All components zero for an employee who had salary last month. "
             "Possible hold, payroll error, or exit without processing.",
             "Confirm employee status (Active/Exit). If on hold, document reason.")

    if prior_components is not None and not prior_is_joiner:
        prior_gross = sum(Decimal(str(v)) for v in prior_components.values())
        if prior_gross > Decimal("0") and total_regular > Decimal("0"):
            ratio = float(total_regular / prior_gross)
            if ratio > float(t.trends.salary_spike_ratio):
                fail("ADV-002", f"Salary Spike > {t.trends.salary_spike_ratio}× Prior Month", "gross",
                     _fmt(prior_gross), _fmt(total_regular), "WARNING",
                     f"Salary is {ratio:.1f}× the prior month ({_fmt(prior_gross)} → {_fmt(total_regular)}). "
                     "Likely bulk arrear, duplication, or data error.",
                     "Validate if this includes arrear. If so, run as increment_arrear type.",
                     float(total_regular - prior_gross))
            elif ratio < float(t.trends.salary_drop_ratio):
                fail("ADV-003",
                     f"Salary Drop < {float(t.trends.salary_drop_ratio) * 100:.0f}% of Prior Month", "gross",
                     _fmt(prior_gross), _fmt(total_regular), "WARNING",
                     f"Salary is only {ratio*100:.0f}% of prior ({_fmt(prior_gross)} → {_fmt(total_regular)}). "
                     "Possible excessive LOP, partial exit, or data truncation.",
                     "Verify paid_days. If partial exit, confirm final settlement is separate.",
                     float(prior_gross - total_regular))

    # ═══════════════════════════════════════════════════════════════════
    # P7 – IDENTITY & MASTER DATA (spec §2)
    # ═══════════════════════════════════════════════════════════════════

    ref_date = period_month or None

    pan_raw = idc.row_text(row, "pan")
    pan_ok, pan_reason = idc.validate_pan(pan_raw) if pan_raw else (False, "missing")
    if pan_raw and not pan_ok:
        fail("ID-001", "Invalid PAN", "pan", "[A-Z]{5}[0-9]{4}[A-Z], 4th char 'P'",
             pan_raw, "CRITICAL",
             f"PAN '{pan_raw}' failed validation ({pan_reason}). TDS credit will not reflect in 26AS.",
             "Correct the PAN from the employee's PAN card; 4th character must be 'P' for individuals.")

    aad_raw = idc.row_text(row, "aadhaar", "aadhar")
    if aad_raw:
        ok_a, why_a = idc.validate_aadhaar(aad_raw)
        if not ok_a:
            fail("ID-002", "Invalid Aadhaar", "aadhaar", "12 digits, valid Verhoeff checksum",
                 aad_raw, "CRITICAL",
                 f"Aadhaar failed validation ({why_a}).",
                 "Re-verify against the Aadhaar card. UAN-Aadhaar seeding fails on invalid numbers.")

    pf_deducted = _dec(row.get("pf_employee") or row.get("pf_emp") or 0) > 0
    uan_raw = idc.row_text(row, "uan")
    if pf_deducted and not uan_raw:
        fail("ID-003", "UAN Missing with PF Deduction", "uan", "12-digit UAN", "(missing)",
             "WARNING", "PF is deducted but no UAN — ECR filing will reject this member.",
             "Obtain/generate the employee's UAN before the ECR due date.")
    elif uan_raw and not idc.validate_uan(uan_raw)[0]:
        fail("ID-003", "Invalid UAN", "uan", "12 digits", uan_raw, "CRITICAL",
             "UAN must be exactly 12 digits.", "Correct the UAN from the EPFO portal.")

    esic_deducted = _dec(row.get("esic_employee") or 0) > 0
    esi_num_raw = idc.row_text(row, "esi_number", "esi_no", "ip_number")
    if esic_deducted and not esi_num_raw:
        fail("ID-004", "ESI Number Missing with ESI Deduction", "esi_number",
             "10 or 17-digit IP number", "(missing)", "CRITICAL",
             "ESI contribution deducted but no insured-person number on record.",
             "Register the employee on the ESIC portal and record the IP number.")
    elif esi_num_raw and not idc.validate_esi_number(esi_num_raw)[0]:
        fail("ID-004", "Invalid ESI Number", "esi_number", "10 or 17 digits", esi_num_raw,
             "CRITICAL", "ESI number must be 10 (old) or 17 (new) digits.",
             "Correct from the ESIC registration.")

    ifsc_raw = idc.row_text(row, "ifsc", "ifsc_code")
    if ifsc_raw and not idc.validate_ifsc(ifsc_raw)[0]:
        fail("ID-005", "Invalid IFSC", "ifsc", "[A-Z]{4}0[A-Z0-9]{6}", ifsc_raw, "CRITICAL",
             "IFSC failed format validation — salary credit will bounce.",
             "Correct the IFSC from the employee's cancelled cheque / bank record.")

    dob = idc.parse_cell_date(row.get("dob") or row.get("date_of_birth"))
    if dob and ref_date:
        age = idc.age_in_years(dob, ref_date)
        if age < float(t.identity.min_working_age_years):
            fail("ID-006", "Below Minimum Working Age", "dob",
                 f"age ≥ {t.identity.min_working_age_years}", f"{age:.1f} years", "CRITICAL",
                 "Employee is below the minimum working age — child labour is prohibited.",
                 "Remove from payroll immediately and review onboarding records.")
        elif age < float(t.identity.adult_age_years) and not idc.row_flag(row, "adolescent_permit"):
            fail("ID-006", "Adolescent Without Permit Flag", "dob",
                 f"age ≥ {t.identity.adult_age_years} or adolescent_permit=1", f"{age:.1f} years",
                 "CRITICAL",
                 "Employees aged 14-18 need non-hazardous adolescent permits on file.",
                 "Attach the permit record and set adolescent_permit=1, or remove from rolls.")

    doj = idc.parse_cell_date(row.get("doj") or row.get("date_of_joining"))
    dol = idc.parse_cell_date(row.get("dol") or row.get("date_of_leaving"))
    if doj and ref_date and doj > ref_date:
        try:
            import calendar as _cal
            month_end = ref_date.replace(day=_cal.monthrange(ref_date.year, ref_date.month)[1])
        except Exception:
            month_end = ref_date
        if doj > month_end:
            fail("ID-007", "Paid Before Date of Joining", "doj", f"≤ {month_end}", str(doj),
                 "CRITICAL", "DOJ is after the payroll month — employee paid before joining.",
                 "Verify DOJ; remove the row or correct the joining date.")
    if dol and ref_date and dol < ref_date and total_regular > Decimal("0") \
            and inc_arrear_total == Decimal("0") and not any(v > 0 for v in arrear_by_base.values()):
        fail("ID-008", "Salary After Exit Without Arrear Flag", "dol", "no pay after DOL", str(dol),
             "CRITICAL",
             f"Employee exited on {dol} but has regular earnings this month with no arrear marking.",
             "Route post-exit payments through an arrear/F&F run, or correct the DOL.")

    # ═══════════════════════════════════════════════════════════════════
    # P8 – DEEP STATUTORY (spec §4-10)
    # ═══════════════════════════════════════════════════════════════════

    # PF: EPS split (EPS-95) — validated when the register carries an EPS column
    eps_raw = row.get("eps") or row.get("pf_eps") or row.get("eps_employer")
    if eps_raw not in (None, ""):
        eps_actual = _dec(eps_raw)
        eps_cap = t.pf_deep.eps_wage_cap
        eps_expected = _q(min(pf_wage_total, eps_cap) * t.pf_deep.eps_rate)
        eps_zero_reason = ""
        cutoff = idc.parse_cell_date(t.pf_deep.eps_join_cutoff)
        if doj and cutoff and doj >= cutoff and pf_wage_total > eps_cap:
            eps_expected, eps_zero_reason = Decimal("0"), f"joined {doj} (≥ {cutoff}) with PF wages above ₹{eps_cap}"
        if dob and ref_date and idc.age_in_years(dob, ref_date) >= float(t.pf_deep.eps_max_age_years):
            eps_expected, eps_zero_reason = Decimal("0"), f"age ≥ {t.pf_deep.eps_max_age_years} — EPS stops, full 12% to EPF"
        if (eps_actual - eps_expected).copy_abs() > tol_stat:
            fail("PF-004", "EPS Contribution Mismatch", "eps", eps_expected, eps_actual, "CRITICAL",
                 (f"EPS should be 0: {eps_zero_reason}." if eps_zero_reason else
                  f"EPS must be {t.pf_deep.eps_rate}×min(PF wages, ₹{eps_cap}) = {_fmt(eps_expected)}."),
                 f"Correct EPS to ₹{_fmt(eps_expected)} and route the balance to EPF.",
                 float((eps_actual - eps_expected).copy_abs()))

    # PF: international worker — no wage ceiling
    if idc.row_flag(row, "international_worker") and _dec(pf_calc.get("pf_wage_capped", 0)) < pf_wage_total:
        fail("PF-008", "International Worker PF Capped", "pf_wage",
             _fmt(pf_wage_total), _fmt(_dec(pf_calc.get("pf_wage_capped", 0))), "CRITICAL",
             "International workers have no PF wage ceiling — contribution must be on full PF wages.",
             "Disable ceiling restriction for this employee (para 83 / relevant SSA).",
             float((pf_wage_total - _dec(pf_calc.get("pf_wage_capped", 0))) * pf_emp_rate))

    # ESI: disability ceiling and daily-wage exemption
    if idc.row_flag(row, "disability") and not esic_deducted \
            and esic_ceiling_cfg < esic_wage_total <= t.esi_deep.disability_wage_ceiling:
        fail("ESI-005", "Disability ESI Coverage Missed", "esic_employee",
             f"covered up to ₹{t.esi_deep.disability_wage_ceiling}", "0.00", "WARNING",
             f"Employees with disability are ESI-covered up to ₹{t.esi_deep.disability_wage_ceiling} "
             f"(wage {_fmt(esic_wage_total)}).",
             "Enrol the employee under ESI with the enhanced ceiling.")
    if days_in_month and esic_deducted:
        daily_wage = esic_wage_total / Decimal(days_in_month)
        if daily_wage <= t.esi_deep.daily_wage_exemption_limit:
            fail("ESI-006", "Employee ESI Share on Exempt Daily Wage", "esic_employee",
                 "0.00", _fmt(_dec(row.get("esic_employee"))), "WARNING",
                 f"Average daily wage {_fmt(_q(daily_wage))} ≤ ₹{t.esi_deep.daily_wage_exemption_limit} — "
                 "employee share is exempt (employer share still payable).",
                 "Zero the employee ESI deduction for this employee.")

    # PT: constitutional cap + no-PT states
    pt_actual_row = _dec(row.get("pt") or row.get("pt_amount") or 0)
    if pt_actual_row > t.pt_caps.annual_cap:
        fail("PT-002", "PT Exceeds Constitutional Annual Cap", "pt",
             f"≤ {t.pt_caps.annual_cap}/year", _fmt(pt_actual_row), "CRITICAL",
             f"A single month's PT ({_fmt(pt_actual_row)}) exceeds the Article 276 annual cap of "
             f"₹{t.pt_caps.annual_cap}.",
             "Correct the PT deduction; the annual total per employee cannot exceed the cap.",
             float(pt_actual_row - t.pt_caps.annual_cap))
    row_state = idc.row_text(row, "state", "work_state", "state_pt", "location_state")
    if pt_actual_row > 0 and row_state and row_state.strip().title() in {
        s.strip().title() for s in t.pt_caps.no_pt_states
    }:
        fail("PT-003", "PT Deducted in a No-PT State", "pt", "0.00", _fmt(pt_actual_row),
             "CRITICAL", f"{row_state} does not levy Professional Tax.",
             "Remove the PT deduction and refund the employee.", float(pt_actual_row))

    # Bonus: Payment of Bonus Act band
    bonus_raw = row.get("bonus")
    if bonus_raw not in (None, "") and _dec(bonus_raw) > 0:
        bonus_actual = _dec(bonus_raw)
        basic_da = pf_wage_total  # Basic+DA proxy: PF-flagged components
        if basic_da > t.bonus.eligibility_wage_ceiling:
            info("BON-001", "Bonus Paid Above Eligibility Ceiling", "bonus",
                 f"Basic+DA ≤ {t.bonus.eligibility_wage_ceiling}", _fmt(basic_da),
                 "Wages exceed the Payment of Bonus Act ceiling — label this as ex-gratia, not statutory bonus.",
                 "Rename the component or record it as ex-gratia in the register.")
        else:
            base = min(basic_da, t.bonus.calc_base_floor)
            lo = _q(base * t.bonus.min_rate)
            hi = _q(base * t.bonus.max_rate)
            if not (lo <= bonus_actual <= hi):
                fail("BON-002", "Statutory Bonus Outside 8.33-20% Band", "bonus",
                     f"{_fmt(lo)} – {_fmt(hi)}", _fmt(bonus_actual), "CRITICAL",
                     f"Monthly statutory bonus must fall between {t.bonus.min_rate}× and "
                     f"{t.bonus.max_rate}× of base ₹{_fmt(base)}.",
                     "Recompute bonus per the Act, or reclassify as ex-gratia.",
                     float(min((bonus_actual - hi).copy_abs(), (bonus_actual - lo).copy_abs())))

    # Gratuity: formula check at exit
    grat_raw = row.get("gratuity")
    if grat_raw not in (None, "") and _dec(grat_raw) > 0 and doj and dol:
        grat_actual = _dec(grat_raw)
        years = idc.completed_service_years(doj, dol)
        waived = idc.row_flag(row, "death_or_disablement")
        if years < float(t.gratuity_formula.min_service_years) and not waived:
            fail("GRAT-002", "Gratuity Paid Below Minimum Service", "gratuity",
                 f"≥ {t.gratuity_formula.min_service_years} years service", f"{years} years",
                 "WARNING",
                 f"Service {doj} → {dol} is {years} completed years — below the eligibility threshold "
                 "(waived only on death/disablement).",
                 "Verify eligibility (4y240d case law) or reclassify the payment.")
        else:
            basic_da = pf_wage_total
            expected_grat = _q(basic_da * t.gratuity_formula.factor_numerator
                               / t.gratuity_formula.factor_denominator * Decimal(years))
            if expected_grat > 0:
                dev_pct = float((grat_actual - expected_grat).copy_abs() / expected_grat * 100)
                if dev_pct > float(t.gratuity_formula.amount_tolerance_pct):
                    fail("GRAT-003", "Gratuity Deviates from Formula", "gratuity",
                         _fmt(expected_grat), _fmt(grat_actual), "WARNING",
                         f"(Basic+DA {_fmt(basic_da)}) × {t.gratuity_formula.factor_numerator}/"
                         f"{t.gratuity_formula.factor_denominator} × {years} years = {_fmt(expected_grat)} "
                         f"(deviation {dev_pct:.1f}%).",
                         "Recheck last-drawn Basic+DA and completed service years.",
                         float((grat_actual - expected_grat).copy_abs()))

    # TDS: Sec 206AA (no PAN) and Sec 192 projection
    tds_raw = row.get("tds") or row.get("income_tax")
    taxable_month = sum(
        (amt for k, amt in regular.items()
         if comp_by_key.get(k) and getattr(comp_by_key[k], "taxable", False)),
        start=Decimal("0"),
    )
    if not pan_ok and tds_raw not in (None, "") and taxable_month > 0:
        required = _q(taxable_month * t.identity.no_pan_tds_rate)
        if _dec(tds_raw) < required - tol_stat:
            fail("TDS-001", "No-PAN TDS Below 20% (Sec 206AA)", "tds",
                 _fmt(required), _fmt(_dec(tds_raw)), "CRITICAL",
                 f"PAN is {'invalid' if pan_raw else 'missing'} — TDS must be at least "
                 f"{float(t.identity.no_pan_tds_rate) * 100:.0f}% of taxable pay ({_fmt(taxable_month)}).",
                 "Deduct at the Sec 206AA rate or obtain a valid PAN.",
                 float(required - _dec(tds_raw)))
    if expected_monthly_tds is not None and tds_raw not in (None, ""):
        tds_actual = _dec(tds_raw)
        exp_tds = Decimal(str(round(expected_monthly_tds, 2)))
        tol = max(t.tds_deep.projection_tolerance_abs,
                  _q(exp_tds * t.tds_deep.projection_tolerance_pct / Decimal("100")))
        if (tds_actual - exp_tds).copy_abs() > tol:
            fail("TDS-002", "Monthly TDS Deviates from Projection", "tds",
                 _fmt(exp_tds), _fmt(tds_actual), "WARNING",
                 f"Projected monthly TDS (annualised, declared regime) is {_fmt(exp_tds)}; "
                 f"deduction differs by {_fmt((tds_actual - exp_tds).copy_abs())} (> ₹{_fmt(tol)} tolerance).",
                 "Re-project annual tax over remaining months; correct cumulative deduction by Q4.",
                 float((tds_actual - exp_tds).copy_abs()))

    # Data-quality: negative deductions, zero-net actives, impossible paid days
    for ded_key in ("pf_employee", "esic_employee", "pt", "pt_amount", "lwf_employee", "tds", "income_tax"):
        v = row.get(ded_key)
        if v not in (None, "") and _dec(v) < 0:
            fail("DATA-005", "Negative Deduction", ded_key, "≥ 0", _fmt(_dec(v)), "CRITICAL",
                 f"Deduction '{ded_key}' is negative — refunds must be separate reversal lines.",
                 "Move the refund to a marked recovery/reversal component.")
    net_col = next(
        (row[k] for k in ("net", "net_salary", "net_pay", "take_home")
         if row.get(k) not in (None, "")),
        None,
    )
    if net_col is not None and _dec(net_col) == 0 and paid_days and paid_days > 0:
        fail("AGG-003", "Zero Net Pay for Active Employee", "net", "> 0", "0.00", "WARNING",
             f"Employee has {paid_days} paid days but zero net pay.",
             "Check for full-salary recovery/hold; document the reason.")
    if net_col not in (None, "") and _dec(net_col) < 0:
        fail("AGG-004", "Negative Net Pay", "net", "≥ 0", _fmt(_dec(net_col)), "CRITICAL",
             "Net pay is negative — recoveries exceed earnings.",
             "Cap recoveries this month and carry the balance to a recovery schedule.")
    if paid_days is not None and days_in_month and paid_days > Decimal(days_in_month):
        fail("LOP-003", "Paid Days Exceed Days in Month", "paid_days",
             f"≤ {days_in_month}", _fmt(paid_days), "CRITICAL",
             "Paid days cannot exceed the month's days.", "Correct the attendance import.")

    return findings


# ── Batch-level findings ──────────────────────────────────────────────────────

def batch_findings(employees: list[dict[str, Any]]) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    seen: dict[str, int] = {}
    for row in employees:
        eid = str(row.get("employee_id") or row.get("emp_id") or row.get("employee_code") or "").strip()
        if not eid:
            continue
        seen[eid] = seen.get(eid, 0) + 1

    for eid, count in seen.items():
        if count > 1:
            findings.append(ValidationFinding(
                employee_id=eid, employee_name=None,
                rule_id="DATA-002", rule_name="Duplicate Employee ID",
                component="employee_id",
                expected_value="unique", actual_value=f"{count} occurrences",
                difference="", severity="CRITICAL", status="FAIL",
                reason=f"Employee ID '{eid}' appears {count} times. Duplicates cause incorrect statutory aggregation.",
                suggested_fix="Remove duplicate rows. Keep one record per employee per pay period.",
                financial_impact=0.0,
            ))

    # Duplicate statutory identifiers across different employees (spec §2.5-2.6)
    dup_specs = [
        ("DATA-006", "Duplicate PAN", "pan", ("pan",), "CRITICAL",
         "The same PAN on two employees corrupts TDS returns (24Q)."),
        ("DATA-007", "Duplicate UAN", "uan", ("uan",), "CRITICAL",
         "The same UAN on two employees corrupts the PF ECR."),
        ("DATA-008", "Duplicate Aadhaar", "aadhaar", ("aadhaar", "aadhar"), "CRITICAL",
         "The same Aadhaar on two employees indicates a data error or duplicate identity."),
        ("DATA-009", "Duplicate Bank Account", "bank_account", ("bank_account", "account_number"),
         "WARNING", "Two employees share a bank account — possible ghost employee."),
    ]
    for rule_id, rule_name, component, keys, severity, why in dup_specs:
        by_value: dict[str, list[str]] = {}
        for row in employees:
            eid = str(row.get("employee_id") or row.get("emp_id") or row.get("employee_code") or "").strip()
            val = ""
            for k in keys:
                v = row.get(k)
                if v not in (None, ""):
                    val = idc.clean_id(v)
                    break
            if eid and val:
                by_value.setdefault(val, []).append(eid)
        for val, eids in by_value.items():
            if len(set(eids)) > 1:
                for eid in sorted(set(eids)):
                    findings.append(ValidationFinding(
                        employee_id=eid, employee_name=None,
                        rule_id=rule_id, rule_name=rule_name, component=component,
                        expected_value="unique per employee",
                        actual_value=f"shared by {len(set(eids))} employees",
                        difference="", severity=severity, status="FAIL",
                        reason=f"{rule_name.split(' ', 1)[1]} '{val}' is shared by employees "
                               f"{', '.join(sorted(set(eids)))}. {why}",
                        suggested_fix="Verify each employee's identity documents and correct the register.",
                        financial_impact=0.0,
                    ))
    return findings


# ── Summary ───────────────────────────────────────────────────────────────────

def summarise_findings(all_findings: list[ValidationFinding]) -> dict[str, Any]:
    fails = [f for f in all_findings if f.status == "FAIL"]
    flat_dicts = [f.to_dict() for f in all_findings]
    rule_counts: dict[str, dict] = {}
    for f in flat_dicts:
        rid = f["rule_id"]
        if rid not in rule_counts:
            rule_counts[rid] = {"rule_id": rid, "rule_name": f["rule_name"],
                                "severity": f["severity"], "fail_count": 0}
        if f["status"] == "FAIL":
            rule_counts[rid]["fail_count"] += 1

    total_impact = sum(f.financial_impact for f in all_findings if f.status == "FAIL")

    return {
        "total_findings": len(all_findings),
        "critical": sum(1 for f in fails if f.severity == "CRITICAL"),
        "warning":  sum(1 for f in fails if f.severity == "WARNING"),
        "info":     sum(1 for f in all_findings if f.severity == "INFO"),
        "pass":     sum(1 for f in all_findings if f.status == "PASS"),
        "total_financial_impact": round(total_impact, 2),
        "rules_triggered": sorted(
            [v for v in rule_counts.values() if v["fail_count"] > 0],
            key=lambda x: x["fail_count"], reverse=True,
        ),
    }
