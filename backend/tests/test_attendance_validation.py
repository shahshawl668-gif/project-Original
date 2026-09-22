"""
Attendance, and the pay that should follow from it.

Attendance is the input payroll multiplies, so a wrong day count is a wrong
payslip that every register-level check will pass — the register is perfectly
consistent with itself, it is consistent with the wrong number of days.

Two jobs are tested here and they are different. Whether the attendance file
adds up, judged with no other input. And whether what was paid follows from
what was worked, which needs a baseline from outside the month and which says
so when it has none.

The property that matters most: the loss-of-pay check must never invent a
full-month wage. A fabricated overpayment sent to a client is worse than an
unanswered question, so with no agreed CTC and no clean prior month the rule
reports that it could not run.
"""
from __future__ import annotations

import io
import json
import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.database import SessionLocal
from app.models import (
    AttendanceRegister,
    AttendanceRow,
    CtcRecord,
    CtcUpload,
    Entity,
    SalaryRegister,
    SalaryRegisterRow,
    User,
)
from app.services import attendance_rules
from app.services.dimensions import UNASSIGNED

PASSWORD = "Passw0rd!x"
PERIOD = date(2026, 6, 1)  # 30 days

COMPONENTS = [
    {"component_name": "Basic", "pf_applicable": True, "esic_applicable": True,
     "pt_applicable": True, "included_in_wages": True, "taxable": True},
    {"component_name": "HRA", "esic_applicable": True, "pt_applicable": True, "taxable": True},
]


@pytest.fixture()
def workspace(client, request):
    email = f"{request.node.name[:40]}@att-example.com".replace("_", "-")
    r = client.post("/api/auth/signup", json={
        "email": email, "password": PASSWORD, "company_name": "Attendance Tests",
    })
    if r.status_code != 200:
        r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    headers = {"Authorization": f"Bearer {r.json()['data']['access_token']}"}
    entity_id = client.post(
        "/api/org/entities",
        json={"name": f"E-{request.node.name[:26]}", "primary_state": "Karnataka"},
        headers=headers,
    ).json()["data"]["id"]
    headers["X-Entity-Id"] = entity_id
    for component in COMPONENTS:
        assert client.post("/api/components", json=component, headers=headers).status_code == 201

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).one()
        entity = db.get(Entity, uuid.UUID(entity_id))
        db.expunge_all()
    finally:
        db.close()
    return entity, user, headers


def _dims() -> dict:
    return dict.fromkeys(
        ("business_unit", "department", "cost_center", "work_location", "work_state",
         "grade", "designation", "employment_type", "skill_category"), UNASSIGNED
    )


def store_attendance(entity, user, rows: list[dict], period: date = PERIOD) -> None:
    db = SessionLocal()
    try:
        register = AttendanceRegister(
            user_id=user.id, entity_id=entity.id, period_month=period,
            filename="attendance.csv", employee_count=len(rows),
        )
        db.add(register)
        db.flush()
        for row in rows:
            db.add(AttendanceRow(
                register_id=register.id, user_id=user.id, entity_id=entity.id,
                period_month=period, employee_id=row["employee_id"],
                employee_name=row.get("employee_name"),
                calendar_days=row.get("calendar_days", Decimal("30")),
                present_days=row.get("present_days"),
                paid_days=row.get("paid_days"),
                lop_days=row.get("lop_days"),
                overtime_hours=row.get("overtime_hours"),
            ))
        db.commit()
    finally:
        db.close()


def store_register(entity, user, rows: list[dict], period: date = PERIOD) -> None:
    db = SessionLocal()
    try:
        register = SalaryRegister(
            user_id=user.id, entity_id=entity.id, period_month=period,
            filename="register.csv", employee_count=len(rows),
        )
        db.add(register)
        db.flush()
        for row in rows:
            db.add(SalaryRegisterRow(
                register_id=register.id, user_id=user.id, entity_id=entity.id,
                period_month=period, employee_id=row["employee_id"],
                components=row.get("components", {"basic": 30000.0, "hra": 12000.0}),
                arrears={}, deductions={}, dimensions=_dims(),
                increment_arrear_total=Decimal("0"),
            ))
        db.commit()
    finally:
        db.close()


def store_ctc(entity, user, employee_id: str, annual: dict[str, float]) -> None:
    db = SessionLocal()
    try:
        upload = CtcUpload(
            user_id=user.id, entity_id=entity.id, effective_from=date(2026, 4, 1),
            filename="ctc.csv", employee_count=1,
        )
        db.add(upload)
        db.flush()
        db.add(CtcRecord(
            upload_id=upload.id, user_id=user.id, entity_id=entity.id,
            employee_id=employee_id, effective_from=date(2026, 4, 1),
            annual_components=annual,
            annual_ctc=Decimal(str(sum(annual.values()))),
        ))
        db.commit()
    finally:
        db.close()


def validate(client, headers, employees: list[dict]) -> dict:
    response = client.post("/api/payroll/validate", headers=headers, json={
        "employees": employees, "period_month": PERIOD.isoformat(),
    })
    assert response.status_code == 200, response.text
    return response.json()["data"]


def rules_for(result: dict, employee_id: str) -> dict[str, dict]:
    row = next(r for r in result["results"] if r["employee_id"] == employee_id)
    return {f["rule_id"]: f for f in row["findings"]}


# ---------------------------------------------------------------------------
# The daily rate
# ---------------------------------------------------------------------------
def test_each_basis_gives_a_different_daily_rate():
    # The whole reason this is configuration: the same month, three answers.
    assert attendance_rules.paid_day_basis(date(2026, 2, 1), "calendar") == 28
    assert attendance_rules.paid_day_basis(date(2026, 6, 1), "calendar") == 30
    assert attendance_rules.paid_day_basis(date(2026, 7, 1), "calendar") == 31
    assert attendance_rules.paid_day_basis(date(2026, 7, 1), "fixed_26") == 26
    assert attendance_rules.paid_day_basis(date(2026, 2, 1), "fixed_30") == 30


def test_a_leap_february_is_twenty_nine_days():
    assert attendance_rules.days_in_month(date(2028, 2, 1)) == 29


def test_every_basis_is_described_for_the_reader():
    for option in attendance_rules.basis_catalogue():
        assert option["key"] and option["label"] and option["hint"]


# ---------------------------------------------------------------------------
# The attendance file against itself
# ---------------------------------------------------------------------------
def check(records: list[dict], period: date = PERIOD) -> dict[str, list[dict]]:
    found: dict[str, list[dict]] = {}
    for finding in attendance_rules.check_self_consistency(records, period):
        found.setdefault(finding["rule_id"], []).append(finding)
    return found


def test_a_coherent_file_raises_nothing():
    assert check([{
        "employee_id": "E1", "calendar_days": 30, "present_days": 22,
        "paid_leave_days": 1, "weekly_off_days": 4, "holiday_days": 1, "lop_days": 2,
        "paid_days": 28,
    }]) == {}


def test_days_that_do_not_add_up_to_the_month_are_reported():
    found = check([{
        "employee_id": "E1", "calendar_days": 30, "present_days": 22,
        "paid_leave_days": 1, "weekly_off_days": 4, "holiday_days": 1, "lop_days": 4,
        "paid_days": 26,
    }])
    assert "ATT-010" in found
    assert "32" in found["ATT-010"][0]["actual_value"]


def test_paid_days_that_contradict_loss_of_pay_are_reported():
    found = check([{"employee_id": "E1", "calendar_days": 30, "paid_days": 30, "lop_days": 4}])
    assert "ATT-011" in found
    assert found["ATT-011"][0]["severity"] == "CRITICAL"
    assert found["ATT-011"][0]["expected_value"] == "26"


def test_a_file_stating_only_one_of_the_two_is_not_accused_of_contradicting_itself():
    # Paid days would be derived from loss of pay. Flagging that would be
    # reporting our own arithmetic back at the client.
    assert "ATT-011" not in check([{"employee_id": "E1", "calendar_days": 30, "lop_days": 4}])
    assert "ATT-011" not in check([{"employee_id": "E1", "calendar_days": 30, "paid_days": 26}])


def test_the_wrong_month_length_is_reported():
    found = check([{"employee_id": "E1", "calendar_days": 31}], date(2026, 6, 1))
    assert "ATT-012" in found
    assert "30" in found["ATT-012"][0]["expected_value"]


def test_february_is_not_thirty_days():
    found = check([{"employee_id": "E1", "calendar_days": 30}], date(2026, 2, 1))
    assert "ATT-012" in found


def test_a_negative_day_count_is_critical():
    found = check([{"employee_id": "E1", "calendar_days": 30, "lop_days": -2}])
    assert "ATT-013" in found
    assert found["ATT-013"][0]["severity"] == "CRITICAL"


def test_more_paid_days_than_the_month_holds_is_critical():
    found = check([{"employee_id": "E1", "calendar_days": 30, "paid_days": 45}])
    assert "ATT-013" in found


def test_overtime_hours_beyond_the_day_count_are_not_treated_as_impossible():
    # Hours are not days. Forty hours of overtime in a thirty-day month is
    # ordinary, and flagging it would train people to ignore the rule.
    assert "ATT-013" not in check([
        {"employee_id": "E1", "calendar_days": 30, "paid_days": 30, "overtime_hours": 40}
    ])


def test_the_same_employee_twice_is_reported_rather_than_silently_dropped():
    found = check([
        {"employee_id": "E1", "calendar_days": 30, "paid_days": 30},
        {"employee_id": "E1", "calendar_days": 30, "paid_days": 20},
    ])
    assert "ATT-014" in found
    assert found["ATT-014"][0]["actual_value"] == "2"


# ---------------------------------------------------------------------------
# Through the upload endpoint
# ---------------------------------------------------------------------------
def test_a_file_can_be_checked_before_anything_is_stored(client, workspace):
    _, _, headers = workspace
    csv = (
        "employee_id,calendar_days,present_days,paid_leave,week_off,holidays,lop,paid_days\n"
        "E1,30,22,1,4,1,2,28\n"
        "E2,30,20,0,4,1,5,30\n"
    )
    result = client.post(
        "/api/workforce/attendance/validate", headers=headers,
        files={"file": ("att.csv", io.BytesIO(csv.encode()), "text/csv")},
        data={"meta": json.dumps({"period_month": "2026-06-01"})},
    )
    assert result.status_code == 200, result.text
    payload = result.json()["data"]
    assert payload["clean"] is False
    assert {f["rule_id"] for f in payload["findings"]} >= {"ATT-011"}
    assert payload["employees"] == 2

    # Nothing was stored.
    stored = client.get("/api/workforce/attendance", headers=headers).json()["data"]
    assert stored == [] or all(r["period_month"] != "2026-06-01" for r in stored)


def test_a_clean_file_is_reported_as_clean(client, workspace):
    _, _, headers = workspace
    csv = "employee_id,calendar_days,paid_days,lop\nE1,30,28,2\nE2,30,30,0\n"
    payload = client.post(
        "/api/workforce/attendance/validate", headers=headers,
        files={"file": ("att.csv", io.BytesIO(csv.encode()), "text/csv")},
        data={"meta": json.dumps({"period_month": "2026-06-01"})},
    ).json()["data"]
    assert payload["clean"] is True
    assert payload["counts"]["total"] == 0


def test_committing_a_file_with_duplicates_says_which_rows_it_dropped(client, workspace):
    _, _, headers = workspace
    csv = "employee_id,calendar_days,paid_days,lop\nE1,30,30,0\nE1,30,20,10\nE2,30,30,0\n"
    payload = client.post(
        "/api/workforce/attendance/commit", headers=headers,
        files={"file": ("att.csv", io.BytesIO(csv.encode()), "text/csv")},
        data={"meta": json.dumps({"period_month": "2026-06-01"})},
    ).json()["data"]
    assert payload["rows_read"] == 3
    assert payload["rows_stored"] == 2
    assert any(p["rule_id"] == "ATT-014" for p in payload["problems"])


def test_the_configured_bases_are_served_to_the_ui(client, workspace):
    _, _, headers = workspace
    bases = client.get("/api/workforce/attendance/bases", headers=headers).json()["data"]["bases"]
    assert {b["key"] for b in bases} == {"calendar", "fixed_26", "fixed_30"}


# ---------------------------------------------------------------------------
# Pay against attendance — the money
# ---------------------------------------------------------------------------
REGISTER_ROW = {
    "employee_id": "E1", "employee_name": "Asha Menon", "state": "Karnataka",
    "basic": 30000, "hra": 12000, "paid_days": 28, "lop_days": 2, "pf_employee": 1800,
}


def test_loss_of_pay_with_no_baseline_reports_that_it_could_not_be_checked(client, workspace):
    # No CTC and no earlier month, so there is nothing to compare against. The
    # rule says so instead of inventing a full-month wage.
    entity, user, headers = workspace
    store_attendance(entity, user, [{"employee_id": "E1", "paid_days": 28, "lop_days": 2}])
    found = rules_for(validate(client, headers, [REGISTER_ROW]), "E1")
    assert "ATT-024" in found
    assert found["ATT-024"]["severity"] == "INFO"
    assert "ATT-020" not in found


def test_pay_not_reduced_for_loss_of_pay_is_found_against_the_agreed_ctc(client, workspace):
    entity, user, headers = workspace
    # ₹504,000 a year is ₹42,000 a month; two days at 1/30 is ₹2,800.
    store_ctc(entity, user, "E1", {"basic": 360000.0, "hra": 144000.0})
    store_attendance(entity, user, [{"employee_id": "E1", "paid_days": 28, "lop_days": 2}])

    # Paid the full month despite two days of loss of pay.
    found = rules_for(validate(client, headers, [REGISTER_ROW]), "E1")
    assert "ATT-020" in found
    finding = found["ATT-020"]
    assert finding["severity"] == "CRITICAL"
    assert finding["expected_value"] == "39200.00"
    assert round(finding["financial_impact"]) == 2800
    assert "agreed CTC" in finding["reason"]


def test_a_correctly_reduced_month_raises_nothing(client, workspace):
    entity, user, headers = workspace
    store_ctc(entity, user, "E1", {"basic": 360000.0, "hra": 144000.0})
    store_attendance(entity, user, [{"employee_id": "E1", "paid_days": 28, "lop_days": 2}])
    reduced = {**REGISTER_ROW, "basic": 28000, "hra": 11200}
    found = rules_for(validate(client, headers, [reduced]), "E1")
    assert "ATT-020" not in found


def test_the_basis_changes_the_expected_deduction(client, workspace):
    # Two days of loss of pay deducts ₹2,800 on a thirty-day basis and
    # ₹3,230.77 on a twenty-six-day one. Same file, different answer.
    entity, user, headers = workspace
    assert client.put("/api/config/statutory/rule-thresholds", headers=headers, json={
        "attendance": {"paid_days_basis": "fixed_26"},
    }).status_code == 200
    store_ctc(entity, user, "E1", {"basic": 360000.0, "hra": 144000.0})
    store_attendance(entity, user, [{"employee_id": "E1", "paid_days": 28, "lop_days": 2}])

    found = rules_for(validate(client, headers, [REGISTER_ROW]), "E1")
    assert "ATT-020" in found
    assert found["ATT-020"]["expected_value"] == "38769.23"
    assert "26" in found["ATT-020"]["reason"] or "fixed 26" in found["ATT-020"]["reason"].lower()


def test_paying_someone_with_no_paid_days_is_critical(client, workspace):
    entity, user, headers = workspace
    store_attendance(entity, user, [{"employee_id": "E1", "paid_days": 0, "lop_days": 30}])
    found = rules_for(validate(client, headers, [{**REGISTER_ROW, "paid_days": 0}]), "E1")
    assert "ATT-021" in found
    assert found["ATT-021"]["severity"] == "CRITICAL"
    assert round(found["ATT-021"]["financial_impact"]) == 42000


def test_overtime_worked_and_not_paid_is_reported(client, workspace):
    entity, user, headers = workspace
    store_ctc(entity, user, "E1", {"basic": 360000.0, "hra": 144000.0})
    store_attendance(entity, user, [
        {"employee_id": "E1", "paid_days": 30, "lop_days": 0, "overtime_hours": 10},
    ])
    found = rules_for(
        validate(client, headers, [{**REGISTER_ROW, "paid_days": 30, "lop_days": 0}]), "E1"
    )
    assert "ATT-022" in found
    # ₹42,000 / 30 / 8 = ₹175 an hour; ten hours at twice that is ₹3,500.
    assert round(found["ATT-022"]["financial_impact"]) == 3500
    assert "Factories Act" in found["ATT-022"]["reason"]


def test_overtime_paid_below_the_statutory_rate_is_reported(client, workspace):
    entity, user, headers = workspace
    store_ctc(entity, user, "E1", {"basic": 360000.0, "hra": 144000.0})
    store_attendance(entity, user, [
        {"employee_id": "E1", "paid_days": 30, "lop_days": 0, "overtime_hours": 10},
    ])
    # Paid at the ordinary rate rather than twice it.
    row = {**REGISTER_ROW, "paid_days": 30, "lop_days": 0, "overtime": 1750}
    found = rules_for(validate(client, headers, [row]), "E1")
    assert "ATT-023" in found
    assert round(found["ATT-023"]["financial_impact"]) == 1750
    assert "ATT-022" not in found


def test_overtime_paid_at_the_statutory_rate_raises_nothing(client, workspace):
    entity, user, headers = workspace
    store_ctc(entity, user, "E1", {"basic": 360000.0, "hra": 144000.0})
    store_attendance(entity, user, [
        {"employee_id": "E1", "paid_days": 30, "lop_days": 0, "overtime_hours": 10},
    ])
    row = {**REGISTER_ROW, "paid_days": 30, "lop_days": 0, "ot_amount": 3500}
    found = rules_for(validate(client, headers, [row]), "E1")
    assert "ATT-022" not in found and "ATT-023" not in found


def test_someone_on_attendance_and_on_no_payslip_is_reported(client, workspace):
    entity, user, headers = workspace
    store_attendance(entity, user, [
        {"employee_id": "E1", "paid_days": 30, "lop_days": 0},
        {"employee_id": "E2", "employee_name": "Rahul Verma", "paid_days": 30, "lop_days": 0},
    ])
    result = validate(client, headers, [{**REGISTER_ROW, "paid_days": 30, "lop_days": 0}])
    unpaid = [
        f for row in result["results"] for f in row["findings"] if f["rule_id"] == "ATT-015"
    ] + [f for f in result["findings"] if f["rule_id"] == "ATT-015"]
    assert any(f["employee_id"] == "E2" for f in unpaid)


def test_someone_with_no_paid_days_and_no_payslip_is_not_reported(client, workspace):
    # Nothing was owed, so nothing is missing.
    entity, user, headers = workspace
    store_attendance(entity, user, [
        {"employee_id": "E1", "paid_days": 30, "lop_days": 0},
        {"employee_id": "E2", "paid_days": 0, "lop_days": 30},
    ])
    result = validate(client, headers, [{**REGISTER_ROW, "paid_days": 30, "lop_days": 0}])
    assert not [f for f in result["findings"] if f["rule_id"] == "ATT-015"]


# ---------------------------------------------------------------------------
# The baseline
# ---------------------------------------------------------------------------
def test_a_prior_month_with_loss_of_pay_is_refused_as_a_baseline(client, workspace):
    # A reduced month used as the baseline would make a second reduced month
    # look correct, which is the one way this check could do harm.
    entity, user, headers = workspace
    store_register(entity, user, [{"employee_id": "E1"}], period=date(2026, 5, 1))
    store_attendance(entity, user, [{"employee_id": "E1", "paid_days": 25, "lop_days": 5}],
                     period=date(2026, 5, 1))
    store_attendance(entity, user, [{"employee_id": "E1", "paid_days": 28, "lop_days": 2}])

    found = rules_for(validate(client, headers, [REGISTER_ROW]), "E1")
    assert "ATT-024" in found
    assert "ATT-020" not in found


def test_a_clean_prior_month_is_accepted_as_a_baseline(client, workspace):
    entity, user, headers = workspace
    store_register(entity, user, [
        {"employee_id": "E1", "components": {"basic": 30000.0, "hra": 12000.0}},
    ], period=date(2026, 5, 1))
    store_attendance(entity, user, [{"employee_id": "E1", "paid_days": 30, "lop_days": 0}],
                     period=date(2026, 5, 1))
    store_attendance(entity, user, [{"employee_id": "E1", "paid_days": 28, "lop_days": 2}])

    found = rules_for(validate(client, headers, [REGISTER_ROW]), "E1")
    assert "ATT-020" in found
    assert "May 2026" in found["ATT-020"]["reason"]


def test_the_agreed_ctc_is_preferred_over_a_prior_month(client, workspace):
    # A contract beats an observation, and it is unaffected by whatever
    # happened to the month being checked.
    entity, user, headers = workspace
    store_ctc(entity, user, "E1", {"basic": 360000.0, "hra": 144000.0})
    store_register(entity, user, [
        {"employee_id": "E1", "components": {"basic": 10000.0, "hra": 4000.0}},
    ], period=date(2026, 5, 1))
    store_attendance(entity, user, [{"employee_id": "E1", "paid_days": 30, "lop_days": 0}],
                     period=date(2026, 5, 1))
    store_attendance(entity, user, [{"employee_id": "E1", "paid_days": 28, "lop_days": 2}])

    found = rules_for(validate(client, headers, [REGISTER_ROW]), "E1")
    assert "agreed CTC" in found["ATT-020"]["reason"]


# ---------------------------------------------------------------------------
# Not claiming more than was checked
# ---------------------------------------------------------------------------
def test_a_workspace_with_no_attendance_gets_silence_not_false_positives(client, workspace):
    _, _, headers = workspace
    result = validate(client, headers, [REGISTER_ROW])
    attendance_rule_ids = {
        f["rule_id"] for row in result["results"] for f in row["findings"]
        if f["rule_id"].startswith("ATT-")
    }
    assert attendance_rule_ids == set()


def test_every_attendance_rule_is_classified_for_the_reader():
    from app.services.finding_taxonomy import CATEGORY_ORDER, categorise

    for rule_id in ("ATT-010", "ATT-011", "ATT-012", "ATT-013", "ATT-014",
                    "ATT-015", "ATT-020", "ATT-021", "ATT-022", "ATT-023", "ATT-024"):
        assert categorise(rule_id) in CATEGORY_ORDER, rule_id
    # The one that reports an absent baseline belongs with the other absences.
    assert categorise("ATT-024") == "missing"
