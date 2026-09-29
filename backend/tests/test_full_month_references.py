"""
The batched full-month reference answers exactly as the per-employee one.

It replaced three queries per employee — most of a large validation's time —
so it has to be proven equal on every branch, not just the common one:

* E1 — CTC in force: the CTC wins, even though prior months exist.
* E2 — CTC dated after the period: ignored; falls back to the prior month.
* E3 — two prior months, the latest with no loss of pay: the latest is used.
* E4 — latest prior month had loss of pay: no baseline at all (not the earlier one).
* E5 — prior month with no attendance on file: no baseline.
* E6 — nothing on file: no baseline.
"""
from __future__ import annotations

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
    OrgMembership,
    SalaryRegister,
    SalaryRegisterRow,
)
from app.services.attendance_rules import FullMonthReferences, full_month_reference

JUNE, MAY, APRIL = date(2026, 6, 1), date(2026, 5, 1), date(2026, 4, 1)


@pytest.fixture()
def world(client):
    email = f"fmr-{uuid.uuid4().hex[:6]}@fmr-example.com"
    r = client.post("/api/auth/signup", json={"email": email, "password": "Passw0rd!x",
                                               "company_name": "FMR Pvt Ltd"})
    headers = {"Authorization": f"Bearer {r.json()['data']['access_token']}"}
    entity_id = uuid.UUID(client.post("/api/org/entities", headers=headers,
                                      json={"name": "FMR", "primary_state": "Karnataka"}).json()["data"]["id"])
    db = SessionLocal()
    try:
        entity = db.get(Entity, entity_id)
        user_id = db.query(OrgMembership).filter(OrgMembership.org_id == entity.org_id).first().user_id

        upload = CtcUpload(user_id=user_id, entity_id=entity_id, effective_from=APRIL, filename="ctc.csv")
        db.add(upload)
        db.flush()
        db.add(CtcRecord(upload_id=upload.id, user_id=user_id, entity_id=entity_id, employee_id="E1",
                         effective_from=APRIL, annual_components={"basic": 240000, "hra": 120000}))
        db.add(CtcRecord(upload_id=upload.id, user_id=user_id, entity_id=entity_id, employee_id="E2",
                         effective_from=date(2026, 7, 1), annual_components={"basic": 999999}))

        regs = {}
        for period in (APRIL, MAY):
            reg = SalaryRegister(user_id=user_id, entity_id=entity_id, period_month=period,
                                 filename="r.csv", employee_count=5)
            att = AttendanceRegister(user_id=user_id, entity_id=entity_id, period_month=period,
                                     filename="a.csv", employee_count=5)
            db.add_all([reg, att])
            db.flush()
            regs[period] = (reg, att)

        def pay(eid, period, gross):
            reg, _ = regs[period]
            db.add(SalaryRegisterRow(register_id=reg.id, user_id=user_id, entity_id=entity_id,
                                     period_month=period, employee_id=eid,
                                     components={"basic": gross}))

        def attend(eid, period, lop):
            _, att = regs[period]
            db.add(AttendanceRow(register_id=att.id, user_id=user_id, entity_id=entity_id,
                                 period_month=period, employee_id=eid, lop_days=Decimal(lop)))

        for eid in ("E1", "E2", "E3", "E4"):
            pay(eid, APRIL, 30000)
            attend(eid, APRIL, 0)
            pay(eid, MAY, 31000)
        attend("E1", MAY, 0)
        attend("E2", MAY, 0)
        attend("E3", MAY, 0)
        attend("E4", MAY, 2)
        pay("E5", MAY, 28000)  # no May attendance for E5
        db.commit()
        yield entity_id
    finally:
        db.close()


def test_batched_references_equal_the_per_employee_ones(world):
    db = SessionLocal()
    try:
        batch = FullMonthReferences(db, world, JUNE)
        for eid in ("E1", "E2", "E3", "E4", "E5", "E6"):
            assert batch.get(eid) == full_month_reference(db, world, eid, JUNE), eid

        assert batch.get("E1").source == "agreed CTC"
        assert batch.get("E1").amount == Decimal("30000.00")  # 360,000 / 12
        assert batch.get("E2").source == "May 2026"
        assert batch.get("E3").amount == Decimal("31000.00")
        assert batch.get("E4") is None
        assert batch.get("E5") is None
        assert batch.get("E6") is None
    finally:
        db.close()
