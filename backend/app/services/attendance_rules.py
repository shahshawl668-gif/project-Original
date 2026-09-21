"""
Attendance, and the pay that should follow from it.

Attendance is the input payroll multiplies. Everything the register-level rules
check is downstream of it: PF on a wage that was already wrong, gross against
components that were already wrong. A month where someone was absent for five
days and paid for thirty passes every internal check the register has, because
the register is perfectly consistent with itself — it is consistent with the
wrong number of days.

Two things are validated here, and they are different jobs.

**The attendance file against itself.** Does it add up? Present plus paid leave
plus weekly off plus holiday plus loss of pay should be the month. Paid days
should be the month less loss of pay. A file that fails these is not a file
anyone can reconcile payroll against, and finding that out before it is
committed is worth more than finding it out afterwards.

**Pay against attendance.** This is the money. Five days of loss of pay should
remove five days of wages, and where it has not, someone has been overpaid by
that amount. Overtime hours worked should be overtime hours paid — under
Section 59 of the Factories Act, at twice ordinary wages.

What this module will not do
----------------------------
It will not guess a monthly wage. Checking a loss-of-pay deduction needs to
know what a full month would have paid, and the register only shows what *was*
paid — already reduced, or not, which is the very thing in question. So the
full-month figure is taken from the agreed CTC where one is uploaded, or from
a prior month that carried no loss of pay, and where neither exists the check
reports that it could not be performed rather than inventing a baseline. A
fabricated overpayment is worse than an unanswered question.
"""
from __future__ import annotations

import calendar as _calendar
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy.orm import Session

CENT = Decimal("0.01")

# The bases a company can divide a monthly wage by to get a daily rate. Each is
# in real use and they do not agree: 26 is the six-day week the Payment of
# Wages Act and the gratuity formula assume, 30 is the flat convention many
# payroll systems ship with, and the calendar is what the month actually held.
PAID_DAY_BASES: tuple[tuple[str, str, str], ...] = (
    ("calendar", "Calendar days",
     "The days the month actually has — 28, 29, 30 or 31. A day of loss of pay "
     "costs slightly more in February than in March."),
    ("fixed_26", "Fixed 26 days",
     "The six-day working week assumed by the Payment of Wages Act and by the "
     "gratuity formula. Weekly offs are not divided into the rate."),
    ("fixed_30", "Fixed 30 days",
     "A flat thirty regardless of the month. Simple, and what many payroll "
     "systems ship with."),
)

BASIS_LABELS = {key: label for key, label, _ in PAID_DAY_BASES}

# Component names that count as overtime pay. Matched on the normalised name,
# so "OT Amount" and "overtime_pay" both land.
OVERTIME_TOKENS = ("overtime", "_ot", "ot_", "_ot_")


def basis_catalogue() -> list[dict[str, str]]:
    return [{"key": key, "label": label, "hint": hint} for key, label, hint in PAID_DAY_BASES]


def _q(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _dec(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def days_in_month(period_month: date) -> Decimal:
    return Decimal(_calendar.monthrange(period_month.year, period_month.month)[1])


def paid_day_basis(period_month: date, basis: str) -> Decimal:
    """The divisor that turns a monthly wage into a daily rate."""
    if basis == "fixed_26":
        return Decimal("26")
    if basis == "fixed_30":
        return Decimal("30")
    return days_in_month(period_month)


def _finding(
    *,
    employee_id: str,
    employee_name: str | None,
    rule_id: str,
    rule_name: str,
    component: str,
    severity: str,
    reason: str,
    expected: Any = "",
    actual: Any = "",
    difference: Any = "",
    fix: str = "",
    impact: float = 0.0,
    status: str = "FAIL",
) -> dict:
    return {
        "employee_id": employee_id,
        "employee_name": employee_name or "",
        "rule_id": rule_id,
        "rule_name": rule_name,
        "component": component,
        "expected_value": str(expected),
        "actual_value": str(actual),
        "difference": str(difference),
        "severity": severity,
        "status": status,
        "reason": reason,
        "suggested_fix": fix,
        "financial_impact": float(impact),
    }


# ---------------------------------------------------------------------------
# The attendance file against itself
# ---------------------------------------------------------------------------
# Run on the parsed records *before* the gaps are derived. After derivation
# paid days and loss of pay always agree, because one was calculated from the
# other — so checking them afterwards would pass every file, including the ones
# that stated both and contradicted themselves.
def check_self_consistency(
    records: list[dict[str, Any]],
    period_month: date,
    *,
    day_tolerance: Decimal = Decimal("0.05"),
    require_days_reconcile: bool = True,
) -> list[dict]:
    """Everything wrong with an attendance file, judged without any other input."""
    period_month = period_month.replace(day=1)
    actual_days = days_in_month(period_month)
    findings: list[dict] = []
    seen: dict[str, int] = {}

    for record in records:
        employee_id = str(record.get("employee_id") or "").strip()
        if not employee_id:
            continue
        name = record.get("employee_name")
        seen[employee_id] = seen.get(employee_id, 0) + 1

        stated = {
            field: _dec(record.get(field))
            for field in ("calendar_days", "present_days", "paid_days", "lop_days",
                          "paid_leave_days", "weekly_off_days", "holiday_days",
                          "overtime_hours")
        }
        calendar_days = stated["calendar_days"] or actual_days

        # ---- impossible values ------------------------------------------
        for field, value in stated.items():
            if value is None:
                continue
            if value < 0:
                findings.append(_finding(
                    employee_id=employee_id, employee_name=name,
                    rule_id="ATT-013", rule_name="Impossible Attendance Value",
                    component=field, severity="CRITICAL",
                    expected=">= 0", actual=value,
                    reason=f"{field.replace('_', ' ')} is negative ({value}).",
                    fix="Correct the attendance export; a negative day count cannot be paid.",
                ))
            elif field != "overtime_hours" and value > calendar_days:
                findings.append(_finding(
                    employee_id=employee_id, employee_name=name,
                    rule_id="ATT-013", rule_name="Impossible Attendance Value",
                    component=field, severity="CRITICAL",
                    expected=f"<= {calendar_days}", actual=value,
                    difference=value - calendar_days,
                    reason=(
                        f"{field.replace('_', ' ')} is {value} in a month of "
                        f"{calendar_days} days."
                    ),
                    fix="Check for a doubled row or a mis-set month length.",
                ))

        # ---- the month the file thinks it is ----------------------------
        if stated["calendar_days"] is not None and stated["calendar_days"] != actual_days:
            findings.append(_finding(
                employee_id=employee_id, employee_name=name,
                rule_id="ATT-012", rule_name="Calendar Days Wrong For The Month",
                component="calendar_days", severity="WARNING",
                expected=actual_days, actual=stated["calendar_days"],
                difference=stated["calendar_days"] - actual_days,
                reason=(
                    f"The file states {stated['calendar_days']} days for "
                    f"{period_month:%B %Y}, which has {actual_days}."
                ),
                fix="Every per-day rate in the month is derived from this figure.",
            ))

        # ---- paid days against loss of pay ------------------------------
        # Only where the file stated both. A file that stated one and had the
        # other derived cannot disagree with itself, and flagging it would be
        # reporting our own arithmetic back at the client.
        paid, lop = stated["paid_days"], stated["lop_days"]
        if paid is not None and lop is not None:
            expected_paid = calendar_days - lop
            if abs(paid - expected_paid) > day_tolerance:
                findings.append(_finding(
                    employee_id=employee_id, employee_name=name,
                    rule_id="ATT-011", rule_name="Paid Days Do Not Match Loss Of Pay",
                    component="paid_days", severity="CRITICAL",
                    expected=expected_paid, actual=paid, difference=paid - expected_paid,
                    reason=(
                        f"{paid} days paid with {lop} days of loss of pay in a "
                        f"{calendar_days}-day month — the two do not reconcile."
                    ),
                    fix="One of the two columns is wrong. Payroll will use paid days.",
                ))

        # ---- the whole month accounted for ------------------------------
        parts = ("present_days", "paid_leave_days", "weekly_off_days",
                 "holiday_days", "lop_days")
        if require_days_reconcile and all(stated[p] is not None for p in parts):
            total = sum((stated[p] for p in parts), Decimal("0"))
            if abs(total - calendar_days) > day_tolerance:
                findings.append(_finding(
                    employee_id=employee_id, employee_name=name,
                    rule_id="ATT-010", rule_name="Attendance Days Do Not Reconcile",
                    component="present_days", severity="WARNING",
                    expected=calendar_days, actual=total, difference=total - calendar_days,
                    reason=(
                        f"Present {stated['present_days']} + paid leave "
                        f"{stated['paid_leave_days']} + weekly off "
                        f"{stated['weekly_off_days']} + holiday {stated['holiday_days']} "
                        f"+ loss of pay {stated['lop_days']} = {total}, against a month "
                        f"of {calendar_days} days."
                    ),
                    fix="Some days are counted twice or not at all. Find them before "
                        "this file is used to pay anyone.",
                ))

    # ---- the same person twice ------------------------------------------
    for employee_id, count in seen.items():
        if count > 1:
            name = next(
                (r.get("employee_name") for r in records
                 if str(r.get("employee_id") or "").strip() == employee_id), None
            )
            findings.append(_finding(
                employee_id=employee_id, employee_name=name,
                rule_id="ATT-014", rule_name="Duplicate Attendance Rows",
                component="employee_id", severity="CRITICAL",
                expected=1, actual=count, difference=count - 1,
                reason=f"This employee appears on {count} rows of the attendance file.",
                fix="Only the first row is stored. Remove the duplicates and re-upload, "
                    "or the days that get paid may not be the days that were worked.",
            ))

    return findings


# ---------------------------------------------------------------------------
# Pay against attendance
# ---------------------------------------------------------------------------
@dataclass
class FullMonthPay:
    """What a full month would have paid this employee, and where that came from."""

    amount: Decimal
    source: str  # "agreed CTC" | "prior month"


def full_month_reference(
    db: Session,
    entity_id: uuid.UUID,
    employee_id: str,
    period_month: date,
) -> FullMonthPay | None:
    """
    A full month's gross for one employee, or ``None`` where none can be had.

    The agreed CTC first — it is a contract rather than an observation, and it
    is unaffected by whatever happened to the month being checked. A prior
    month stands in where no CTC is on file, but only one that carried no loss
    of pay: a reduced month used as the baseline would make a second reduced
    month look correct.
    """
    from app.models import AttendanceRow, CtcRecord, SalaryRegisterRow

    period_month = period_month.replace(day=1)

    ctc = (
        db.query(CtcRecord)
        .filter(
            CtcRecord.entity_id == entity_id,
            CtcRecord.employee_id == employee_id,
            CtcRecord.effective_from <= period_month,
        )
        .order_by(CtcRecord.effective_from.desc())
        .first()
    )
    if ctc is not None and ctc.annual_components:
        annual = sum(
            (_dec(v) or Decimal("0") for v in ctc.annual_components.values()), Decimal("0")
        )
        if annual > 0:
            return FullMonthPay(_q(annual / Decimal("12")), "agreed CTC")

    previous = (
        db.query(SalaryRegisterRow)
        .filter(
            SalaryRegisterRow.entity_id == entity_id,
            SalaryRegisterRow.employee_id == employee_id,
            SalaryRegisterRow.period_month < period_month,
        )
        .order_by(SalaryRegisterRow.period_month.desc())
        .first()
    )
    if previous is None:
        return None

    prior_attendance = (
        db.query(AttendanceRow)
        .filter(
            AttendanceRow.entity_id == entity_id,
            AttendanceRow.employee_id == employee_id,
            AttendanceRow.period_month == previous.period_month,
        )
        .first()
    )
    prior_lop = _dec(getattr(prior_attendance, "lop_days", None))
    if prior_lop is None or prior_lop > 0:
        # No evidence the baseline month was a full one, so it is not a baseline.
        return None

    gross = sum(
        (_dec(v) or Decimal("0") for v in (previous.components or {}).values()), Decimal("0")
    )
    return FullMonthPay(_q(gross), f"{previous.period_month:%b %Y}") if gross > 0 else None


def check_pay_against_attendance(
    employee_id: str,
    name: str | None,
    row: dict[str, Any],
    attendance: Any,
    *,
    period_month: date,
    reference: FullMonthPay | None,
    basis: str = "calendar",
    day_tolerance: Decimal = Decimal("0.05"),
    lop_pay_tolerance_pct: Decimal = Decimal("2"),
    overtime_multiplier: Decimal = Decimal("2"),
    overtime_hours_per_day: Decimal = Decimal("8"),
) -> list[dict]:
    """What the register paid, against what attendance says it should have."""
    findings: list[dict] = []
    if attendance is None:
        return findings

    paid_days = _dec(getattr(attendance, "paid_days", None))
    lop_days = _dec(getattr(attendance, "lop_days", None))
    overtime_hours = _dec(getattr(attendance, "overtime_hours", None))
    gross = _dec(row.get("gross")) or Decimal("0")
    divisor = paid_day_basis(period_month, basis)

    # ---- paid nothing, still paid ---------------------------------------
    if paid_days is not None and paid_days <= day_tolerance and gross > 0:
        findings.append(_finding(
            employee_id=employee_id, employee_name=name,
            rule_id="ATT-021", rule_name="Paid With No Paid Days",
            component="gross", severity="CRITICAL",
            expected=0, actual=gross, difference=gross,
            reason=(
                f"Attendance records {paid_days} paid days for the month and "
                f"₹{gross:,.2f} was paid."
            ),
            fix="Either the attendance is wrong or this payment should not have been made.",
            impact=float(gross),
        ))
        return findings

    # ---- loss of pay that never reached the payslip ----------------------
    if lop_days is not None and lop_days > day_tolerance:
        if reference is None:
            findings.append(_finding(
                employee_id=employee_id, employee_name=name,
                rule_id="ATT-024", rule_name="Loss Of Pay Deduction Not Verifiable",
                component="gross", severity="INFO", status="INFO",
                expected="a full month's gross", actual="not available",
                reason=(
                    f"{lop_days} days of loss of pay were recorded, but there is no "
                    "agreed CTC and no earlier month without loss of pay to compare "
                    "against, so the deduction could not be checked."
                ),
                fix="Upload the CTC master, and the deduction is checked from next run.",
            ))
        else:
            daily = reference.amount / divisor
            expected_gross = _q(reference.amount - daily * lop_days)
            tolerance = _q(reference.amount * lop_pay_tolerance_pct / Decimal("100"))
            overpaid = _q(gross - expected_gross)
            if overpaid > tolerance:
                findings.append(_finding(
                    employee_id=employee_id, employee_name=name,
                    rule_id="ATT-020", rule_name="Pay Not Reduced For Loss Of Pay",
                    component="gross", severity="CRITICAL",
                    expected=expected_gross, actual=gross, difference=overpaid,
                    reason=(
                        f"{lop_days} days of loss of pay against a full month of "
                        f"₹{reference.amount:,.2f} ({reference.source}) should have paid "
                        f"₹{expected_gross:,.2f} on a {BASIS_LABELS.get(basis, basis).lower()} "
                        f"basis. ₹{gross:,.2f} was paid."
                    ),
                    fix=(
                        f"Recover ₹{overpaid:,.2f}, or correct the attendance if the "
                        "days were not in fact lost."
                    ),
                    impact=float(overpaid),
                ))

    # ---- overtime worked, overtime not paid ------------------------------
    if overtime_hours is not None and overtime_hours > 0:
        paid_overtime = _overtime_paid(row)
        if paid_overtime <= 0:
            impact = Decimal("0")
            detail = ""
            if reference is not None:
                hourly = reference.amount / divisor / overtime_hours_per_day
                impact = _q(hourly * overtime_multiplier * overtime_hours)
                detail = f" At {overtime_multiplier}× ordinary wages that is ₹{impact:,.2f}."
            findings.append(_finding(
                employee_id=employee_id, employee_name=name,
                rule_id="ATT-022", rule_name="Overtime Worked But Not Paid",
                component="overtime_hours", severity="WARNING",
                expected=f"> 0 ({overtime_multiplier}x ordinary)", actual=0,
                reason=(
                    f"{overtime_hours} overtime hours were recorded and the register "
                    f"carries no overtime payment.{detail} Section 59 of the Factories "
                    f"Act requires twice ordinary wages for overtime."
                ),
                fix="Pay the overtime, or correct the hours if they were not worked.",
                impact=float(impact),
            ))
        elif reference is not None:
            hourly = reference.amount / divisor / overtime_hours_per_day
            required = _q(hourly * overtime_multiplier * overtime_hours)
            shortfall = _q(required - paid_overtime)
            if shortfall > Decimal("1"):
                findings.append(_finding(
                    employee_id=employee_id, employee_name=name,
                    rule_id="ATT-023", rule_name="Overtime Paid Below The Statutory Rate",
                    component="overtime_hours", severity="WARNING",
                    expected=required, actual=paid_overtime, difference=shortfall,
                    reason=(
                        f"{overtime_hours} hours at {overtime_multiplier}× the ordinary "
                        f"rate comes to ₹{required:,.2f}; ₹{paid_overtime:,.2f} was paid."
                    ),
                    fix="Check the overtime rate against the Factories Act and any "
                        "applicable state rule or settlement.",
                    impact=float(shortfall),
                ))

    return findings


def _overtime_paid(row: dict[str, Any]) -> Decimal:
    """Whatever the register paid that reads as overtime."""
    from app.services.payroll_parse import normalize_col

    total = Decimal("0")
    for key, value in row.items():
        if key is None:
            continue
        name = normalize_col(str(key))
        padded = f"_{name}_"
        if any(
            (token in padded) if token.startswith("_") or token.endswith("_") else (token in name)
            for token in OVERTIME_TOKENS
        ):
            total += _dec(value) or Decimal("0")
    return total


def check_worked_but_unpaid(
    attendance: dict[str, Any],
    paid_employee_ids: set[str],
) -> list[dict]:
    """
    Anyone on the attendance register who is on no payslip.

    The mirror of ATT-003, and the more serious direction: a person paid
    without attendance is a control weakness, a person who attended without
    being paid is an unpaid worker.
    """
    findings: list[dict] = []
    for employee_id, row in attendance.items():
        if employee_id in paid_employee_ids:
            continue
        paid_days = _dec(getattr(row, "paid_days", None))
        if paid_days is None or paid_days <= 0:
            # Nothing to pay, so nothing is owed.
            continue
        findings.append(_finding(
            employee_id=employee_id,
            employee_name=getattr(row, "employee_name", None),
            rule_id="ATT-015", rule_name="On Attendance But Not Paid",
            component="paid_days", severity="CRITICAL",
            expected="a payslip", actual="not on the register",
            reason=(
                f"Attendance records {paid_days} paid days for this employee and the "
                "salary register does not contain them."
            ),
            fix="Establish whether they were paid outside this register. If not, they "
                "have worked and not been paid.",
        ))
    return findings
