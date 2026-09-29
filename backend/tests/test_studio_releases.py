"""
Studio phase 4: the developer workspace, environments and releases.

* The workspace evaluates with the product's own whitelisted evaluator,
  explains, refuses what it refuses, and treats absent as absent.
* Scripting is off and says why.
* Releases go upward only, carry mappings and workflows — never data,
  connections or secrets — re-resolve references by name in the target,
  preview their impact, need someone other than the author to approve,
  promote all-or-nothing by adding versions, and roll back by another release.
"""
from __future__ import annotations

import uuid

import pytest

from app.database import SessionLocal
from app.models import AuditEvent, EmployeeRecord, StudioConnection, StudioMapping, StudioRun, StudioWorkflow
from tests.test_approvals import _second_manager
from tests.test_run_history import _company, _data, _empty_queue  # noqa: F401
from tests.test_studio_sync import MAPPING, _connection, _published_mapping, _stream, hrms  # noqa: F401
from tests.test_studio_workflows import _me


@pytest.fixture()
def pair(client, hrms):
    """One organisation, two companies: A (test) and B (production)."""
    from tests.test_studio_sync import Mock, _employees

    Mock.employees = _employees()
    Mock.flaky_left = 0
    a = _company(client, "rel")
    b_id = _data(client.post("/api/org/entities", headers={"Authorization": a["Authorization"]},
                             json={"name": "Release target", "primary_state": "Karnataka"}))["id"]
    b = {"Authorization": a["Authorization"], "X-Entity-Id": b_id}
    for h in (a, b):
        assert client.post("/api/studio/destinations", headers=h, json={"host": "127.0.0.1"}).status_code == 200
    return a, b


# ---------------------------------------------------------------------------
# Developer workspace
# ---------------------------------------------------------------------------
def test_workspace_explains_tests_and_refuses(client, pair):
    a, _ = pair
    out = _data(client.post("/api/studio/developer/formula", headers=a, json={
        "expression": "min(pf_wage, 15000) * 0.12",
        "samples": [{"pf_wage": "₹18,000"}, {"pf_wage": ""}, {"pf_wage": "12000"}]}))
    assert out["ok"] and out["variables"] == ["pf_wage"] and "smaller of" in out["in_words"]
    assert out["results"][0]["value"] == 1800.0 and out["results"][2]["value"] == 1440.0
    assert "Absent is not zero" in out["results"][1]["error"]
    for bad in ("__import__('os')", "a.__class__", "open('x')", "[1, 2]", "(lambda: 1)()"):
        refused = _data(client.post("/api/studio/developer/formula", headers=a, json={"expression": bad, "samples": [{}]}))
        assert not refused["ok"] and refused["error"], bad
    look = _data(client.post("/api/studio/developer/lookup", headers=a, json={
        "table": {"BLR": "Karnataka"}, "values": ["BLR", "XYZ"], "on_unmatched": "reject"}))
    assert look["results"][0]["result"] == "Karnataka" and "no entry" in look["results"][1]["error"]
    cond = _data(client.post("/api/studio/developer/conditions", headers=a, json={
        "conditions": [{"field": "data.counts.rejected", "op": "gt", "value": 0}],
        "samples": [{"data": {"counts": {"rejected": 2}}}, {"data": {"counts": {"rejected": "n/a"}}}]}))
    assert [r["holds"] for r in cond["results"]] == [True, False], "not comparable is not true"
    ref = _data(client.get("/api/studio/developer/reference", headers=a))
    assert ref["scripting"]["enabled"] is False and "isolation" in ref["scripting"]["reason"]


# ---------------------------------------------------------------------------
# Releases
# ---------------------------------------------------------------------------
def _setup_source(client, a, hrms):
    conn = _connection(client, a, hrms, name="HRMS")
    _published_mapping(client, a)
    stream = _stream(client, a, conn["id"], name="Employees")
    run = _data(client.post(f"/api/studio/streams/{stream['id']}/sync", headers=a))  # a synthetic test run
    from tests.test_studio_sync import _drain

    _drain()
    wf = _data(client.post("/api/studio/workflows", headers=a, json={"name": "Nightly", "definition": {
        "trigger": {"type": "manual"},
        "actions": [{"type": "sync", "params": {"stream_id": stream["id"]}},
                    {"type": "notify", "params": {"user_ids": [_me(client, a)], "title": "Synced {{period}}"}}]}}))
    _data(client.post(f"/api/studio/workflows/{wf['id']}/publish", headers=a))
    return conn, stream, run


def test_releases_go_upward_and_carry_configuration_only(client, pair, hrms):
    a, b = pair
    _setup_source(client, a, hrms)
    # Both production: refused.
    r = client.post("/api/studio/releases", headers=a, json={
        "target_entity_id": b["X-Entity-Id"], "title": "First", "items": [{"kind": "mapping", "name": "hrms-employees"}]})
    assert r.status_code == 400 and "Releases go upward" in r.text
    assert client.put("/api/studio/environment", headers=a, json={"environment": "test"}).status_code == 200
    for kind in ("connection", "employee_master", "webhook", "credentials"):
        r = client.post("/api/studio/releases", headers=a, json={
            "target_entity_id": b["X-Entity-Id"], "title": "Sneaky", "items": [{"kind": kind, "name": "x"}]})
        assert r.status_code == 400 and "never data, connections or secrets" in r.text, kind
    # Downward is refused too.
    r = client.post("/api/studio/releases", headers=b, json={
        "target_entity_id": a["X-Entity-Id"], "title": "Down", "items": [{"kind": "mapping", "name": "hrms-employees"}]})
    assert r.status_code == 400


def test_the_full_path_with_independent_approval_and_rollback(client, pair, hrms):
    a, b = pair
    _setup_source(client, a, hrms)
    client.put("/api/studio/environment", headers=a, json={"environment": "test"})
    # The target already has v1 of this mapping, used by a run: that history must survive.
    old_spec = {**MAPPING, "fields": MAPPING["fields"][:3]}
    old = _published_mapping(client, b, spec=old_spec)
    old_fields = old["spec"]["fields"]  # as stored: normalised on save
    rel = _data(client.post("/api/studio/releases", headers=a, json={
        "target_entity_id": b["X-Entity-Id"], "title": "June mapping and nightly flow",
        "items": [{"kind": "mapping", "name": "hrms-employees"}, {"kind": "workflow", "name": "Nightly"}]}))
    items = {i["kind"]: i for i in rel["impact"]["items"]}
    assert items["mapping"]["change"] == "update" and items["mapping"]["diff"]
    assert items["mapping"]["tested"]["status"] in ("completed", "partially_completed"), "evidence it was tried in test"
    assert items["workflow"]["change"] == "create"
    assert any("No stream" in p for p in items["workflow"]["blocking"]), "the stream does not exist in B yet"
    assert any("Never run" in w for w in items["workflow"]["warnings"])
    r = client.post(f"/api/studio/releases/{rel['id']}/submit", headers=a)
    assert r.status_code == 409 and "blocking" in r.text

    # B gets its own connection and stream — its own credentials — under the same names.
    conn_b = _connection(client, b, hrms, name="HRMS")
    stream_b = _stream(client, b, conn_b["id"], name="Employees")
    rel = _data(client.get(f"/api/studio/releases/{rel['id']}", headers=a))
    assert rel["impact"]["blocking"] == 0
    _data(client.post(f"/api/studio/releases/{rel['id']}/submit", headers=a))

    # The author cannot approve their own release; a second manager can.
    r = client.post(f"/api/studio/releases/{rel['id']}/decide", headers=a, json={"approve": True})
    assert r.status_code == 409 and "someone other than its author" in r.text
    checker = _second_manager(client, b)
    _data(client.post(f"/api/studio/releases/{rel['id']}/decide", headers=checker, json={"approve": True, "note": "Checked"}))
    done = _data(client.post(f"/api/studio/releases/{rel['id']}/promote", headers=checker))
    assert done["status"] == "promoted"
    outcomes = {r["kind"]: r for r in done["result"]}
    assert outcomes["mapping"]["outcome"] == "published" and outcomes["mapping"]["version"] == 2

    db = SessionLocal()
    try:
        bid = uuid.UUID(b["X-Entity-Id"])
        v1 = db.get(StudioMapping, uuid.UUID(old["id"]))
        assert v1.status == "published" and v1.spec["fields"] == old_fields, "history is not rewritten"
        wf = db.query(StudioWorkflow).filter(StudioWorkflow.entity_id == bid, StudioWorkflow.name == "Nightly").one()
        assert wf.status == "disabled", "a new workflow arrives disabled; a person enables it"
        assert wf.active_definition["actions"][0]["params"]["stream_id"] == stream_b["id"], "re-resolved in B"
        assert db.query(StudioConnection).filter(StudioConnection.entity_id == bid).count() == 1, "no connection copied"
        assert db.query(EmployeeRecord).filter(EmployeeRecord.entity_id == bid).count() == 0, "no payroll data copied"
        assert db.query(StudioRun).filter(StudioRun.entity_id == bid).count() == 0, "no runs copied"
        audited = {e.action for e in db.query(AuditEvent).filter(AuditEvent.entity_id == bid).all()}
        assert {"studio.release.approved", "studio.release.promoted"} <= audited
    finally:
        db.close()

    # Roll back: another release, approved the same way, restoring what was replaced.
    back = _data(client.post(f"/api/studio/releases/{rel['id']}/rollback", headers=checker))
    assert back["rollback_of_id"] == rel["id"] and back["status"] == "draft"
    _data(client.post(f"/api/studio/releases/{back['id']}/submit", headers=checker))
    assert client.post(f"/api/studio/releases/{back['id']}/decide", headers=checker,
                       json={"approve": True}).status_code == 409
    _data(client.post(f"/api/studio/releases/{back['id']}/decide", headers=a, json={"approve": True}))
    _data(client.post(f"/api/studio/releases/{back['id']}/promote", headers=a))
    db = SessionLocal()
    try:
        rows = (db.query(StudioMapping).filter(StudioMapping.entity_id == bid, StudioMapping.key == "hrms-employees")
                .order_by(StudioMapping.version).all())
        assert [r.version for r in rows] == [1, 2, 3], "rollback adds a version; it deletes nothing"
        assert rows[2].spec["fields"] == old_fields and rows[2].status == "published"
        wf = db.query(StudioWorkflow).filter(StudioWorkflow.entity_id == bid, StudioWorkflow.name == "Nightly").one()
        assert wf.status == "disabled"
    finally:
        db.close()


def test_releases_are_invisible_outside_their_organisation(client, pair, hrms):
    a, b = pair
    _setup_source(client, a, hrms)
    client.put("/api/studio/environment", headers=a, json={"environment": "test"})
    rel = _data(client.post("/api/studio/releases", headers=a, json={
        "target_entity_id": b["X-Entity-Id"], "title": "Mapping only", "items": [{"kind": "mapping", "name": "hrms-employees"}]}))
    stranger = _company(client, "rel-stranger")
    assert client.get(f"/api/studio/releases/{rel['id']}", headers=stranger).status_code == 404
    assert client.post(f"/api/studio/releases/{rel['id']}/submit", headers=stranger).status_code == 404
    assert _data(client.get("/api/studio/releases", headers=stranger)) == []
    # A target in another organisation cannot be named.
    r = client.post("/api/studio/releases", headers=a, json={
        "target_entity_id": stranger["X-Entity-Id"], "title": "Across", "items": [{"kind": "mapping", "name": "hrms-employees"}]})
    assert r.status_code == 404
