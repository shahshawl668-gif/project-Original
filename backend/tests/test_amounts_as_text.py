"""
Amounts a spreadsheet writes as text are amounts, and text that is not an
amount is refused — never read as zero.

Excel and most HRMS exports write "30,000" or "₹1,800.50". The engines used
to read such a cell as nought, so a PF deduction of "1,700" against "1,800"
due was compared as zero against zero and passed. The Studio CTC import
accepted "12,00,000" as readable and then stored it as nothing.
"""
from __future__ import annotations

import io
import json
import uuid

import pytest

from app.database import SessionLocal
from app.models import CtcRecord
from app.services.ctc_parse import parse_ctc_file
from tests.test_coverage import _outcome, _register, _run
from tests.test_run_history import PERIOD, _company
from tests.test_studio_api import _key, submit
from datetime import UTC


@pytest.fixture()
def company(client):
    return _company(client, "amounts")


def _upload(client, headers, rows):
    return client.post("/api/payroll/upload", headers=headers,
                       files={"file": ("r.csv", io.BytesIO(_register(rows)), "text/csv")},
                       data={"meta": json.dumps({"period_month": PERIOD, "strict_header_check": False})})


def test_grouped_and_rupee_amounts_are_read_and_checked(client, company):
    rows = ['E001,Person E001,Karnataka,30,0,"30,000","12,000","7,500","1,800","1,800",,,ABCPE1234F,100200300400',
            # ₹100 short on PF, written the way an export writes it.
            'E002,Person E002,Karnataka,30,0,"₹30,000","12,000","7,500","1,700","1,700",,,ABCPE1234G,100200300401']
    run_id = _run(client, company, _register(rows))
    assert _outcome(client, company, run_id, "E001", "STAT-001")["outcome"] == "passed"
    failed = _outcome(client, company, run_id, "E002", "STAT-001")
    assert failed["outcome"] == "failed" and "1700.00" in failed["reason"] and "1800.00" in failed["reason"]


def test_a_register_amount_that_is_not_a_number_is_refused_not_zeroed(client, company):
    rows = ['E003,Person E003,Karnataka,30,0,thirty,12000,7500,1800,1800,,,ABCPE1234H,100200300402']
    r = _upload(client, company, rows)
    assert r.status_code == 400
    detail = r.json()["error"]["detail"]
    assert "row 2, basic “thirty”" in detail and "never taken as zero" in detail


def test_a_blank_or_dash_stays_absent(client, company):
    # ESIC left blank or "-" above the ceiling is absent, not a stated zero.
    rows = ['E004,Person E004,Karnataka,30,0,30000,12000,7500,1800,1800,-,,ABCPE1234J,100200300403']
    assert _upload(client, company, rows).status_code == 200


def test_ctc_upload_reads_lakh_grouping_and_refuses_text():
    good = (b"employee_id,effective_from,basic,annual_ctc\n"
            b'E1,2026-04-01,"4,80,000","9,00,000"\n'
            b'E2,2026-04-01,"\xe2\x82\xb93,00,000",\n')
    _, records = parse_ctc_file(good, "ctc.csv", {"basic"})
    assert [r["annual_components"]["basic"] for r in records] == [480000.0, 300000.0]
    assert records[0]["annual_ctc"] == 900000.0
    with pytest.raises(ValueError, match="Row 2, basic “lots” is not an amount"):
        parse_ctc_file(b"employee_id,effective_from,basic\nE1,2026-04-01,lots\n", "ctc.csv", {"basic"})


def test_a_ctc_row_without_a_date_is_reported_not_dropped():
    content = b"employee_id,effective_from,basic\nE1,2026-04-01,100\nE2,,200\n"
    with pytest.raises(ValueError, match=r"row 3 \(E2\)"):
        parse_ctc_file(content, "ctc.csv", {"basic"})
    # With a default date for the file, the row is kept.
    from datetime import date

    _, records = parse_ctc_file(content, "ctc.csv", {"basic"}, date(2026, 4, 1))
    assert [r["employee_id"] for r in records] == ["E1", "E2"]


def test_studio_ctc_stores_the_amount_it_accepted(client, company):
    from app.services.studio import ratelimit

    ratelimit.reset()
    k = _key(client, company)
    run = submit(client, k["key"], "ctc", {"records": [
        {"employee_id": "00777", "effective_from": "2026-04-01", "basic": "12,00,000", "annual_ctc": "₹18,00,000"},
    ]})
    assert run["counts"]["accepted"] == 1
    db = SessionLocal()
    try:
        record = db.query(CtcRecord).filter(CtcRecord.entity_id == uuid.UUID(company["X-Entity-Id"]),
                                            CtcRecord.employee_id == "00777").one()
    finally:
        db.close()
    assert record.annual_components == {"basic": 1200000.0}
    assert float(record.annual_ctc) == 1800000.0


def test_a_ctc_date_is_read_day_first():
    content = b"employee_id,effective_from,basic\nE1,01/04/2026,100\nE2,2026-04-01 00:00:00,100\nE3,01-Apr-2026,100\n"
    _, records = parse_ctc_file(content, "ctc.csv", {"basic"})
    assert {r["effective_from"] for r in records} == {"2026-04-01"}       # never 4 January


def test_today_is_the_indian_calendar_day(monkeypatch):
    """At 00:30 IST the server's UTC clock still says yesterday; due dates follow India."""
    from datetime import date, datetime

    from app.services import clock

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 14, 19, 0, tzinfo=UTC).astimezone(tz)   # 00:30 IST on the 15th

    monkeypatch.setattr(clock, "datetime", Frozen)
    assert clock.india_today() == date(2026, 9, 15)


def test_a_windows_excel_csv_is_readable():
    from app.services.payroll_parse import normalize_col, parse_payroll_file

    cp1252 = "Employee ID,Employee Name,Basic\nE1,José Müller,\"30,000\"\n".encode("cp1252")
    frame = parse_payroll_file(cp1252, "r.csv")
    assert frame.iloc[0]["Employee Name"] == "José Müller"
    bom = "﻿Employee ID,Basic\nE1,30000\n".encode()
    assert [normalize_col(c) for c in parse_payroll_file(bom, "r.csv").columns] == ["employee_id", "basic"]


def test_a_budget_amount_is_read_or_refused_never_zeroed():
    from app.services.budgeting import parse_budget_rows

    lines, problems = parse_budget_rows([
        {"period": "2026-09", "scope": "entity", "amount": "5,00,000"},
        {"period": "2026-10", "scope": "entity", "amount": "five lakh"},
    ], "scope")
    assert [str(line["amount"]) for line in lines] == ["500000"]
    assert problems == ["Row 3: budget amount “five lakh” is not a number."]


def test_unreadable_attendance_values_are_named_not_dropped(client, company):
    content = b"employee_id,paid_days,lop_days\nE1,30,0\nE2,twenty,0\nE3,,\n"
    r = client.post("/api/workforce/attendance/upload", headers=company,
                    files={"file": ("a.csv", io.BytesIO(content), "text/csv")}, data={"meta": "{}"})
    assert r.status_code == 200, r.text
    warnings = r.json()["data"]["warnings"]
    assert any("row 3, paid_days “twenty” is not a number" in w and "not zero" in w for w in warnings)
    assert not any("row 4" in w for w in warnings)               # a blank is absent, not unreadable
