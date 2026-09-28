"""
Validation coverage: for every check and every employee, one of five outcomes.

    Passed · Failed · Cannot validate · Not applicable · Disabled

A findings list answers "what went wrong". It cannot answer "what was checked",
and the difference is the most dangerous gap in a compliance tool: a check that
could not run because a column was missing produces no finding, and no finding
reads as a pass. This module makes the difference explicit.

For each rule the registry below declares, from the engine's own gating:

* ``applies`` — does the rule have anything to say about this employee? ESIC
  contribution checks apply to the ESIC-eligible; arrear checks to rows with
  arrears; month-on-month checks to continuing employees.
* ``requires`` — the inputs it needs to reach a verdict, as (label, predicate)
  pairs. A missing one makes the outcome **Cannot validate**, naming the input.

The outcome is then derived, in this order:

1. The rule is switched off for the company → **Disabled**.
2. The engine reported that it could not check (a "(missing)" column finding,
   an arrear with no period, a slab with no dated version…) → **Cannot validate**.
3. The engine reported a failure → **Failed**.
4. The engine reported a pass → **Passed**.
5. The rule does not apply → **Not applicable**, with the reason.
6. A required input is absent → **Cannot validate**, naming it.
7. Otherwise the rule ran on a complete input and raised nothing → **Passed**.

Step 7 is only sound because ``applies`` and ``requires`` mirror the engine's
gating. Each entry cites the condition it mirrors; when the engine changes, the
entry changes with it, and ``tests/test_coverage.py`` holds the two together on
fixtures that exercise every branch.

Rules that exist but do not run inside a monthly validation are declared
``runs_in_validation=False`` and reported as **Not applicable** with the reason
("checked when the attendance file is uploaded"), never as passed.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

PASSED = "passed"
FAILED = "failed"
CANNOT = "cannot_validate"
NA = "not_applicable"
DISABLED = "disabled"

OUTCOMES = (PASSED, FAILED, CANNOT, NA, DISABLED)
OUTCOME_LABELS = {
    PASSED: "Passed",
    FAILED: "Failed",
    CANNOT: "Cannot validate",
    NA: "Not applicable",
    DISABLED: "Disabled",
}


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------
@dataclass
class Context:
    """Everything a rule's gating may look at, for one employee."""

    row: dict[str, Any]
    result: dict[str, Any]
    has_master: bool = False
    master_record: bool = False
    has_attendance: bool = False
    attendance_record: bool = False
    has_prior_register: bool = False
    pt_states_configured: bool = False
    lwf_states_configured: bool = False

    def stated(self, *keys: str) -> bool:
        return any(self.row.get(k) not in (None, "") for k in keys)

    def num(self, *keys: str) -> Decimal:
        for k in keys:
            v = self.row.get(k)
            if v not in (None, ""):
                try:
                    return Decimal(str(v))
                except (InvalidOperation, ValueError):
                    return Decimal("0")
        return Decimal("0")

    def res(self, key: str, default: Any = None) -> Any:
        return self.result.get(key, default)

    def flag(self, key: str) -> bool:
        v = self.row.get(key)
        return str(v).strip().lower() in {"1", "true", "yes", "y"} if v not in (None, "") else False


Check = Callable[[Context], bool]
Requirement = tuple[str, Check]


@dataclass
class RuleCoverage:
    rule_id: str
    name: str
    family: str
    applies: Check = field(default=lambda c: True)
    na_reason: str = ""
    requires: tuple[Requirement, ...] = ()
    runs_in_validation: bool = True
    #: A Cannot-validate on this rule keeps the month from being ready for
    #: approval. Statutory contributions are material; optional detail is not.
    material: bool = False
    #: Findings of this rule that mean "could not check", identified by the
    #: engine's own marker. None: any finding of this rule is a failure.
    cannot_marker: Callable[[dict[str, Any]], bool] | None = None
    #: Checks performed once per register or per file rather than per employee.
    register_level: bool = False


def _missing_actual(f: dict[str, Any]) -> bool:
    return str(f.get("actual_value") or "").strip().lower() in {"(missing)", "(none)", ""}


def _pf_expected(c: Context) -> Decimal:
    return Decimal(str(c.res("pf_amount_employee") or 0))


def _esic_eligible(c: Context) -> bool:
    return bool(c.res("esic_eligible"))


def _continuing(c: Context) -> bool:
    return bool((c.res("prior_month") or {}).get("is_continuing"))


def _any_arrear(c: Context) -> bool:
    kinds = c.res("row_kinds") or []
    return bool(c.res("arrear_total")) or bool(c.res("increment_arrear_total")) or any(
        "arrear" in str(k) for k in kinds
    )


def _gross(c: Context) -> Decimal:
    return Decimal(str(c.res("gross_total") or 0))


STATED = lambda *keys: (lambda c: c.stated(*keys))  # noqa: E731


# ---------------------------------------------------------------------------
# The registry — one entry per rule the engine can emit
# ---------------------------------------------------------------------------
REGISTRY: list[RuleCoverage] = [
    # Import integrity ------------------------------------------------------
    RuleCoverage("DATA-001", "Missing Employee ID", "Import integrity"),
    RuleCoverage("DATA-002", "Duplicate Employee ID", "Import integrity", register_level=True),
    RuleCoverage("DATA-003", "Negative Earning Component", "Import integrity"),
    RuleCoverage("DATA-004", "All Components Are Zero", "Import integrity"),
    RuleCoverage(
        "DATA-005", "Negative Deduction", "Import integrity",
        applies=STATED("pf_employee", "esic_employee", "pt", "pt_amount", "lwf_employee", "tds", "income_tax"),
        na_reason="The register states no deductions",
    ),
    RuleCoverage("DATA-006", "Duplicate PAN", "Import integrity", applies=STATED("pan"),
                 na_reason="No PAN on the register", register_level=True),
    RuleCoverage("DATA-007", "Duplicate UAN", "Import integrity", applies=STATED("uan"),
                 na_reason="No UAN on the register", register_level=True),
    RuleCoverage("DATA-008", "Duplicate Aadhaar", "Import integrity", applies=STATED("aadhaar", "aadhar"),
                 na_reason="No Aadhaar on the register", register_level=True),
    RuleCoverage("DATA-009", "Duplicate Bank Account", "Import integrity",
                 applies=STATED("bank_account", "account_number"),
                 na_reason="No bank account on the register", register_level=True),
    RuleCoverage(
        "DATA-010", "Work State Missing for State Deduction", "Import integrity",
        applies=lambda c: c.num("pt", "pt_amount") > 0 or c.num("lwf_employee") > 0,
        na_reason="No PT or LWF deducted",
    ),
    RuleCoverage(
        "DATA-011", "Bank Account Missing for Bank Payment", "Import integrity",
        applies=lambda c: str(c.row.get("payment_mode") or "").strip().casefold() in {"bank", "bank transfer", "neft"},
        na_reason="Payment mode is not a bank transfer, or is not stated",
    ),
    RuleCoverage(
        "DATA-012", "IFSC Missing for Bank Payment", "Import integrity",
        applies=lambda c: str(c.row.get("payment_mode") or "").strip().casefold() in {"bank", "bank transfer", "neft"},
        na_reason="Payment mode is not a bank transfer, or is not stated",
    ),
    RuleCoverage("DATA-PT-STATE", "PT State Not Mapped", "Configuration integrity",
                 applies=lambda c: c.pt_states_configured, na_reason="No PT states configured"),
    RuleCoverage("DATA-LWF-STATE", "LWF State Not Mapped", "Configuration integrity",
                 applies=lambda c: c.lwf_states_configured, na_reason="No LWF states configured"),
    RuleCoverage("DATA-PT-RATE", "PT Rate Version Missing", "Configuration integrity",
                 applies=lambda c: bool(c.res("pt_applicable_state")), na_reason="No PT state for this employee"),
    RuleCoverage("DATA-LWF-RATE", "LWF Rate Version Missing", "Configuration integrity",
                 applies=lambda c: bool(c.res("lwf_applicable_state")), na_reason="No LWF state for this employee"),
    RuleCoverage("COMP-001", "Unmapped Column in Register", "Import integrity", register_level=True),
    RuleCoverage("COMP-002", "PF Component Missing from Register", "Import integrity"),

    # Salary structure ------------------------------------------------------
    RuleCoverage("STRUCT-001", "Low PF Wage — Possible PF Avoidance", "Salary structure",
                 applies=lambda c: _gross(c) > 0 and Decimal(str(c.res("pf_wage") or 0)) > 0,
                 na_reason="No gross or no PF wage"),
    RuleCoverage("STRUCT-002", "Allowance-Heavy Salary Structure", "Salary structure",
                 applies=lambda c: _gross(c) > 0 and Decimal(str(c.res("pf_wage") or 0)) > 0,
                 na_reason="No gross or no PF wage"),
    RuleCoverage("AGG-001", "Gross Pay Mismatch", "Salary structure",
                 requires=(("stated gross", STATED("gross", "gross_salary", "gross_pay", "total_gross")),)),
    RuleCoverage("AGG-002", "Net Pay Mismatch", "Salary structure",
                 requires=(("stated net", STATED("net", "net_salary", "net_pay", "take_home")),
                           ("stated gross", STATED("gross", "gross_salary", "gross_pay", "total_gross")),
                           ("stated total deductions", STATED("total_deductions", "total_deduction")))),
    RuleCoverage("AGG-003", "Zero Net Pay for Active Employee", "Salary structure",
                 requires=(("stated net", STATED("net", "net_salary", "net_pay", "take_home")),
                           ("paid days", STATED("paid_days")))),
    RuleCoverage("AGG-004", "Negative Net Pay", "Salary structure",
                 requires=(("stated net", STATED("net", "net_salary", "net_pay", "take_home")),)),

    # Statutory contributions -----------------------------------------------
    RuleCoverage(
        "STAT-001", "PF Employee Contribution", "Statutory",
        applies=lambda c: _pf_expected(c) > 0 or c.stated("pf_employee", "pf_emp"),
        na_reason="No PF due and none deducted",
        requires=(("PF employee column", STATED("pf_employee", "pf_emp")),),
        material=True, cannot_marker=_missing_actual,
    ),
    RuleCoverage(
        "PF-009", "PF Restriction Basis", "Statutory",
        applies=STATED("pf_employee", "pf_emp"), na_reason="No PF deduction stated",
    ),
    RuleCoverage(
        "STAT-002", "PF Employer Contribution", "Statutory",
        applies=lambda c: Decimal(str(c.res("pf_amount_employer") or 0)) > 0 or c.stated("pf_employer", "pf_employer_total"),
        na_reason="No employer PF due and none stated",
        requires=(("PF employer column", STATED("pf_employer", "pf_employer_total")),),
        material=True,
    ),
    RuleCoverage("STAT-003", "PF Wage Above Ceiling (Uncapped Mode)", "Statutory",
                 applies=lambda c: c.res("pf_type") == "uncapped", na_reason="PF is on the restricted basis"),
    RuleCoverage("STAT-004", "PF Wage is Zero", "Statutory",
                 applies=lambda c: c.res("pf_type") == "uncapped", na_reason="PF is on the restricted basis"),
    RuleCoverage("STAT-005", "ESIC Eligibility", "Statutory",
                 applies=lambda c: Decimal(str(c.res("esic_wage") or 0)) > 0, na_reason="No ESIC wages"),
    RuleCoverage(
        "STAT-006", "ESIC Employee Contribution", "Statutory",
        applies=lambda c: _esic_eligible(c) or c.stated("esic_employee"),
        na_reason="Not ESIC-eligible and no ESIC deducted",
        requires=(("ESIC employee column", STATED("esic_employee")),),
        material=True, cannot_marker=_missing_actual,
    ),
    RuleCoverage(
        "STAT-007", "ESIC Employer Contribution", "Statutory",
        applies=lambda c: _esic_eligible(c) or c.stated("esic_employer"),
        na_reason="Not ESIC-eligible and no ESIC stated",
        requires=(("ESIC employer column", STATED("esic_employer")),),
        material=True,
    ),
    RuleCoverage(
        "STAT-008", "Professional Tax", "Statutory",
        applies=lambda c: Decimal(str(c.res("pt_due") or 0)) > 0 or (c.pt_states_configured and not c.res("pt_applicable_state")),
        na_reason="No PT due for this employee's state and wage",
        requires=(("PT state mapping", lambda c: bool(c.res("pt_applicable_state"))),
                  ("PT column", STATED("pt", "pt_amount"))),
        material=True, cannot_marker=_missing_actual,
    ),
    RuleCoverage(
        "STAT-009", "LWF Employee Contribution", "Statutory",
        applies=lambda c: Decimal(str(c.res("lwf_employee") or 0)) > 0,
        na_reason="No LWF due this month for this state",
        requires=(("LWF employee column", STATED("lwf_employee")),), material=True,
    ),
    RuleCoverage(
        "STAT-010", "LWF Employer Contribution", "Statutory",
        applies=lambda c: Decimal(str(c.res("lwf_employer") or 0)) > 0,
        na_reason="No LWF due this month for this state",
        requires=(("LWF employer column", STATED("lwf_employer")),), material=True,
    ),
    RuleCoverage("STAT-011", "TDS Risk — High Income Month", "Statutory"),
    RuleCoverage("STAT-014", "Gratuity Statutory Cap", "Statutory",
                 applies=lambda c: c.num("gratuity") > 0, na_reason="No gratuity paid"),
    RuleCoverage("PF-004", "EPS Contribution", "Statutory",
                 applies=lambda c: _pf_expected(c) > 0, na_reason="No PF due",
                 requires=(("EPS column", STATED("eps", "pf_eps", "eps_employer")),)),
    RuleCoverage("PF-008", "International Worker PF", "Statutory",
                 applies=lambda c: c.flag("international_worker"), na_reason="Not an international worker"),
    RuleCoverage("ESI-005", "Disability ESI Coverage", "Statutory",
                 applies=lambda c: c.flag("disability"), na_reason="No disability flag"),
    RuleCoverage("ESI-006", "Employee ESI Share on Exempt Daily Wage", "Statutory",
                 applies=lambda c: c.num("esic_employee") > 0, na_reason="No ESIC deducted"),
    RuleCoverage("PT-002", "PT Annual Cap", "Statutory",
                 applies=STATED("pt", "pt_amount"), na_reason="No PT stated"),
    RuleCoverage("PT-003", "PT in a No-PT State", "Statutory",
                 applies=lambda c: c.num("pt", "pt_amount") > 0, na_reason="No PT deducted",
                 requires=(("work state", STATED("state", "work_state", "state_pt", "location_state")),)),
    RuleCoverage("BON-001", "Bonus Eligibility Ceiling", "Statutory",
                 applies=lambda c: c.num("bonus") > 0, na_reason="No bonus paid"),
    RuleCoverage("BON-002", "Statutory Bonus Band", "Statutory",
                 applies=lambda c: c.num("bonus") > 0, na_reason="No bonus paid"),
    RuleCoverage("GRAT-002", "Gratuity Minimum Service", "Arrears and F&F",
                 applies=lambda c: c.num("gratuity") > 0, na_reason="No gratuity paid",
                 requires=(("date of joining", STATED("doj", "date_of_joining")),
                           ("date of leaving", STATED("dol", "date_of_leaving")))),
    RuleCoverage("GRAT-003", "Gratuity Formula", "Arrears and F&F",
                 applies=lambda c: c.num("gratuity") > 0, na_reason="No gratuity paid",
                 requires=(("date of joining", STATED("doj", "date_of_joining")),
                           ("date of leaving", STATED("dol", "date_of_leaving")))),
    RuleCoverage("TDS-001", "No-PAN TDS Rate (Sec 206AA)", "Statutory",
                 applies=lambda c: not c.stated("pan"), na_reason="PAN is on the register",
                 requires=(("TDS column", STATED("tds", "income_tax")),)),
    RuleCoverage("TDS-002", "Monthly TDS Against Projection", "Statutory",
                 applies=STATED("tds", "income_tax"), na_reason="No TDS stated"),

    # Attendance -------------------------------------------------------------
    RuleCoverage("LOP-001", "Paid Days + LOP Days = Days in Month", "Attendance",
                 requires=(("paid days", STATED("paid_days")), ("LOP days", STATED("lop_days", "lop")))),
    RuleCoverage("LOP-002", "LOP Proration", "Attendance",
                 applies=lambda c: c.num("lop_days", "lop") > 0, na_reason="No loss of pay",
                 requires=(("CTC record", lambda c: bool((c.res("lop_check") or {}).get("checked"))),)),
    RuleCoverage("LOP-003", "Paid Days Within the Month", "Attendance",
                 requires=(("paid days", STATED("paid_days")),)),
    RuleCoverage("ATT-001", "Paid Days Against Attendance", "Attendance",
                 applies=lambda c: c.has_attendance, na_reason="No attendance register for the month",
                 requires=(("attendance row", lambda c: c.attendance_record),)),
    RuleCoverage("ATT-002", "LOP Against Attendance", "Attendance",
                 applies=lambda c: c.has_attendance, na_reason="No attendance register for the month",
                 requires=(("attendance row", lambda c: c.attendance_record),)),
    RuleCoverage("ATT-003", "Attendance Record Present", "Attendance",
                 applies=lambda c: c.has_attendance, na_reason="No attendance register for the month"),
    RuleCoverage("ATT-004", "Paid Days Within Calendar Days", "Attendance",
                 applies=lambda c: c.has_attendance, na_reason="No attendance register for the month",
                 requires=(("attendance row", lambda c: c.attendance_record),)),
    *[
        RuleCoverage(rid, name, "Attendance", runs_in_validation=False,
                     na_reason="Checked when the attendance file is uploaded; a file that fails is refused")
        for rid, name in (
            ("ATT-010", "Attendance Days Reconcile"), ("ATT-011", "Paid Days Match Loss Of Pay"),
            ("ATT-012", "Calendar Days For The Month"), ("ATT-013", "Attendance Values Possible"),
            ("ATT-014", "No Duplicate Attendance Rows"),
        )
    ],
    RuleCoverage("ATT-015", "On Attendance But Not Paid", "Attendance", register_level=True,
                 applies=lambda c: c.has_attendance, na_reason="No attendance register for the month"),
    RuleCoverage("ATT-020", "Pay Reduced For Loss Of Pay", "Attendance",
                 applies=lambda c: c.attendance_record, na_reason="No attendance row for this employee"),
    RuleCoverage("ATT-021", "Paid With No Paid Days", "Attendance",
                 applies=lambda c: c.attendance_record, na_reason="No attendance row for this employee"),
    RuleCoverage("ATT-022", "Overtime Paid", "Attendance",
                 applies=lambda c: c.attendance_record, na_reason="No attendance row for this employee"),
    RuleCoverage("ATT-023", "Overtime Rate", "Attendance",
                 applies=lambda c: c.attendance_record, na_reason="No attendance row for this employee"),
    RuleCoverage("ATT-024", "Loss Of Pay Deduction Verifiable", "Attendance",
                 applies=lambda c: c.attendance_record, na_reason="No attendance row for this employee",
                 cannot_marker=lambda f: True),

    # Employee lifecycle -----------------------------------------------------
    RuleCoverage("MST-001", "In Employee Master", "Employee lifecycle",
                 requires=(("employee master", lambda c: c.has_master),)),
    RuleCoverage("MST-002", "Paid Before Joining", "Employee lifecycle",
                 requires=(("employee master", lambda c: c.has_master), ("master record", lambda c: c.master_record))),
    RuleCoverage("MST-003", "Paid After Exit", "Employee lifecycle",
                 requires=(("employee master", lambda c: c.has_master), ("master record", lambda c: c.master_record))),
    RuleCoverage("MST-004", "PF Deducted Without UAN", "Employee lifecycle",
                 applies=lambda c: c.num("pf_employee", "pf_emp") > 0, na_reason="No PF deducted",
                 requires=(("employee master", lambda c: c.has_master),)),
    RuleCoverage("MST-005", "ESIC Deducted Without IP Number", "Employee lifecycle",
                 applies=lambda c: c.num("esic_employee") > 0, na_reason="No ESIC deducted",
                 requires=(("employee master", lambda c: c.has_master),)),
    RuleCoverage("GRAT-004", "Gratuity Service Known", "Arrears and F&F",
                 applies=lambda c: c.num("gratuity") > 0, na_reason="No gratuity paid",
                 cannot_marker=lambda f: True),
    RuleCoverage("GRAT-005", "Gratuity Service Threshold", "Arrears and F&F",
                 applies=lambda c: c.num("gratuity") > 0, na_reason="No gratuity paid",
                 requires=(("employee master", lambda c: c.has_master),)),
    RuleCoverage("ID-001", "PAN Format", "Employee lifecycle", requires=(("PAN", STATED("pan")),)),
    RuleCoverage("ID-002", "Aadhaar Checksum", "Employee lifecycle", requires=(("Aadhaar", STATED("aadhaar", "aadhar")),)),
    RuleCoverage("ID-003", "UAN Present and Valid", "Employee lifecycle",
                 applies=lambda c: c.num("pf_employee", "pf_emp") > 0 or c.stated("uan"),
                 na_reason="No PF deducted and no UAN stated"),
    RuleCoverage("ID-004", "ESI Number Present and Valid", "Employee lifecycle",
                 applies=lambda c: c.num("esic_employee") > 0 or c.stated("esi_number", "esi_no", "ip_number"),
                 na_reason="No ESIC deducted and no ESI number stated"),
    RuleCoverage("ID-005", "IFSC Format", "Employee lifecycle", applies=STATED("ifsc", "ifsc_code"),
                 na_reason="No IFSC on the register"),
    RuleCoverage("ID-006", "Minimum Working Age", "Employee lifecycle",
                 requires=(("date of birth", STATED("dob", "date_of_birth")),)),
    RuleCoverage("ID-007", "Paid Before Date of Joining", "Employee lifecycle",
                 requires=(("date of joining", STATED("doj", "date_of_joining")),)),
    RuleCoverage("ID-008", "Salary After Exit", "Employee lifecycle",
                 applies=STATED("dol", "date_of_leaving"), na_reason="No date of leaving on the register"),

    # Period comparison ------------------------------------------------------
    RuleCoverage("MOM-001", "New Joiner", "Period comparison",
                 requires=(("previous month's register", lambda c: c.has_prior_register),)),
    *[
        RuleCoverage(rid, name, "Period comparison",
                     applies=lambda c: _continuing(c) or not c.has_prior_register,
                     na_reason="New joiner — no prior month to compare",
                     requires=(("previous month's register", lambda c: c.has_prior_register),))
        for rid, name in (
            ("MOM-002", "Component Spike"), ("MOM-003", "Component Drop"),
            ("MOM-004", "New Component"), ("MOM-005", "Component Missing vs Prior"),
            ("ADV-001", "Zero Salary — Continuing Employee"), ("ADV-002", "Salary Spike"),
            ("ADV-003", "Salary Drop"),
        )
    ],

    # Arrears ------------------------------------------------------------------
    RuleCoverage("ARR-001", "Arrear Period Stated", "Arrears and F&F", applies=_any_arrear,
                 na_reason="No arrears on this row", cannot_marker=lambda f: True),
    RuleCoverage("ARR-002", "Arrear Period Valid", "Arrears and F&F", applies=_any_arrear,
                 na_reason="No arrears on this row"),
    RuleCoverage("ARR-003", "Arrear Period Length", "Arrears and F&F", applies=_any_arrear,
                 na_reason="No arrears on this row"),
    RuleCoverage("ARR-004", "Arrear PF at Ceiling", "Arrears and F&F", applies=_any_arrear,
                 na_reason="No arrears on this row"),
    RuleCoverage("MOM-006", "Increment Arrear Amount", "Arrears and F&F",
                 applies=lambda c: bool(c.res("increment_arrear_total")),
                 na_reason="No increment arrear on this row",
                 requires=(("CTC revision", lambda c: bool((c.res("increment_arrear") or {}).get("applicable"))),)),

    # Minimum wage -----------------------------------------------------------
    RuleCoverage("MW-001", "Pay At or Above Minimum Wage", "Statutory",
                 applies=lambda c: c.res("minimum_wage_status") != "not_applicable",
                 na_reason="Minimum wage recorded as not applicable to this company",
                 requires=(("a minimum-wage applicability decision",
                            lambda c: c.res("minimum_wage_status") == "checked"),),
                 material=True),
    RuleCoverage("MW-003", "Minimum Wage Rate and Classification Available", "Statutory",
                 applies=lambda c: c.res("minimum_wage_status") == "checked",
                 na_reason="Minimum wage not checked for this company",
                 cannot_marker=lambda f: True),
]

BY_ID: dict[str, RuleCoverage] = {r.rule_id: r for r in REGISTRY}

#: Families in the order a reader works through them.
FAMILIES = (
    "Import integrity", "Configuration integrity", "Employee lifecycle", "Salary structure",
    "Statutory", "Attendance", "Arrears and F&F", "Period comparison",
)


# ---------------------------------------------------------------------------
# Deriving outcomes
# ---------------------------------------------------------------------------
def employee_outcomes(
    ctx: Context,
    findings: list[dict[str, Any]],
    suppressed: set[str],
    reasons: dict[str, str] | None = None,
) -> dict[str, Any]:
    """One employee's outcome on every registered check, in compact form.

    Stored for every employee of every run, so its size is the run's memory:
    97 small dicts per person was ~25 KB each and pushed an 8,000-employee
    validation past 500 MB. Passes are a list of ids; the other outcomes map
    id → reason, and reasons are shared strings (``reasons`` interns the
    per-employee "Not supplied: …" texts across a run). ``expand`` gives back
    the full ``{rule_id: {outcome, reason}}`` map for display.
    """
    intern = reasons if reasons is not None else {}
    by_rule: dict[str, list[dict[str, Any]]] = {}
    for f in findings:
        by_rule.setdefault(str(f.get("rule_id") or ""), []).append(f)

    out: dict[str, Any] = {PASSED: [], FAILED: {}, CANNOT: {}, NA: {}, DISABLED: []}
    for rule in REGISTRY:
        rid = rule.rule_id
        emitted = by_rule.get(rid, [])
        fails = [f for f in emitted if f.get("status") == "FAIL"]

        if rid in suppressed:
            out[DISABLED].append(rid)
            continue
        if not rule.runs_in_validation:
            out[NA][rid] = rule.na_reason
            continue
        if fails and rule.cannot_marker is not None and all(rule.cannot_marker(f) for f in fails):
            out[CANNOT][rid] = fails[0].get("reason") or "The input this check needs was not supplied"
            continue
        if fails:
            out[FAILED][rid] = fails[0].get("reason") or ""
            continue
        if any(f.get("status") == "PASS" for f in emitted):
            out[PASSED].append(rid)
            continue
        try:
            applies = rule.applies(ctx)
        except Exception:  # noqa: BLE001 — a gating error is a Cannot, never a pass
            applies = True
        if not applies:
            out[NA][rid] = rule.na_reason or "Does not apply"
            continue
        missing = []
        for label, present in rule.requires:
            try:
                ok = present(ctx)
            except Exception:  # noqa: BLE001
                ok = False
            if not ok:
                missing.append(label)
        if missing:
            text = "Not supplied: " + ", ".join(missing)
            out[CANNOT][rid] = intern.setdefault(text, text)
            continue
        out[PASSED].append(rid)
    return out


def counts_of(compact: dict[str, Any]) -> dict[str, int]:
    return {o: len(compact.get(o) or ()) for o in OUTCOMES}


def expand(compact: dict[str, Any] | None, findings: list[dict[str, Any]] | None = None) -> dict[str, dict[str, str]] | None:
    """The full ``{rule_id: {outcome, reason}}`` map, in registry order.

    Accepts the older per-rule form too, so a run recorded before the compact
    form was introduced still reads.
    """
    if not compact:
        return None
    if PASSED not in compact or not isinstance(compact.get(PASSED), list):
        return compact  # already the per-rule form
    pass_reason: dict[str, str] = {}
    for f in findings or []:
        if f.get("status") == "PASS" and f.get("reason"):
            pass_reason.setdefault(str(f.get("rule_id")), str(f["reason"]))
    where: dict[str, tuple[str, str]] = {}
    for rid in compact.get(PASSED) or []:
        where[rid] = (PASSED, pass_reason.get(rid, "Checked; nothing raised"))
    for rid in compact.get(DISABLED) or []:
        where[rid] = (DISABLED, "Switched off for this company")
    for outcome in (FAILED, CANNOT, NA):
        for rid, reason in (compact.get(outcome) or {}).items():
            where[rid] = (outcome, reason)
    return {
        r.rule_id: {"outcome": where[r.rule_id][0], "reason": where[r.rule_id][1]}
        for r in REGISTRY if r.rule_id in where
    }


def summarise(per_employee: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts by rule and outcome, plus the headline coverage figures."""
    rules: dict[str, dict[str, int]] = {r.rule_id: dict.fromkeys(OUTCOMES, 0) for r in REGISTRY}
    missing_inputs: dict[str, int] = {}
    for outcomes in per_employee:
        for outcome in OUTCOMES:
            for rule_id in outcomes.get(outcome) or ():
                rules[rule_id][outcome] += 1
        for reason in (outcomes.get(CANNOT) or {}).values():
            if reason.startswith("Not supplied: "):
                for label in reason[len("Not supplied: "):].split(", "):
                    missing_inputs[label] = missing_inputs.get(label, 0) + 1
    totals = dict.fromkeys(OUTCOMES, 0)
    for counts in rules.values():
        for k, v in counts.items():
            totals[k] += v
    assessed = totals[PASSED] + totals[FAILED]
    applicable = assessed + totals[CANNOT]
    material_cannot = sum(
        rules[r.rule_id][CANNOT] for r in REGISTRY if r.material
    )
    return {
        "totals": totals,
        # Of the checks that applied, how many could reach a verdict. The one
        # number that says whether "no failures" means anything.
        "coverage_pct": round(assessed * 100 / applicable, 1) if applicable else None,
        "material_cannot_validate": material_cannot,
        "missing_inputs": dict(sorted(missing_inputs.items(), key=lambda kv: -kv[1])),
        "rules": [
            {
                "rule_id": r.rule_id,
                "name": r.name,
                "family": r.family,
                "material": r.material,
                "runs_in_validation": r.runs_in_validation,
                "counts": rules[r.rule_id],
            }
            for r in REGISTRY
        ],
    }


# ---------------------------------------------------------------------------
# Applying it to a run
# ---------------------------------------------------------------------------
def annotate_run(
    db: Any,
    entity: Any,
    period_month: Any,
    results: list[dict[str, Any]],
    source_rows: list[dict[str, Any]],
    unmatched_findings: list[dict[str, Any]] | None,
    suppressed: set[str],
) -> dict[str, Any]:
    """
    Attach an outcome for every check to every employee's result, and return
    the run's coverage summary.

    Each result row gains ``coverage`` (compact; see ``employee_outcomes``) and
    ``coverage_counts``. The summary is what the results page and the
    evidence pack show beside — never merged into — the failure counts.
    """
    import calendar

    from sqlalchemy import func

    from app.models import SalaryRegisterRow, StatutorySettings
    from app.services.workforce import attendance_for_period, master_as_of

    period_month = period_month.replace(day=1)
    end = period_month.replace(day=calendar.monthrange(period_month.year, period_month.month)[1])
    prior = (
        period_month.replace(year=period_month.year - 1, month=12)
        if period_month.month == 1 else period_month.replace(month=period_month.month - 1)
    )
    master = master_as_of(db, entity.id, end)
    attendance = attendance_for_period(db, entity.id, period_month)
    has_prior = bool(
        db.query(func.count(SalaryRegisterRow.id))
        .filter(SalaryRegisterRow.entity_id == entity.id, SalaryRegisterRow.period_month == prior)
        .scalar()
    )
    settings = db.query(StatutorySettings).filter(StatutorySettings.entity_id == entity.id).first()
    pt_states = bool(settings and settings.pt_states)
    lwf_states = bool(settings and settings.lwf_states)

    by_eid: dict[str, dict[str, Any]] = {}
    for row in source_rows:
        key = str(row.get("employee_id") or row.get("emp_id") or row.get("employee_code") or "").strip()
        by_eid.setdefault(key, row)

    per_employee: list[dict[str, Any]] = []
    reasons: dict[str, str] = {}
    for result in results:
        eid = str(result.get("employee_id") or "")
        ctx = Context(
            row=by_eid.get(eid, {}),
            result=result,
            has_master=bool(master),
            master_record=eid in master,
            has_attendance=bool(attendance),
            attendance_record=eid in attendance,
            has_prior_register=has_prior,
            pt_states_configured=pt_states,
            lwf_states_configured=lwf_states,
        )
        outcomes = employee_outcomes(ctx, result.get("findings") or [], suppressed, reasons)
        result["coverage"] = outcomes
        result["coverage_counts"] = counts_of(outcomes)
        per_employee.append(outcomes)

    summary = summarise(per_employee)
    summary["unmatched_findings"] = len(unmatched_findings or [])
    summary["inputs"] = {
        "employee_master": bool(master),
        "attendance": bool(attendance),
        "previous_month_register": has_prior,
    }
    return summary
