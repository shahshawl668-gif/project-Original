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

    def to_dict(self) -> dict[str, Any]:
        return {
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
) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []

    # Tenant-aware statutory thresholds (from compute_pf / compute_esic)
    pf_ceiling_cfg = _dec(pf_calc.get("_ceiling", 15000))
    esic_ceiling_cfg = _dec(esic_calc.get("_ceiling", 21000))
    pf_emp_rate_pct = float(pf_calc.get("_emp_rate", 0.12)) * 100
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

    for col in row.keys():
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

    if calc_gross > Decimal("0") and pf_wage_total > Decimal("0"):
        basic_pct = float(pf_wage_total / calc_gross) * 100
        if basic_pct < 30.0:
            fail("STRUCT-001", "Low PF Wage — Possible PF Avoidance", "pf_wage",
                 f"≥ 30% of gross ({_fmt(_q(calc_gross * Decimal('0.30')))})",
                 _fmt(pf_wage_total),
                 "WARNING",
                 f"PF wage ({_fmt(pf_wage_total)}) is only {basic_pct:.1f}% of gross ({_fmt(calc_gross)}). "
                 "Structures where Basic < 30% of CTC are flagged by PF authorities as avoidance.",
                 "Restructure Basic to be ≥ 40-50% of CTC. Consult CA before changing.",
                 float(_q((calc_gross * Decimal("0.40") - pf_wage_total) * Decimal("0.12"))))

    # Allowance-heavy structure
    if calc_gross > Decimal("0") and pf_wage_total > Decimal("0"):
        allowances = calc_gross - pf_wage_total
        allow_pct = float(allowances / calc_gross) * 100
        if allow_pct > 70.0:
            fail("STRUCT-002", "Allowance-Heavy Salary Structure", "allowances",
                 "≤ 70% of gross in allowances", f"{allow_pct:.1f}% of gross",
                 "WARNING",
                 f"Non-PF allowances are {allow_pct:.1f}% of gross. "
                 "High allowance structures attract scrutiny under PF Act and Income Tax.",
                 "Balance the CTC mix: target Basic ≥ 40%, HRA ≤ 50% of Basic, allowances ≤ 30%.")

    # ═══════════════════════════════════════════════════════════════════
    # P3 – AGGREGATION
    # ═══════════════════════════════════════════════════════════════════

    for gk in ("gross", "gross_salary", "gross_pay", "total_gross"):
        reg_val = row.get(gk)
        if reg_val not in (None, ""):
            actual_gross = _dec(reg_val)
            delta = (actual_gross - calc_gross).copy_abs()
            if delta > Decimal("2"):
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
            if delta > Decimal("5"):
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
        if diff_pf > Decimal("1"):
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
        if diff_er > Decimal("1"):
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
        if diff_esic > Decimal("1"):
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
        if diff_er > Decimal("1"):
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
        if pt_due > Decimal("0") and (pt_actual - pt_due).copy_abs() > Decimal("1"):
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
        if diff_lwf > Decimal("1"):
            fail("STAT-009", "LWF Employee Mismatch", "lwf_employee",
                 lwf_eamt, lwf_emp_actual, "WARNING",
                 f"LWF employee ({_fmt(lwf_emp_actual)}) ≠ slab ({_fmt(lwf_eamt)}).",
                 "Check LWF slab configuration for this state under Rule Engine → PT/LWF Slabs.",
                 float(diff_lwf))

    lwf_er_raw = row.get("lwf_employer")
    if lwf_er_raw not in (None, "") and lwf_oamt > Decimal("0"):
        lwf_er_actual = _dec(lwf_er_raw)
        diff_lwf_er = (lwf_er_actual - lwf_oamt).copy_abs()
        if diff_lwf_er > Decimal("1"):
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
        max_gratuity = Decimal("2000000")  # ₹20 lakh cap
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

            if abs(pct) > 30 and not arrear_present:
                rule_id = "MOM-002" if pct > 0 else "MOM-003"
                rule_name = "Component Spike > 30%" if pct > 0 else "Component Drop > 30%"
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
            if ratio > 3.0:
                fail("ADV-002", "Salary Spike > 3× Prior Month", "gross",
                     _fmt(prior_gross), _fmt(total_regular), "WARNING",
                     f"Salary is {ratio:.1f}× the prior month ({_fmt(prior_gross)} → {_fmt(total_regular)}). "
                     "Likely bulk arrear, duplication, or data error.",
                     "Validate if this includes arrear. If so, run as increment_arrear type.",
                     float(total_regular - prior_gross))
            elif ratio < 0.25:
                fail("ADV-003", "Salary Drop < 25% of Prior Month", "gross",
                     _fmt(prior_gross), _fmt(total_regular), "WARNING",
                     f"Salary is only {ratio*100:.0f}% of prior ({_fmt(prior_gross)} → {_fmt(total_regular)}). "
                     "Possible excessive LOP, partial exit, or data truncation.",
                     "Verify paid_days. If partial exit, confirm final settlement is separate.",
                     float(prior_gross - total_regular))

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
