"""
Dated statutory changes: drafted, published from a month, withdrawn.

The base configuration applies to every month no published version covers.
A draft changes nothing. Publishing puts a version in force from its month
until the next one, for validation and for costing alike, and marks exactly
the validated months it covers as needing revalidation — naming the
configuration as what changed. Withdrawing puts those months back.
"""
from __future__ import annotations

import uuid
from datetime import date

from app.database import SessionLocal
from app.models import Entity, OrgMembership
from app.services.config_service import ConfigService
from tests.test_coverage import BASE_ROWS, _outcome, _register, _run
from tests.test_run_history import PERIOD, _company, _data, _drain

JUNE, JULY = "2026-06-01", "2026-07-01"


def _config(client, company, ceiling: int) -> dict:
    base = _data(client.get("/api/config/statutory", headers=company))
    cfg = {k: base[k] for k in ("pf", "esic", "component_mapping")}
    cfg["pf"]["wage"]["wage_ceiling"] = str(ceiling)
    return cfg


def _draft(client, company, month: str, ceiling: int, note="Budget") -> dict:
    return _data(client.post("/api/config/statutory/versions", headers=company, json={
        "effective_from": month, "config": _config(client, company, ceiling), "note": note}))


def _ceiling(company, month: str) -> str:
    db = SessionLocal()
    try:
        entity_id = uuid.UUID(company["X-Entity-Id"])
        return str(ConfigService(db, as_of=date.fromisoformat(month)).get_pf_config(entity_id).wage.wage_ceiling)
    finally:
        db.close()


def _freshness(client, company, run_id) -> dict:
    return _data(client.get(f"/api/validation/runs/{run_id}", headers=company))["freshness"]


def _revalidate(client, company) -> str:
    job = _data(client.post("/api/validation/jobs", headers=company, json={"period_month": PERIOD}))["job"]
    _drain()
    return _data(client.get(f"/api/validation/jobs/{job['id']}", headers=company))["run_id"]


def test_a_draft_changes_nothing_and_a_later_month_leaves_earlier_runs_current(client):
    company = _company(client, "sv1")
    run_id = _run(client, company, _register(BASE_ROWS))
    assert _outcome(client, company, run_id, "E001", "STAT-001")["outcome"] == "passed"

    july = _draft(client, company, JULY, 25000)
    assert july["status"] == "draft" and july["effective_from"] == JULY
    assert any(c["field"] == "pf.wage.wage_ceiling" for c in july["changes"])
    assert _ceiling(company, JULY) == "15000"                        # a draft is not in force

    published = _data(client.post(f"/api/config/statutory/versions/{july['id']}/publish", headers=company))
    assert published["status"] == "published" and published["affected_months"] == []
    assert _ceiling(company, JULY) == "25000" and _ceiling(company, JUNE) == "15000"
    assert _freshness(client, company, run_id)["is_current_for_inputs"] is True


def test_publishing_a_change_for_a_validated_month_marks_it_and_the_rerun_uses_it(client):
    company = _company(client, "sv2")
    run_id = _run(client, company, _register(BASE_ROWS))
    june = _draft(client, company, JUNE, 25000)
    assert june["affected_months"] == [JUNE]                           # says what publishing would touch
    published = _data(client.post(f"/api/config/statutory/versions/{june['id']}/publish", headers=company))
    assert published["affected_months"] == [JUNE]

    fresh = _freshness(client, company, run_id)
    assert fresh["revalidation_required"] is True
    assert [c["input"] for c in fresh["changes"]] == ["configuration"]

    # E001's register deducted PF on ₹15,000. From June the ceiling is ₹25,000.
    rerun = _revalidate(client, company)
    assert _outcome(client, company, rerun, "E001", "STAT-001")["outcome"] == "failed"

    # Withdrawn: June falls back to the base, and the run made under the version is stale.
    assert client.post(f"/api/config/statutory/versions/{june['id']}/withdraw", headers=company,
                       json={"reason": ""}).status_code == 422
    withdrawn = _data(client.post(f"/api/config/statutory/versions/{june['id']}/withdraw", headers=company,
                                  json={"reason": "Entered a month early"}))
    assert withdrawn["status"] == "withdrawn" and withdrawn["withdraw_reason"] == "Entered a month early"
    assert _ceiling(company, JUNE) == "15000"
    assert _freshness(client, company, rerun)["revalidation_required"] is True
    again = _revalidate(client, company)
    assert _outcome(client, company, again, "E001", "STAT-001")["outcome"] == "passed"


def test_costing_reads_the_version_in_force_for_each_month(client):
    from app.models import SalaryRegister, SalaryRegisterRow, User
    from app.services import analytics

    company = _company(client, "sv3")
    entity_id = uuid.UUID(company["X-Entity-Id"])
    db = SessionLocal()
    try:
        owner = db.query(OrgMembership).join(Entity, Entity.org_id == OrgMembership.org_id).filter(
            Entity.id == entity_id).first()
        user = db.get(User, owner.user_id)
        for month in (date(2026, 6, 1), date(2026, 7, 1)):
            reg = SalaryRegister(user_id=user.id, entity_id=entity_id, period_month=month, filename="r.csv", employee_count=1)
            db.add(reg)
            db.flush()
            db.add(SalaryRegisterRow(register_id=reg.id, user_id=user.id, entity_id=entity_id, period_month=month,
                                     employee_id="E1", components={"basic": 30000.0}, arrears={}, deductions={},
                                     dimensions={}, increment_arrear_total=0))
        db.commit()
    finally:
        db.close()
    july = _draft(client, company, JULY, 25000)
    _data(client.post(f"/api/config/statutory/versions/{july['id']}/publish", headers=company))

    db = SessionLocal()
    try:
        result = analytics.cost_analysis(db, entity_id, group_by="department", measure="er_pf")
    finally:
        db.close()
    by_month = {p["period"]: p["measures"]["er_pf"] for p in result["period_totals"]}
    assert by_month["2026-06-01"] < by_month["2026-07-01"]              # the higher ceiling from July only


def test_publishing_is_for_managers_one_per_month_and_independent_when_required(client):
    company = _company(client, "sv4")
    first = _draft(client, company, JULY, 20000)
    _data(client.post(f"/api/config/statutory/versions/{first['id']}/publish", headers=company))
    second = _draft(client, company, JULY, 22000)
    clash = client.post(f"/api/config/statutory/versions/{second['id']}/publish", headers=company)
    assert clash.status_code == 409 and "Withdraw it first" in clash.json()["error"]["detail"]
    # A published change is not edited; it is withdrawn and drafted again.
    assert client.put(f"/api/config/statutory/versions/{first['id']}", headers=company, json={
        "effective_from": JULY, "config": _config(client, company, 21000)}).status_code == 409

    policy = client.put("/api/org/approval-policy", headers=company,
                        json={"statutory_publish_requires_independent_approver": True})
    assert policy.status_code == 200, policy.text
    own = client.post(f"/api/config/statutory/versions/{second['id']}/withdraw", headers=company,
                      json={"reason": "clash"})  # withdrawing the first needs no second person
    assert own.status_code == 409  # second is a draft, not published
    refused = client.post(f"/api/config/statutory/versions/{second['id']}/publish", headers=company)
    assert refused.status_code in (403, 409)

    third = _draft(client, company, "2026-09-01", 23000)
    self_publish = client.post(f"/api/config/statutory/versions/{third['id']}/publish", headers=company)
    assert self_publish.status_code == 403 and "someone other than" in self_publish.json()["error"]["detail"]

    # An analyst may draft but never publish.
    db = SessionLocal()
    try:
        entity = db.get(Entity, uuid.UUID(company["X-Entity-Id"]))
        member = db.query(OrgMembership).filter(OrgMembership.org_id == entity.org_id).first()
        member.role = "analyst"
        db.commit()
    finally:
        db.close()
    draft = _draft(client, company, "2026-10-01", 24000)
    assert client.post(f"/api/config/statutory/versions/{draft['id']}/publish", headers=company).status_code == 403
    listing = _data(client.get("/api/config/statutory/versions", headers=company))
    assert listing["independent_publish"] is True
    assert {v["status"] for v in listing["versions"]} == {"published", "draft"}
