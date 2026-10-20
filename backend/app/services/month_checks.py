"""
The month's input and master-data checks that sit beside the statutory engine.

Each looks at one employee's row together with the employee master and last
month's stored row, and reports what a payroll processor checks before signing
a month off: a PF member with no UAN, a held salary paid, an EPS exclusion the
new ceiling no longer allows, an arrear paid twice, a LOP reversal for LOP that
never happened, a one-time payment with no approval.

Kept apart from ``rule_engine_v2.build_findings`` because these need the master
record and history, which that function deliberately does not take.
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from app.services.rule_engine_v2 import ValidationFinding, stated

HELD = {"on hold", "hold", "salary hold", "absconding", "absconded", "suspended", "held"}
ONE_TIME_TOKENS = ("incentive", "reimbursement", "reimb", "commission", "award", "referral",
                   "joining_bonus", "retention", "recovery", "emi")
ONE_TIME_FIELDS = {"loan_recovery": "loan EMI", "notice_period_recovery": "notice recovery"}
OVERTIME_KEYS = ("overtime", "ot")
EPS_CHANGE = date(2026, 9, 17)


def _d(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(value).replace(",", ""))
    except Exception:
        return Decimal("0")


def _blank(value: Any) -> bool:
    return value is None or str(value).strip() in ("", "nan", "None", "0")


def _words(key: str) -> list[str]:
    return [w for w in key.split("_") if w]


def _money(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'))}"


def employee_month_checks(
    *,
    eid: str,
    ename: str | None,
    row: dict[str, Any],
    master: Any,
    prior: Any,
    period_month: date | None,
    days_in_month: int,
    paid_days: Decimal | None,
    regular: dict[str, Decimal],
    arrear_total: Decimal,
    comp_by_key: dict[str, Any],
    pf_calc: dict[str, Any],
    esic_calc: dict[str, Any],
    ctc_monthly: dict[str, Decimal],
    mid_month_revision: bool,
    revision_from: date | None,
    arrears_paid_before: list[tuple[date, Decimal]],
    age: float | None,
    tolerance: Decimal = Decimal("1"),
    change_pct: Decimal = Decimal("10"),
    explained: bool = False,
) -> list[ValidationFinding]:
    out: list[ValidationFinding] = []

    def add(rule_id, rule_name, component, expected, actual, severity, reason, fix, impact=0.0):
        out.append(ValidationFinding(
            employee_id=eid, employee_name=ename, rule_id=rule_id, rule_name=rule_name, component=component,
            expected_value=str(expected), actual_value=str(actual), difference="", severity=severity,
            status="FAIL", reason=reason, suggested_fix=fix, financial_impact=float(impact),
        ))

    pf_due = _d(pf_calc.get("pf_employee"))
    pf_paid = _d(stated(row, "pf_employee", "pf_emp"))
    esic_due = _d(esic_calc.get("esic_employee"))
    esic_paid = _d(row.get("esic_employee"))
    gross = sum(regular.values(), Decimal("0")) + arrear_total
    net = _d(stated(row, "net", "net_pay"))

    # ── EPS: an exclusion the new ceiling no longer allows ──────────────────
    ceiling = _d(pf_calc.get("_ceiling"))
    full_wage = _d(pf_calc.get("_pf_wage_full"))
    if paid_days and Decimal("0") < paid_days < Decimal(days_in_month):
        full_wage = full_wage * Decimal(days_in_month) / paid_days
    if (master is not None and master.eps_member is False and period_month and pf_due > 0
            and period_month >= EPS_CHANGE.replace(day=1)
            and ceiling >= Decimal("15000") and full_wage <= ceiling and (age is None or age < 58)):
        add("PF-010", "EPS Exclusion No Longer Valid", "eps_member", "EPS member", "excluded", "WARNING",
            f"The master keeps this employee out of EPS, but the PF wage of ₹{_money(full_wage)} is within the "
            f"₹{ceiling:,.0f} ceiling. Members excluded for earning above ₹15,000 and earning up to ₹25,000 are "
            "brought into EPS from 17 September 2026.",
            "Mark the employee as an EPS member in the master and route 8.33% of the capped wage to EPS.")

    # ── Statutory numbers for everyone who is due, not only those deducted ──
    uan = row.get("uan") or (master.uan if master is not None else None)
    if pf_due > 0 and pf_paid <= 0 and _blank(uan):
        add("MST-007", "PF Due but No UAN", "uan", "UAN", "(missing)", "WARNING",
            f"Employee PF of ₹{_money(pf_due)} is due this month and there is no UAN on the register or the master "
            "— typical of someone newly covered when the ceiling rose to ₹25,000.",
            "Generate the UAN and record it in the employee master before the ECR is filed.")
    ip = row.get("esi_number") or (master.esic_ip_number if master is not None else None)
    if esic_calc.get("esic_eligible") and esic_due > 0 and esic_paid <= 0 and _blank(ip):
        add("MST-008", "ESIC Covered but No IP Number", "esi_number", "IP number", "(missing)", "WARNING",
            f"The employee is covered by ESIC (₹{_money(esic_due)} due) and has no insurance number on the "
            "register or the master.",
            "Register the employee on the ESIC portal and record the IP number in the master.")

    # ── Held salaries ───────────────────────────────────────────────────────
    status = str(getattr(master, "employment_status", None) or "").strip().casefold()
    if status in HELD and (net > 0 or gross > 0):
        add("MST-009", "Salary Paid While On Hold", "employment_status", "salary held", status, "CRITICAL",
            f"The master marks this employee as '{status}', yet the register pays "
            f"₹{_money(net if net > 0 else gross)}.",
            "Hold the payment, or update the employee's status in the master if it has changed.",
            float(net if net > 0 else gross))

    # ── Voluntary PF only where declared ────────────────────────────────────
    vpf = _d(stated(row, "vpf", "voluntary_pf"))
    if vpf > 0 and not (master is not None and master.vpf_declared is True):
        add("PF-014", "VPF Without a Declaration", "vpf", "declared in the master", "not declared", "WARNING",
            f"Voluntary PF of ₹{_money(vpf)} is deducted, but the master has no VPF declaration for the employee.",
            "Record the employee's VPF declaration in the master, or stop the deduction and refund it.",
            float(vpf))

    # ── Bank details ────────────────────────────────────────────────────────
    if master is not None:
        on_row = str(row.get("bank_account") or "").strip()
        in_master = str(master.bank_account or "").strip()
        if on_row and in_master and on_row != in_master:
            add("DATA-014", "Bank Account Differs From the Master", "bank_account", in_master, on_row, "WARNING",
                "The account the register pays into is not the one in the employee master.",
                "Confirm which account is right; update the master with proof of the change.")
        changed = master.bank_changed_on
        if changed and period_month and (changed.year, changed.month) == (period_month.year, period_month.month) \
                and _blank(master.bank_change_proof):
            add("DATA-013", "Bank Account Changed Without Proof", "bank_change_proof", "proof on file", "(none)",
                "WARNING",
                f"The salary account changed on {changed.isoformat()} and no proof (cancelled cheque, bank letter) "
                "is recorded for it.",
                "Record the proof reference in the employee master before paying into the new account.")

    # ── One-time inputs need an approval and the right month ────────────────
    items = [k.replace("_", " ") for k, v in regular.items()
             if v > 0 and any(t in _words(k) or t in k for t in ONE_TIME_TOKENS)]
    items += [label for field, label in ONE_TIME_FIELDS.items() if _d(row.get(field)) > 0]
    if items:
        approval = row.get("one_time_approval")
        if _blank(approval):
            add("OTI-001", "One-Time Input Without Approval", "one_time_approval", "approval reference",
                "(none)", "WARNING",
                f"{', '.join(items).capitalize()} paid or recovered this month with no approval reference on the row.",
                "Add the approval reference (an 'Approval Ref' column) for each one-time input.")
        stated_month = row.get("one_time_month")
        if not _blank(stated_month) and period_month:
            text = str(stated_month).strip()[:7]
            if text and text != period_month.isoformat()[:7]:
                add("OTI-002", "One-Time Input For Another Month", "one_time_month",
                    period_month.isoformat()[:7], text, "WARNING",
                    f"The one-time inputs on this row are marked for {text}, but this register is for "
                    f"{period_month:%B %Y}.",
                    "Move the input to the month it belongs to, or correct the month on the row.")

    # ── LOP reversals ───────────────────────────────────────────────────────
    reversal_days = _d(row.get("previous_months_lop_days"))
    if reversal_days > 0:
        earlier = _d(getattr(prior, "lop_days", None)) if prior is not None else Decimal("0")
        if earlier < reversal_days:
            add("LOP-004", "LOP Reversal Without Earlier LOP", "previous_months_lop_days", f"≤ {earlier}",
                str(reversal_days), "WARNING",
                f"{reversal_days} days of LOP are reversed this month, but last month's register shows only "
                f"{earlier} days of LOP.",
                "Check the reversal against the month the LOP was taken; reverse only LOP actually deducted.")
        amount = _d(row.get("lop_reversal_amount"))
        if amount > 0 and ctc_monthly and period_month:
            prev = period_month.replace(day=1) - timedelta(days=1)
            due = sum(ctc_monthly.values(), Decimal("0")) * reversal_days / Decimal(prev.day)
            if (amount - due).copy_abs() > tolerance:
                add("LOP-005", "LOP Reversal Amount Wrong", "lop_reversal_amount", _money(due), _money(amount),
                    "WARNING",
                    f"{reversal_days} days reversed at last month's daily rate come to ₹{_money(due)}; the register "
                    f"pays ₹{_money(amount)}.",
                    "Recompute the reversal on the monthly salary divided by last month's days.",
                    float((amount - due).copy_abs()))

    # ── Overtime is part of the ESIC wage ───────────────────────────────────
    if esic_calc.get("esic_eligible"):
        ot = sum((v for k, v in regular.items()
                  if (k in OVERTIME_KEYS or "overtime" in k) and comp_by_key.get(k) is not None
                  and not comp_by_key[k].esic_applicable), Decimal("0"))
        if ot > 0:
            rate = Decimal(str(esic_calc.get("_emp_rate") or "0.0075"))
            add("ESI-009", "Overtime Left Out of the ESIC Wage", "overtime", "included", "excluded", "WARNING",
                f"Overtime of ₹{_money(ot)} is paid to an ESIC-covered employee but the Overtime component is not "
                "ESIC-applicable. ESIC is due on actual gross wages, overtime included.",
                "Mark the Overtime component ESIC-applicable under Salary components.",
                math.ceil(float(ot * rate)))

    # ── An arrear paid once only ────────────────────────────────────────────
    if arrear_total > 0 and revision_from:
        for month, paid in arrears_paid_before:
            if month >= revision_from.replace(day=1) and paid > 0:
                add("ARR-005", "Arrear Already Paid", "arrear", "paid once", f"also paid in {month:%B %Y}",
                    "WARNING",
                    f"An arrear of ₹{_money(arrear_total)} is paid this month for the revision effective "
                    f"{revision_from.isoformat()}, and {month:%B %Y} already paid ₹{_money(paid)} of arrears.",
                    "Check that the months are not being settled twice; pay only what the earlier arrear left out.",
                    float(min(arrear_total, paid)))
                break

    # ── Every component prorated on the same days ───────────────────────────
    if ctc_monthly and not mid_month_revision and paid_days is not None and days_in_month:
        implied = {}
        for key, amount in regular.items():
            full = ctc_monthly.get(key)
            if full and full > 0 and amount > 0:
                implied[key] = amount / full * Decimal(days_in_month)
        if len(implied) >= 2:
            low, high = min(implied.values()), max(implied.values())
            if high - low > Decimal("0.5"):
                parts = ", ".join(f"{k.replace('_', ' ')} {v.quantize(Decimal('0.1'))}" for k, v in implied.items())
                add("LOP-006", "Components Prorated On Different Days", "paid_days", "same days for every component",
                    parts, "WARNING",
                    f"Measured against the CTC, the components are paid for different numbers of days ({parts}).",
                    "Prorate every component on the same paid days and month-day basis.")
    # ── Net pay against last month ──────────────────────────────────────────
    # Measured before income tax: TDS is re-projected every month and moves with any earning.
    prior_net = _d(getattr(prior, "net_pay", None)) if prior is not None else Decimal("0")
    if prior_net > 0:
        prior_net += _d((getattr(prior, "deductions", None) or {}).get("tds"))
    if net > 0:
        net += _d(stated(row, "tds", "income_tax"))
    if prior_net > 0 and net > 0 and not explained:
        prior_lop = getattr(prior, "lop_days", None)
        this_lop = _d(stated(row, "lop_days", "lop"))
        days_moved = prior_lop is not None and _d(prior_lop) != this_lop
        prior_gross = sum((_d(v) for v in (getattr(prior, "components", None) or {}).values()), Decimal("0"))
        # An earning that moved (overtime, an increment) moves gross and net together and is
        # reported on its own component. What is left is net pay moved by a deduction.
        unexplained = (net - prior_net) - (gross - prior_gross if prior_gross > 0 else Decimal("0"))
        moved = unexplained / prior_net * 100
        if abs(moved) > change_pct and not days_moved and arrear_total <= 0:
            add("ADV-004", "Net Pay Changed Without a Reason", "net", f"within ±{change_pct}% of ₹{_money(prior_net)}",
                _money(net), "WARNING",
                f"Net pay before income tax moved by ₹{_money(unexplained)} ({moved:+.1f}%) more than gross did "
                f"(₹{_money(prior_net)} → ₹{_money(net)}), with the same paid days, no arrears and no CTC "
                "revision in the master.",
                "Find the deduction that moved and record why, or correct it.",
                float(unexplained.copy_abs()))
    return out
