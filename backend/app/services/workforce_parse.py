"""
Parsing for employee master and attendance files.

No two clients name their columns the same way. A bureau onboarding its tenth
client should not need a code change, so each field declares the aliases seen in
the wild and headers are matched against them after normalisation.

Anything unrecognised is kept in ``extra`` rather than discarded: a column this
schema doesn't know about today is still evidence, and dropping it silently is
how validation tools lose people's trust.
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd

from app.services.payroll_parse import normalize_col

# ---------------------------------------------------------------------------
# Header aliases
# ---------------------------------------------------------------------------
# Each entry maps a canonical field to the header spellings that mean it.
# Matching is done on normalised headers (lowercased, underscored).

EMPLOYEE_MASTER_ALIASES: dict[str, tuple[str, ...]] = {
    "employee_id": ("employee_id", "emp_id", "employee_code", "emp_code", "employee_no", "empno", "staff_id", "token_no"),
    "employee_name": ("employee_name", "name", "emp_name", "full_name", "employee"),
    "date_of_joining": ("date_of_joining", "doj", "joining_date", "date_joined", "hire_date", "date_of_join"),
    "date_of_exit": ("date_of_exit", "dol", "date_of_leaving", "exit_date", "last_working_day", "lwd", "relieving_date", "date_of_separation"),
    "date_of_birth": ("date_of_birth", "dob", "birth_date"),
    "gender": ("gender", "sex"),
    "work_state": ("work_state", "state", "pt_state", "location_state", "work_location_state"),
    "work_location": ("work_location", "location", "branch", "office", "site"),
    "department": ("department", "dept", "division", "function"),
    "designation": ("designation", "title", "job_title", "role"),
    "grade": ("grade", "band", "level", "job_grade"),
    "employment_type": ("employment_type", "emp_type", "employee_type", "worker_type", "category", "nature_of_employment"),
    "skill_category": ("skill_category", "skill", "skill_level", "skill_type", "minimum_wage_category"),
    "pf_restricted": ("pf_restricted", "pf_restriction", "pf_capped", "pf_cap", "restrict_pf",
                      "pf_ceiling_applied", "pf_limit_applied", "pf_basis"),
    "pan": ("pan", "pan_no", "pan_number", "income_tax_pan"),
    "aadhaar": ("aadhaar", "aadhar", "aadhaar_no", "aadhar_no", "aadhaar_number", "uidai"),
    "uan": ("uan", "uan_no", "uan_number", "universal_account_number"),
    "pf_number": ("pf_number", "pf_no", "pf_account_number", "epf_number", "member_id"),
    "esic_ip_number": ("esic_ip_number", "esic_ip", "ip_number", "esic_no", "esic_number", "insurance_number"),
    "bank_account": ("bank_account", "account_no", "account_number", "bank_ac_no", "bank_account_number"),
    "ifsc": ("ifsc", "ifsc_code", "bank_ifsc"),
}

ATTENDANCE_ALIASES: dict[str, tuple[str, ...]] = {
    "employee_id": ("employee_id", "emp_id", "employee_code", "emp_code", "employee_no", "empno", "staff_id", "token_no"),
    "employee_name": ("employee_name", "name", "emp_name", "full_name", "employee"),
    "calendar_days": ("calendar_days", "total_days", "month_days", "days_in_month", "standard_days"),
    "present_days": ("present_days", "days_present", "present", "actual_days", "worked_days", "attended_days"),
    "paid_days": ("paid_days", "payable_days", "days_paid", "paid"),
    "lop_days": ("lop_days", "lop", "loss_of_pay", "lwp", "lwp_days", "absent_days", "unpaid_days", "absent"),
    "paid_leave_days": ("paid_leave_days", "leave_days", "paid_leave", "pl_days", "el_days", "cl_days", "leave"),
    "weekly_off_days": ("weekly_off_days", "week_off", "weekly_off", "wo_days", "off_days"),
    "holiday_days": ("holiday_days", "holidays", "ph_days", "public_holidays", "festival_holidays"),
    "overtime_hours": ("overtime_hours", "ot_hours", "overtime", "ot", "ot_hrs"),
}

DATE_FIELDS = {"date_of_joining", "date_of_exit", "date_of_birth"}
BOOLEAN_FIELDS = {"pf_restricted"}
DECIMAL_FIELDS = {
    "calendar_days", "present_days", "paid_days", "lop_days",
    "paid_leave_days", "weekly_off_days", "holiday_days", "overtime_hours",
}

# Formats tried in order. Day-first comes before month-first because Indian
# payroll exports are overwhelmingly dd/mm/yyyy, and 03/04/2025 is a silent
# eleven-month error if read the American way.
DATE_FORMATS = (
    "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y",
    "%d-%b-%Y", "%d %b %Y", "%d-%B-%Y", "%d %B %Y",
    "%m/%d/%Y", "%Y/%m/%d", "%d-%m-%y", "%d/%m/%y",
)


def build_header_map(columns: list[str], aliases: dict[str, tuple[str, ...]]) -> dict[str, str]:
    """
    Resolve each incoming column to a canonical field name.

    Returns ``{source_column: canonical_field}``, leaving unmatched columns out
    so the caller can route them to ``extra``.
    """
    lookup: dict[str, str] = {}
    for canonical, spellings in aliases.items():
        for spelling in spellings:
            lookup[spelling] = canonical

    mapping: dict[str, str] = {}
    claimed: set[str] = set()
    for column in columns:
        key = normalize_col(column)
        canonical = lookup.get(key)
        if canonical is None:
            # Tolerate decoration like "DOJ (dd/mm/yyyy)" or "Paid Days*".
            stripped = re.sub(r"[^a-z0-9_]", "", key)
            canonical = lookup.get(stripped)
        # First column wins, so a file carrying both "state" and "work_state"
        # keeps the more specific header that appeared first.
        if canonical and canonical not in claimed:
            mapping[column] = canonical
            claimed.add(canonical)
    return mapping


def parse_date(value: Any) -> date | None:
    """Read a date from whatever the export produced, or None if unreadable."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime().date()

    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none", "-", "na", "n/a"}:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_decimal(value: Any) -> Decimal | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    text = str(value).strip().replace(",", "")
    if not text or text.lower() in {"nan", "none", "-", "na", "n/a"}:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _clean_text(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    text = str(value).strip()
    return text or None


def _coerce_employee_id(value: Any) -> str | None:
    """Excel turns a numeric code into 1001.0; restore the original spelling."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    return str(value).strip() or None


def _rows_from_frame(
    df: pd.DataFrame, aliases: dict[str, tuple[str, ...]]
) -> tuple[list[dict[str, Any]], dict[str, str], list[str]]:
    header_map = build_header_map(list(df.columns), aliases)
    unmapped = [c for c in df.columns if c not in header_map]

    records: list[dict[str, Any]] = []
    for _, source in df.iterrows():
        record: dict[str, Any] = {}
        extra: dict[str, Any] = {}

        for column, value in source.items():
            canonical = header_map.get(column)
            if canonical is None:
                cleaned = _clean_text(value)
                if cleaned is not None:
                    extra[normalize_col(column)] = cleaned
                continue
            if canonical == "employee_id":
                record[canonical] = _coerce_employee_id(value)
            elif canonical in DATE_FIELDS:
                record[canonical] = parse_date(value)
            elif canonical in DECIMAL_FIELDS:
                record[canonical] = parse_decimal(value)
            elif canonical in BOOLEAN_FIELDS:
                from app.services.pf_basis import parse_flag

                record[canonical] = parse_flag(value)
            else:
                record[canonical] = _clean_text(value)

        record["extra"] = extra
        if record.get("employee_id"):
            records.append(record)

    return records, header_map, unmapped


def parse_employee_master(df: pd.DataFrame) -> tuple[list[dict[str, Any]], dict[str, str], list[str]]:
    """Return (records, header_map, unmapped_columns) for an employee master file."""
    return _rows_from_frame(df, EMPLOYEE_MASTER_ALIASES)


def parse_attendance(df: pd.DataFrame) -> tuple[list[dict[str, Any]], dict[str, str], list[str]]:
    """Return (records, header_map, unmapped_columns) for an attendance file."""
    return _rows_from_frame(df, ATTENDANCE_ALIASES)


def derive_attendance_gaps(record: dict[str, Any], calendar_days: Decimal) -> dict[str, Any]:
    """
    Fill in the attendance figures a file left out.

    Most exports carry two of {calendar, paid, LOP} and expect the third to be
    inferred. Deriving it here means the comparison rules can assume all three
    are present, and the derivation is stated once instead of in each rule.
    """
    filled = dict(record)
    if filled.get("calendar_days") is None:
        filled["calendar_days"] = calendar_days

    cal = filled.get("calendar_days") or calendar_days
    paid = filled.get("paid_days")
    lop = filled.get("lop_days")

    if paid is None and lop is not None:
        filled["paid_days"] = cal - lop
    elif lop is None and paid is not None:
        filled["lop_days"] = cal - paid

    return filled
