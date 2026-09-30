"""
Stored costings and cached input digests.

Both exist for speed (see app/models/derived_cache.py), and both would be
dangerous if they were ever used after their basis moved: a stored costing
would show last month's configuration as this month's cost, and a stale digest
would call an out-of-date run current. These tests pin that every change that
matters is seen, and that what is stored is exactly what would be computed.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.database import SessionLocal
from app.models import (
    EmployeeMasterUpload,
    EmployeeRecord,
    InputDigestCache,
    RegisterCosting,
    SalaryRegister,
    SalaryRegisterRow,
)
from app.services import analytics, costing_store, run_inputs
from app.services.cost_model import CostContext
from tests.test_cost_analysis import _dims, _register, workspace  # noqa: F401

MONTH = date(2026, 6, 1)
PRIOR = date(2026, 5, 1)


def _components(client, headers) -> dict:
    out = {}
    for name, flags in (("Basic", dict(pf_applicable=True, esic_applicable=True, pt_applicable=True,
                                       lwf_applicable=True)),
                        ("HRA", dict(pf_applicable=False, esic_applicable=True))):
        r = client.post("/api/components", headers=headers, json={
            "component_name": name, "included_in_wages": True, "taxable": True, **flags})
        assert r.status_code == 201, r.text
        out[name] = r.json()["data"]
    for rule_type in ("PT", "LWF"):
        client.post(f"/api/rule-engine/slabs/import-defaults/all?rule_type={rule_type}&overwrite=true",
                    headers=headers)
    return out


def _staff(n: int, *, uplift: float = 0.0) -> list[dict]:
    states = ("Karnataka", "Maharashtra", "Tamil Nadu")
    return [{"employee_id": f"E{i:03d}", "basic": 9000.0 + i * 911.0 + uplift,
             "dimensions": _dims(department=f"D{i % 3}", work_state=states[i % 3])}
            for i in range(n)]


def _rows(entity_id, period=MONTH):
    db = SessionLocal()
    try:
        return db, (db.query(SalaryRegisterRow)
                    .filter(SalaryRegisterRow.entity_id == entity_id, SalaryRegisterRow.period_month == period)
                    .all())
    except Exception:
        db.close()
        raise


def _fresh(entity_id, period=MONTH) -> dict:
    """Every row costed from scratch, nothing stored or read back."""
    db, rows = _rows(entity_id, period)
    try:
        context = CostContext(db, entity_id)
        flags = costing_store.pf_flags_as_of(db, entity_id, period)
        return {r.id: context.cost_row(r, pf_restricted=flags.get(r.employee_id)) for r in rows}
    finally:
        db.close()


def _through_store(entity_id, period=MONTH) -> dict:
    db, rows = _rows(entity_id, period)
    try:
        costing = analytics._Costing(db, entity_id)
        return {r.id: costing.cost(r) for r in rows}
    finally:
        db.close()


def _same(a: dict, b: dict) -> None:
    assert a.keys() == b.keys()
    for row_id in a:
        assert a[row_id].measures == b[row_id].measures, row_id
        assert a[row_id].reported_keys == b[row_id].reported_keys, row_id


def _stored_basis(entity_id) -> str | None:
    db = SessionLocal()
    try:
        reg = db.query(SalaryRegister).filter(SalaryRegister.entity_id == entity_id,
                                              SalaryRegister.period_month == MONTH).one()
        row = db.get(RegisterCosting, reg.id)
        return row.basis_digest if row else None
    finally:
        db.close()


# ── costing ─────────────────────────────────────────────────────────────────

def test_a_stored_costing_is_every_row_exactly_as_computed(client, workspace):
    entity, user, headers = workspace
    _components(client, headers)
    staff = _staff(30)
    staff[0]["dimensions"]["employment_type"] = "apprentice"
    _register(entity, user, MONTH, staff)
    db = SessionLocal()
    try:
        # A register that states its own figures: those win, and are stored as reported.
        row = db.query(SalaryRegisterRow).filter(SalaryRegisterRow.entity_id == entity.id,
                                                 SalaryRegisterRow.employee_id == "E001").one()
        row.deductions = {"ee_pf": 1234.5, "pt": 0}
        db.commit()
    finally:
        db.close()

    first = _through_store(entity.id)          # computes and stores
    assert _stored_basis(entity.id) is not None
    second = _through_store(entity.id)         # reads what was stored
    fresh = _fresh(entity.id)
    _same(first, fresh)
    _same(second, fresh)
    reported = next(c for rid, c in second.items() if c.measures["ee_pf"] == Decimal("1234.50"))
    assert reported.reported_keys == {"ee_pf", "pt"}


def test_a_configuration_change_is_costed_afresh(client, workspace):
    entity, user, headers = workspace
    comps = _components(client, headers)
    _register(entity, user, MONTH, _staff(12))
    before = _through_store(entity.id)
    basis = _stored_basis(entity.id)

    # HRA becomes PF-wage: employer PF moves for everyone.
    r = client.patch(f"/api/components/{comps['HRA']['id']}", headers=headers,
                     json={"pf_applicable": True})
    assert r.status_code == 200, r.text
    db, rows = _rows(entity.id)
    try:
        for row in rows:
            row_components = dict(row.components)
            row_components["hra"] = 4000.0
            row.components = row_components
        db.commit()
    finally:
        db.close()
    after = _through_store(entity.id)
    _same(after, _fresh(entity.id))
    assert _stored_basis(entity.id) != basis
    assert any(after[k].measures != before[k].measures for k in after)


def test_a_pf_flag_in_the_master_is_costed_afresh(client, workspace):
    entity, user, headers = workspace
    _components(client, headers)
    staff = _staff(4, uplift=20000.0)   # all above the PF ceiling
    _register(entity, user, MONTH, staff)
    db = SessionLocal()
    try:
        upload = EmployeeMasterUpload(user_id=user.id, entity_id=entity.id, effective_from=PRIOR,
                                      filename="m.csv", employee_count=1)
        db.add(upload)
        db.flush()
        db.add(EmployeeRecord(upload_id=upload.id, user_id=user.id, entity_id=entity.id,
                              employee_id="E002", effective_from=PRIOR, pf_restricted=False, extra={}))
        db.commit()
    finally:
        db.close()
    unrestricted = _through_store(entity.id)
    _same(unrestricted, _fresh(entity.id))

    db = SessionLocal()
    try:
        rec = db.query(EmployeeRecord).filter(EmployeeRecord.entity_id == entity.id).one()
        rec.pf_restricted = True
        db.commit()
    finally:
        db.close()
    restricted = _through_store(entity.id)
    _same(restricted, _fresh(entity.id))
    changed = [k for k in restricted if restricted[k].measures["er_pf"] != unrestricted[k].measures["er_pf"]]
    assert len(changed) == 1


def test_a_replaced_register_is_costed_afresh(client, workspace):
    entity, user, headers = workspace
    _components(client, headers)
    _register(entity, user, MONTH, _staff(6))
    first = analytics.cost_analysis(SessionLocal(), entity.id, group_by="department", measure="gross")

    # What a re-upload does (register_ingest): the rows go, new ones arrive.
    db = SessionLocal()
    try:
        reg = db.query(SalaryRegister).filter(SalaryRegister.entity_id == entity.id).one()
        db.query(SalaryRegisterRow).filter(SalaryRegisterRow.register_id == reg.id).delete()
        for r in _staff(6, uplift=1000.0):
            db.add(SalaryRegisterRow(register_id=reg.id, user_id=user.id, entity_id=entity.id,
                                     period_month=MONTH, employee_id=r["employee_id"],
                                     components={"basic": r["basic"]}, arrears={},
                                     increment_arrear_total=Decimal("0"), dimensions=r["dimensions"]))
        db.commit()
    finally:
        db.close()
    second = analytics.cost_analysis(SessionLocal(), entity.id, group_by="department", measure="gross")
    assert second["totals"]["gross"] == first["totals"]["gross"] + 6000
    _same(_through_store(entity.id), _fresh(entity.id))


# ── input digests ───────────────────────────────────────────────────────────

def _count_digests(monkeypatch) -> list:
    calls = []
    real = run_inputs._table_digest

    def counted(db, model, *criteria):
        calls.append(model.__tablename__)
        return real(db, model, *criteria)

    monkeypatch.setattr(run_inputs, "_table_digest", counted)
    return calls


def _digests(entity):
    db = SessionLocal()
    try:
        return run_inputs.input_digests(db, entity, MONTH, rows_sha256="x", config={})
    finally:
        db.close()


def test_an_input_digest_is_reused_until_that_input_is_written(client, workspace, monkeypatch):
    entity, user, headers = workspace
    _register(entity, user, PRIOR, _staff(5))
    calls = _count_digests(monkeypatch)

    first = _digests(entity)
    assert len(calls) == 4
    calls.clear()
    assert _digests(entity) == first
    assert calls == []

    # One changed amount in last month's register: that digest, and only that one.
    db = SessionLocal()
    try:
        row = db.query(SalaryRegisterRow).filter(SalaryRegisterRow.entity_id == entity.id,
                                                 SalaryRegisterRow.employee_id == "E003").one()
        row.components = {"basic": 1.0}
        db.commit()
    finally:
        db.close()
    third = _digests(entity)
    assert calls == ["salary_register_rows"]
    assert third["prior_register"] != first["prior_register"]
    assert {k: v for k, v in third.items() if k != "prior_register"} == \
        {k: v for k, v in first.items() if k != "prior_register"}

    # A bulk delete cannot be tied to one company, so every company recomputes.
    calls.clear()
    db = SessionLocal()
    try:
        db.query(SalaryRegisterRow).filter(SalaryRegisterRow.entity_id == entity.id,
                                           SalaryRegisterRow.employee_id == "E004").delete()
        db.commit()
    finally:
        db.close()
    fourth = _digests(entity)
    assert calls == ["salary_register_rows"]
    assert fourth["counts"]["prior_register_rows"] == 4


def test_one_company_writing_does_not_invalidate_another(client, workspace, monkeypatch):
    entity, user, headers = workspace
    _register(entity, user, PRIOR, _staff(3))
    _digests(entity)
    db = SessionLocal()
    try:
        assert db.query(InputDigestCache).filter(InputDigestCache.entity_id == entity.id).count() == 4
    finally:
        db.close()

    other = client.post("/api/org/entities", headers={"Authorization": headers["Authorization"]},
                        json={"name": "Another company"}).json()["data"]["id"]
    import uuid as _uuid

    from app.models import Entity
    db = SessionLocal()
    try:
        other_entity = db.get(Entity, _uuid.UUID(other))
        db.expunge(other_entity)
    finally:
        db.close()
    _register(other_entity, user, PRIOR, _staff(3))

    calls = _count_digests(monkeypatch)
    _digests(entity)
    assert calls == []
