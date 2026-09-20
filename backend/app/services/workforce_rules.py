"""
Rules that compare the salary register against its inputs.

Everything the existing rule engine checks is internal to the register: does
PF match the PF wage, does gross match its components, did a component jump
since last month. Those checks cannot see a wrong input that was processed
consistently — an employee paid for a month before they joined, or two months
after they left, passes every one of them.

These rules close that gap by validating the register against the employee
master and the attendance register. They only run for employees the relevant
input actually covers: a client who has not uploaded attendance gets silence
from the attendance rules rather than a screenful of false positives.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.services.workforce import attendance_for_period, master_as_of, service_years

# Attendance figures are quoted to half-days in most systems; a difference
# smaller than this is rounding, not a discrepancy.
DAY_TOLERANCE = Decimal("0.05")


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


def _dec(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def check_against_inputs(
    db: Session,
    entity_id: uuid.UUID,
    *,
    period_month: date,
    rows: list[dict[str, Any]],
    gratuity_min_service_years: Decimal = Decimal("5"),
) -> dict[str, list[dict]]:
    """
    Validate register rows against the master and attendance for the period.

    ``rows`` are dicts carrying at least ``employee_id``; ``employee_name``,
    ``paid_days``, ``lop_days``, ``gross`` and the statutory amounts are used
    where present. Returns findings keyed by employee id.
    """
    period_month = period_month.replace(day=1)
    month_end = _month_end(period_month)

    master = master_as_of(db, entity_id, month_end)
    attendance = attendance_for_period(db, entity_id, period_month)

    # Without either input there is nothing to compare against, and reporting
    # every employee as unverifiable would be noise rather than information.
    have_master = bool(master)
    have_attendance = bool(attendance)

    out: dict[str, list[dict]] = {}
    for row in rows:
        employee_id = str(row.get("employee_id") or "").strip()
        if not employee_id:
            continue
        name = row.get("employee_name")
        findings: list[dict] = []

        record = master.get(employee_id)
        if have_master:
            findings.extend(_master_rules(employee_id, name, row, record, period_month, month_end,
                                          gratuity_min_service_years))
        if have_attendance:
            findings.extend(_attendance_rules(employee_id, name, row, attendance.get(employee_id)))

        if findings:
            out[employee_id] = findings
    return out


def _month_end(period_month: date) -> date:
    import calendar as _calendar

    return date(
        period_month.year,
        period_month.month,
        _calendar.monthrange(period_month.year, period_month.month)[1],
    )


def _master_rules(
    employee_id: str,
    name: str | None,
    row: dict,
    record,
    period_month: date,
    month_end: date,
    gratuity_min_service_years: Decimal,
) -> list[dict]:
    findings: list[dict] = []
    gross = _dec(row.get("gross")) or Decimal("0")

    if record is None:
        findings.append(
            _finding(
                employee_id=employee_id, employee_name=name,
                rule_id="MST-001", rule_name="Not in Employee Master",
                component="employee", severity="CRITICAL",
                reason="Paid in this register but absent from the employee master.",
                fix="Add the employee to the master, or confirm the payment is legitimate.",
                impact=float(gross),
            )
        )
        return findings

    # Paid before joining — usually a data error, occasionally something worse.
    if record.date_of_joining and record.date_of_joining > month_end:
        findings.append(
            _finding(
                employee_id=employee_id, employee_name=name,
                rule_id="MST-002", rule_name="Paid Before Joining",
                component="employee", severity="CRITICAL",
                expected=f"joins {record.date_of_joining.isoformat()}",
                actual=f"paid for {period_month.strftime('%b %Y')}",
                reason=(
                    f"Joining date {record.date_of_joining.isoformat()} is after the end of "
                    f"this pay period."
                ),
                fix="Correct the joining date, or remove the payment.",
                impact=float(gross),
            )
        )

    # Paid after exit. The single most expensive thing this tool can catch,
    # because it keeps recurring until someone notices.
    if record.date_of_exit and record.date_of_exit < period_month:
        findings.append(
            _finding(
                employee_id=employee_id, employee_name=name,
                rule_id="MST-003", rule_name="Paid After Exit",
                component="employee", severity="CRITICAL",
                expected=f"exited {record.date_of_exit.isoformat()}",
                actual=f"paid for {period_month.strftime('%b %Y')}",
                reason=(
                    f"Exit date {record.date_of_exit.isoformat()} precedes this pay period, "
                    f"but the employee is still on the register."
                ),
                fix="Stop the payment and recover it, or correct the exit date.",
                impact=float(gross),
            )
        )

    # Statutory identifiers, checked only where the deduction implies one.
    if (_dec(row.get("pf_employee")) or Decimal("0")) > 0 and not record.uan:
        findings.append(
            _finding(
                employee_id=employee_id, employee_name=name,
                rule_id="MST-004", rule_name="PF Deducted Without UAN",
                component="uan", severity="CRITICAL",
                reason="PF was deducted but the master carries no UAN, so the ECR cannot be filed for this member.",
                fix="Capture the UAN, or generate one before the next filing.",
            )
        )

    if (_dec(row.get("esic_employee")) or Decimal("0")) > 0 and not record.esic_ip_number:
        findings.append(
            _finding(
                employee_id=employee_id, employee_name=name,
                rule_id="MST-005", rule_name="ESIC Deducted Without IP Number",
                component="esic_ip_number", severity="CRITICAL",
                reason="ESIC was deducted but the master carries no insurance number.",
                fix="Capture the IP number so the contribution can be credited.",
            )
        )

    # Gratuity service years — previously not checkable at all without a
    # joining date, which is what the master now supplies.
    gratuity_paid = _dec(row.get("gratuity")) or Decimal("0")
    if gratuity_paid > 0:
        years = service_years(record.date_of_joining, record.date_of_exit or month_end)
        if years is None:
            findings.append(
                _finding(
                    employee_id=employee_id, employee_name=name,
                    rule_id="GRAT-004", rule_name="Gratuity — Service Years Unknown",
                    component="gratuity", severity="INFO",
                    reason="Gratuity was paid but the master carries no joining date, so eligibility cannot be checked.",
                    fix="Add the joining date to the employee master.",
                )
            )
        elif Decimal(str(years)) < gratuity_min_service_years:
            findings.append(
                _finding(
                    employee_id=employee_id, employee_name=name,
                    rule_id="GRAT-005", rule_name="Gratuity Below Service Threshold",
                    component="gratuity", severity="WARNING",
                    expected=f">= {gratuity_min_service_years} years",
                    actual=f"{years} years",
                    reason=(
                        f"Gratuity of {gratuity_paid} paid on {years} years of service, below the "
                        f"{gratuity_min_service_years}-year threshold."
                    ),
                    fix="Confirm this is death/disablement or a contractual payment above the statute.",
                    impact=float(gratuity_paid),
                )
            )

    return findings


def _attendance_rules(employee_id: str, name: str | None, row: dict, attendance) -> list[dict]:
    if attendance is None:
        return [
            _finding(
                employee_id=employee_id, employee_name=name,
                rule_id="ATT-003", rule_name="No Attendance Record",
                component="paid_days", severity="WARNING",
                reason="Paid in this register but absent from the attendance register for the month.",
                fix="Confirm the attendance upload covers every paid employee.",
            )
        ]

    findings: list[dict] = []

    register_paid = _dec(row.get("paid_days"))
    attendance_paid = _dec(attendance.paid_days)
    if register_paid is not None and attendance_paid is not None:
        difference = register_paid - attendance_paid
        if abs(difference) > DAY_TOLERANCE:
            # Value the gap at the employee's own daily rate where the register
            # gives one, so the number means something to whoever fixes it.
            gross = _dec(row.get("gross")) or Decimal("0")
            daily = gross / register_paid if register_paid and register_paid > 0 else Decimal("0")
            findings.append(
                _finding(
                    employee_id=employee_id, employee_name=name,
                    rule_id="ATT-001", rule_name="Paid Days Differ From Attendance",
                    component="paid_days", severity="CRITICAL",
                    expected=attendance_paid, actual=register_paid, difference=difference,
                    reason=(
                        f"Payroll paid {register_paid} days but attendance records "
                        f"{attendance_paid}."
                    ),
                    fix="Reconcile the attendance feed with the payroll input.",
                    impact=float(abs(daily * difference)),
                )
            )

    register_lop = _dec(row.get("lop_days"))
    attendance_lop = _dec(attendance.lop_days)
    if register_lop is not None and attendance_lop is not None:
        difference = register_lop - attendance_lop
        if abs(difference) > DAY_TOLERANCE:
            findings.append(
                _finding(
                    employee_id=employee_id, employee_name=name,
                    rule_id="ATT-002", rule_name="LOP Differs From Attendance",
                    component="lop_days", severity="WARNING",
                    expected=attendance_lop, actual=register_lop, difference=difference,
                    reason=f"Payroll applied {register_lop} LOP days against {attendance_lop} recorded.",
                    fix="Reconcile leave-without-pay between the two systems.",
                )
            )

    # More days paid than the month holds is arithmetically impossible and
    # usually means a doubled row or a mis-set calendar.
    calendar_days = _dec(attendance.calendar_days)
    if register_paid is not None and calendar_days is not None and register_paid > calendar_days:
        findings.append(
            _finding(
                employee_id=employee_id, employee_name=name,
                rule_id="ATT-004", rule_name="Paid Days Exceed Calendar Days",
                component="paid_days", severity="CRITICAL",
                expected=f"<= {calendar_days}", actual=register_paid,
                difference=register_paid - calendar_days,
                reason=f"{register_paid} days paid in a month of {calendar_days} days.",
                fix="Check for a duplicated row or an incorrect month length.",
            )
        )

    return findings
