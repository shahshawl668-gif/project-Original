"""
Parser coverage for employee master and attendance files.

The cases here are the shapes real client exports arrive in: decorated headers,
dd/mm/yyyy dates, Excel's numeric employee codes, and columns nobody planned for.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd

from app.services.workforce_parse import (
    EMPLOYEE_MASTER_ALIASES,
    build_header_map,
    derive_attendance_gaps,
    parse_attendance,
    parse_date,
    parse_employee_master,
)


def test_header_aliases_resolve_across_naming_conventions():
    columns = ["Emp Code", "Employee Name", "DOJ", "Date of Leaving", "PAN No", "UAN Number"]
    mapping = build_header_map(columns, EMPLOYEE_MASTER_ALIASES)

    assert mapping["Emp Code"] == "employee_id"
    assert mapping["DOJ"] == "date_of_joining"
    assert mapping["Date of Leaving"] == "date_of_exit"
    assert mapping["PAN No"] == "pan"
    assert mapping["UAN Number"] == "uan"


def test_indian_exports_are_read_day_first():
    """03/04/2025 is 3 April, not 4 March — an eleven-month error if misread."""
    assert parse_date("03/04/2025") == date(2025, 4, 3)
    assert parse_date("03-04-2025") == date(2025, 4, 3)
    assert parse_date("3-Apr-2025") == date(2025, 4, 3)
    assert parse_date("2025-04-03") == date(2025, 4, 3)


def test_unreadable_dates_become_none_rather_than_guesses():
    for value in ("", "  ", "N/A", "-", "not a date", None, float("nan")):
        assert parse_date(value) is None


def test_master_rows_are_typed_and_unknown_columns_are_kept():
    df = pd.DataFrame(
        [
            {
                "Emp Code": 1001.0,          # Excel numeric coercion
                "Employee Name": " Asha Menon ",
                "DOJ": "15/06/2021",
                "State": "Karnataka",
                "Shift Pattern": "Night B",   # genuinely not in the schema
            }
        ]
    )
    records, header_map, unmapped = parse_employee_master(df)

    assert len(records) == 1
    row = records[0]
    assert row["employee_id"] == "1001"       # not "1001.0"
    assert row["employee_name"] == "Asha Menon"
    assert row["date_of_joining"] == date(2021, 6, 15)
    assert row["work_state"] == "Karnataka"

    assert "Shift Pattern" in unmapped
    assert row["extra"]["shift_pattern"] == "Night B"


def test_rows_without_an_employee_id_are_dropped():
    """Trailing total rows and blank lines are common in exports."""
    df = pd.DataFrame(
        [
            {"Emp Code": "1001", "Employee Name": "Asha"},
            {"Emp Code": None, "Employee Name": "TOTAL"},
        ]
    )
    records, _, _ = parse_employee_master(df)
    assert [r["employee_id"] for r in records] == ["1001"]


def test_attendance_numeric_fields_are_decimals():
    df = pd.DataFrame(
        [{"Emp Code": "1001", "Paid Days": "28.5", "LOP": "2.5", "OT Hours": "10"}]
    )
    records, _, _ = parse_attendance(df)
    row = records[0]

    assert row["paid_days"] == Decimal("28.5")
    assert row["lop_days"] == Decimal("2.5")
    assert row["overtime_hours"] == Decimal("10")


def test_missing_attendance_figure_is_derived():
    calendar = Decimal("31")

    only_lop = derive_attendance_gaps({"lop_days": Decimal("3")}, calendar)
    assert only_lop["paid_days"] == Decimal("28")

    only_paid = derive_attendance_gaps({"paid_days": Decimal("28")}, calendar)
    assert only_paid["lop_days"] == Decimal("3")

    # A file that states both is left alone, even if the two disagree with the
    # calendar — that disagreement is a finding, not something to paper over.
    both = derive_attendance_gaps(
        {"paid_days": Decimal("30"), "lop_days": Decimal("3")}, calendar
    )
    assert both["paid_days"] == Decimal("30")
    assert both["lop_days"] == Decimal("3")


def test_a_more_specific_header_is_not_displaced_by_a_generic_one():
    df = pd.DataFrame([{"Work State": "Tamil Nadu", "State": "Maharashtra", "Emp Code": "1"}])
    records, _, _ = parse_employee_master(df)
    assert records[0]["work_state"] == "Tamil Nadu"
