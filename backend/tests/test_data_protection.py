"""
Retention and erasure.

* Retention removes every period older than the company's window, everywhere,
  and leaves the newer ones untouched. No policy deletes nothing, and says so.
* Erasure leaves no identifier of the person anywhere the company's working
  data is held — checked by scanning every table, compressed blobs included —
  and names what it kept. Another employee's data is not touched.

All data is synthetic.
"""
from __future__ import annotations

import gzip
import io
import json
import uuid
from datetime import date

import pytest
from sqlalchemy import LargeBinary

from app.database import Base, SessionLocal
from app.models import (
    AuditEvent,
    EmployeeRecord,
    ErasureRequest,
    RetentionPolicy,
    SalaryRegister,
    SalaryRegisterRow,
    ValidationRun,
)
from app.services import data_protection as dp

from tests.test_run_history import _company, _data, _drain

PASSWORD = "Passw0rd!x"


def _member(client, owner: dict, role: str) -> dict:
    email = f"dp-{role}-{uuid.uuid4().hex[:6]}@dp-example.com"
    inv = client.post("/api/org/invitations", headers=owner, json={"email": email, "role": role})
    assert inv.status_code == 200, inv.text
    joined = client.post("/api/org/invitations/register", json={"token": inv.json()["data"]["token"], "password": PASSWORD})
    assert joined.status_code == 200, joined.text
    return {"Authorization": f"Bearer {joined.json()['data']['access_token']}", "X-Entity-Id": owner["X-Entity-Id"]}


# Identifiers that occur nowhere else in the test data.
PERSON = "EMPX9001"
PAN = "ABCPX9001K"
UAN = "100900100900"
NAME = "Zorawar Testname"
ACCOUNT = "900100900100"
OTHER = "EMPY9002"
OTHER_PAN = "ABCPY9002L"

HEADER = "employee_id,employee_name,state,paid_days,lop_days,basic,hra,special allowance,pf_employee,pf_employer,pan,uan,bank_account"


def _register(period: str, rows: list[str]) -> bytes:
    return ("\n".join([HEADER, *rows]) + "\n").encode()


def _rows():
    return [f"{PERSON},{NAME},Karnataka,30,0,30000,12000,8000,1800,1800,{PAN},{UAN},{ACCOUNT}",
            f"{OTHER},Other Person,Karnataka,30,0,30000,12000,8000,1800,1800,{OTHER_PAN},100900100901,900100900101"]


def _validate(client, headers, period: str, content: bytes) -> str:
    r = client.post("/api/payroll/upload", headers=headers,
                    files={"file": ("r.csv", io.BytesIO(content), "text/csv")},
                    data={"meta": json.dumps({"period_month": period, "strict_header_check": False,
                                              "return_employees": False})})
    assert r.status_code == 200, r.text
    job = _data(client.post("/api/validation/jobs", headers=headers, json={"period_month": period}))["job"]
    _drain()
    job = _data(client.get(f"/api/validation/jobs/{job['id']}", headers=headers))
    assert job["state"] == "succeeded", job
    return job["run_id"]


def _master(client, headers):
    content = ("employee_id,employee_name,date_of_joining,pan,uan,bank_account\n"
               f"{PERSON},{NAME},2020-04-01,{PAN},{UAN},{ACCOUNT}\n"
               f"{OTHER},Other Person,2020-04-01,{OTHER_PAN},100900100901,900100900101\n").encode()
    r = client.post("/api/workforce/master/commit", headers=headers,
                    files={"file": ("m.csv", io.BytesIO(content), "text/csv")},
                    data={"meta": '{"effective_from": "2020-04-01"}'})
    assert r.status_code == 200, r.text


@pytest.fixture()
def company(client):
    return _company(client, "dpdp")


def _entity(headers) -> uuid.UUID:
    return uuid.UUID(headers["X-Entity-Id"])


def _scan(entity_id: uuid.UUID, needles: list[str]) -> dict[str, list[str]]:
    """Every table and column where any needle appears, compressed blobs opened."""
    hits: dict[str, list[str]] = {}
    db = SessionLocal()
    try:
        for table in Base.metadata.sorted_tables:
            if "entity_id" not in table.c:
                continue
            for row in db.execute(table.select().where(table.c.entity_id == entity_id)).mappings():
                for col in table.c:
                    value = row[col.name]
                    if value is None:
                        continue
                    if isinstance(col.type, LargeBinary):
                        try:
                            text = gzip.decompress(value).decode("utf-8", errors="replace")
                        except OSError:
                            text = value.decode("utf-8", errors="replace")
                    else:
                        text = json.dumps(value, default=str) if not isinstance(value, str) else value
                    for needle in needles:
                        if needle.lower() in text.lower():
                            hits.setdefault(needle, []).append(f"{table.name}.{col.name}")
    finally:
        db.close()
    return hits


# ── retention ────────────────────────────────────────────────────────────────

def test_cutoff_counts_the_current_month():
    assert dp.cutoff_for(12, date(2026, 10, 12)) == date(2025, 11, 1)
    assert dp.cutoff_for(24, date(2026, 1, 31)) == date(2024, 2, 1)


def test_no_policy_deletes_nothing_and_says_so(client, company):
    policy = _data(client.get("/api/data-protection/retention", headers=company))
    assert policy["status"] == "not_set" and policy["payroll_months"] is None
    assert "nothing is deleted" in policy["statement"]
    db = SessionLocal()
    try:
        assert dp.apply_due(db) >= 0
    finally:
        db.close()


def test_retention_removes_old_periods_and_keeps_new_ones(client, company):
    _validate(client, company, "2023-04-01", _register("2023-04-01", _rows()))
    _validate(client, company, "2026-09-01", _register("2026-09-01", _rows()))
    preview = _data(client.get("/api/data-protection/retention/preview?months=24", headers=company))
    assert preview["counts"]["Salary registers"] == 1 and preview["counts"]["Validation runs"] == 1

    r = client.put("/api/data-protection/retention", headers=company,
                   json={"payroll_months": 24, "reason": "Board decision 2026-10: two years"})
    assert r.status_code == 200, r.text
    assert _data(r)["status"] == "set" and _data(r)["pending"]["counts"]["Register rows"] == 2

    applied = _data(client.post("/api/data-protection/retention/apply", headers=company))
    assert applied["counts"]["Salary registers"] == 1 and applied["counts"]["Findings"] > 0

    e = _entity(company)
    db = SessionLocal()
    try:
        periods = sorted(p for (p,) in db.query(SalaryRegister.period_month).filter(SalaryRegister.entity_id == e))
        assert periods == [date(2026, 9, 1)]
        assert {p for (p,) in db.query(ValidationRun.period_month).filter(ValidationRun.entity_id == e)} == {
            date(2026, 9, 1)}
        events = [a.action for a in db.query(AuditEvent).filter(AuditEvent.entity_id == e)]
        assert "retention.policy_set" in events and "retention.applied" in events
        # Applied today already: the daily pass leaves it alone.
        stamp = db.query(RetentionPolicy).filter(RetentionPolicy.entity_id == e).one().last_applied_at
        dp.apply_due(db)
        db.expire_all()
        assert db.query(RetentionPolicy).filter(RetentionPolicy.entity_id == e).one().last_applied_at == stamp
    finally:
        db.close()


def test_the_daily_pass_counts_days_in_india_not_utc(client, company):
    """Applied at 20:39 UTC on 12 Oct is 02:09 IST on the 13th: already done for India's 13th.

    Comparing the UTC date with India's date re-applied the policy on every
    housekeeping pass from 18:30 to midnight UTC — an audit entry every ten
    minutes for five and a half hours a night.
    """
    from datetime import UTC, datetime, timedelta

    client.put("/api/data-protection/retention", headers=company,
               json={"payroll_months": 24, "reason": "Two years, per policy"})
    e = _entity(company)
    db = SessionLocal()
    try:
        policy = db.query(RetentionPolicy).filter(RetentionPolicy.entity_id == e).one()
        late_evening_utc = datetime(2026, 10, 12, 20, 39, tzinfo=UTC)
        policy.last_applied_at = late_evening_utc
        db.commit()
        dp.apply_due(db, today=date(2026, 10, 13))
        db.expire_all()
        stamp = db.query(RetentionPolicy).filter(RetentionPolicy.entity_id == e).one().last_applied_at
        assert stamp.replace(tzinfo=None) == late_evening_utc.replace(tzinfo=None)   # not applied again
        # The next Indian day is due.
        dp.apply_due(db, today=date(2026, 10, 14))
        db.expire_all()
        stamp = db.query(RetentionPolicy).filter(RetentionPolicy.entity_id == e).one().last_applied_at
        assert stamp.replace(tzinfo=None) > (late_evening_utc + timedelta(hours=1)).replace(tzinfo=None)
    finally:
        db.close()


def test_retention_takes_leavers_out_of_the_master(client, company):
    content = (b"employee_id,employee_name,date_of_joining,date_of_exit\n"
               b"L1,Long Gone,2015-04-01,2019-03-31\n"
               b"S1,Still Here,2015-04-01,\n")
    assert client.post("/api/workforce/master/commit", headers=company,
                       files={"file": ("m.csv", io.BytesIO(content), "text/csv")},
                       data={"meta": '{"effective_from": "2015-04-01"}'}).status_code == 200
    client.put("/api/data-protection/retention", headers=company,
               json={"payroll_months": 36, "reason": "Three years, per policy"})
    applied = _data(client.post("/api/data-protection/retention/apply", headers=company))
    assert applied["counts"]["Employee master (leavers)"] == 1
    db = SessionLocal()
    try:
        left = {r for (r,) in db.query(EmployeeRecord.employee_id).filter(EmployeeRecord.entity_id == _entity(company))}
        assert left == {"S1"}
    finally:
        db.close()


def test_retention_is_bounded_and_owner_only(client, company):
    r = client.put("/api/data-protection/retention", headers=company, json={"payroll_months": 6, "reason": "too short"})
    assert r.status_code in (400, 422)
    manager = _member(client, company, "manager")
    r = client.put("/api/data-protection/retention", headers=manager,
                   json={"payroll_months": 24, "reason": "manager tries"})
    assert r.status_code == 403
    assert client.post("/api/data-protection/retention/apply", headers=company).status_code == 409


# ── erasure ──────────────────────────────────────────────────────────────────

def test_erasure_leaves_no_identifier_in_working_data(client, company):
    _master(client, company)
    _validate(client, company, "2026-09-01", _register("2026-09-01", _rows()))
    needles = [PERSON, PAN, UAN, NAME, ACCOUNT]
    before = _scan(_entity(company), needles)
    assert set(before) == set(needles)                      # the scan can see them

    preview = _data(client.get(f"/api/data-protection/erasures/preview?employee_id={PERSON}", headers=company))
    assert preview["counts"]["Employee master"] == 1 and preview["counts"]["Register rows"] == 1

    r = client.post("/api/data-protection/erasures", headers=company,
                    json={"employee_id": PERSON, "confirm_employee_id": PERSON,
                          "reason": "Data principal request DP-2026-014"})
    assert r.status_code == 201, r.text
    done = r.json()["data"]
    assert done["counts"]["Employee master"] == 1 and done["counts"]["Uploaded register rows"] == 1

    after = _scan(_entity(company), needles)
    # The request record and the audit trail say whose data was erased; nothing else does.
    assert set(after.get(PERSON, [])) <= {"erasure_requests.employee_id", "audit_events.object_id",
                                          "audit_events.summary"}
    for needle in (PAN, UAN, NAME, ACCOUNT):
        assert needle not in after, (needle, after.get(needle))

    # The other employee is untouched.
    assert set(_scan(_entity(company), [OTHER_PAN])) == {OTHER_PAN}
    db = SessionLocal()
    try:
        rows = db.query(SalaryRegisterRow).filter(SalaryRegisterRow.entity_id == _entity(company)).all()
        ids = sorted(r.employee_id for r in rows)
        assert ids[0] == OTHER and ids[1].startswith("ERASED-")
        # The month still adds up: the pay stays, unattributed.
        assert all(r.components for r in rows)
        req = db.query(ErasureRequest).one()
        assert req.employee_id == PERSON and req.requested_by_email
        assert "ERASED-" not in json.dumps(req.counts) + json.dumps(req.retained)
    finally:
        db.close()

    listed = _data(client.get("/api/data-protection/erasures", headers=company))
    assert listed[0]["employee_id"] == PERSON and listed[0]["reason"].startswith("Data principal")


def test_erasure_refuses_an_unknown_id_and_a_mismatched_confirmation(client, company):
    _master(client, company)
    r = client.post("/api/data-protection/erasures", headers=company,
                    json={"employee_id": PERSON, "confirm_employee_id": PERSON + "X", "reason": "mismatch here"})
    assert r.status_code == 400
    r = client.post("/api/data-protection/erasures", headers=company,
                    json={"employee_id": "NOBODY1", "confirm_employee_id": "NOBODY1", "reason": "nobody at all"})
    assert r.status_code == 409 and "No data is held" in r.json()["error"]["detail"]


def test_erasure_is_owner_only(client, company):
    _master(client, company)
    manager = _member(client, company, "manager")
    r = client.post("/api/data-protection/erasures", headers=manager,
                    json={"employee_id": PERSON, "confirm_employee_id": PERSON, "reason": "manager tries"})
    assert r.status_code == 403


def test_signed_records_are_named_not_rewritten(client, company):
    """A month's sign-off is the record of what was approved: kept, and listed as kept."""
    _master(client, company)
    _validate(client, company, "2026-09-01", _register("2026-09-01", _rows()))
    db = SessionLocal()
    try:
        from app.models import PeriodSignOff

        db.add(PeriodSignOff(entity_id=_entity(company), period_month=date(2026, 9, 1), state="signed",
                             snapshot={"outstanding_findings": [{"employee_id": PERSON}]}, snapshot_digest="x"))
        db.commit()
    finally:
        db.close()
    r = client.post("/api/data-protection/erasures", headers=company,
                    json={"employee_id": PERSON, "confirm_employee_id": PERSON, "reason": "Data principal request"})
    assert r.status_code == 201, r.text
    done = r.json()["data"]
    stores = {r["store"]: r for r in done["retained"]}
    assert stores["Month sign-offs"]["count"] == 1 and "retention period" in stores["Month sign-offs"]["why"]
