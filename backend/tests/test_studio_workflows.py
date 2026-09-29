"""
Studio workflows (phase 3): trigger → conditions → actions, run by the worker.

The properties that matter, each tested:

* a definition can name only safe actions — signing, waiving, publishing and
  approving are refused when it is saved;
* the chain fetch → readiness → validate → assign → notify → webhook runs,
  waiting for the work it starts, and links to what it produced;
* an event starts a workflow once, however often it is fanned out;
* a workflow never triggers itself, chains stop, and runaway starts are capped;
* "inputs ready" fires once per distinct set of inputs;
* failures take the failure branch; steps retry, time out and can be cancelled;
* a dry run does nothing;
* notifications reach only the people named, and only they can read them;
* nothing crosses companies.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.database import SessionLocal
from app.models import (
    FindingState,
    StudioEvent,
    StudioNotification,
    StudioRun,
    StudioWorkflow,
    StudioWorkflowFire,
)
from app.services.studio import webhooks as hooks_svc
from app.services.studio import worker as studio_worker
from app.services.studio import workflows as flows
from tests.test_coverage import BASE_ROWS, HEADER, _register
from tests.test_run_history import PERIOD, _company, _data, _drain, _empty_queue  # noqa: F401
from tests.test_studio_api import _key, submit
from tests.test_studio_sync import _connection, _published_mapping, _stream, hrms  # noqa: F401


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(flows, "WAIT_SECONDS", 0)
    monkeypatch.setattr(flows, "STEP_BACKOFF_SECONDS", 0)
    monkeypatch.setattr(studio_worker, "BACKOFF_SECONDS", 0)


@pytest.fixture()
def company(client, hrms):
    from app.services.studio import ratelimit
    from tests.test_studio_sync import Mock, _employees

    ratelimit.reset()
    Mock.employees = _employees()
    Mock.flaky_left = 0
    headers = _company(client, "flows")
    assert client.post("/api/studio/destinations", headers=headers, json={"host": "127.0.0.1"}).status_code == 200
    return headers


def _settle(rounds: int = 40) -> None:
    """Run the Studio worker and the validation worker until both are idle."""
    for _ in range(rounds):
        db = SessionLocal()
        try:
            did = studio_worker.drain(db)
        finally:
            db.close()
        did += _drain()
        if not did:
            return


def _me(client, headers) -> str:
    return _data(client.get("/api/auth/me", headers=headers))["id"]


def _register_records():
    cols = HEADER.split(",")
    return [dict(zip(cols, line.split(","), strict=True))
            for line in _register(BASE_ROWS).decode().strip().split("\n")[1:]]


def _flow(client, headers, definition, name=None, publish=True):
    wf = _data(client.post("/api/studio/workflows", headers=headers,
                           json={"name": name or f"Flow {uuid.uuid4().hex[:4]}", "definition": definition}))
    if publish:
        wf = _data(client.post(f"/api/studio/workflows/{wf['id']}/publish", headers=headers))
    return wf


def _run(client, headers, wf_id, period=PERIOD):
    return _data(client.post(f"/api/studio/workflows/{wf_id}/run", headers=headers, json={"period": period}))


def _get_run(client, headers, run_id):
    return _data(client.get(f"/api/studio/runs/{run_id}", headers=headers))


def _notify(user_id, title="{{workflow}} finished for {{period}}"):
    return {"type": "notify", "params": {"user_ids": [user_id], "title": title, "body": "Counts: {{counts.received}}"}}


# ---------------------------------------------------------------------------
# Definitions
# ---------------------------------------------------------------------------
def test_definitions_refuse_decisions_that_belong_to_people(client, company):
    me = _me(client, company)
    for forbidden in ("sign_off", "waive_finding", "resolve_finding", "publish_rule", "submit_period", "approve"):
        r = client.post("/api/studio/workflows", headers=company, json={"name": "Bad", "definition": {
            "trigger": {"type": "manual"}, "actions": [{"type": forbidden}]}})
        assert r.status_code == 400 and "No workflow can do it" in r.text, forbidden
    r = client.post("/api/studio/workflows", headers=company, json={"name": "Bad", "definition": {
        "trigger": {"type": "manual"}, "actions": [_notify(me)],
        "on_failure": [{"type": "start_validation"}]}})
    assert r.status_code == 400 and "failure branch may only" in r.text
    r = client.post("/api/studio/workflows", headers=company, json={"name": "Bad", "definition": {
        "trigger": {"type": "on_payday"}, "actions": [_notify(me)]}})
    assert r.status_code == 400 and "Unknown trigger" in r.text
    catalogue = _data(client.get("/api/studio/workflows/catalogue", headers=company))
    assert "sign_off" in catalogue["not_available"] and "sign_off" not in catalogue["actions"]


def test_nothing_crosses_companies(client, company, hrms):
    other = _company(client, "flows-other")
    client.post("/api/studio/destinations", headers=other, json={"host": "127.0.0.1"})
    conn = _connection(client, other, hrms)
    _published_mapping(client, other)
    stream = _stream(client, other, conn["id"])
    r = client.post("/api/studio/workflows", headers=company, json={"name": "Theirs", "definition": {
        "trigger": {"type": "manual"}, "actions": [{"type": "sync", "params": {"stream_id": stream["id"]}}]}})
    assert r.status_code == 400 and "no such stream in this company" in r.text
    stranger = _me(client, other)
    r = client.post("/api/studio/workflows", headers=company, json={"name": "Tell them", "definition": {
        "trigger": {"type": "manual"}, "actions": [_notify(stranger)]}})
    assert r.status_code == 400 and "cannot see this company" in r.text
    mine = _flow(client, company, {"trigger": {"type": "manual"}, "actions": [_notify(_me(client, company))]})
    assert client.get(f"/api/studio/workflows/{mine['id']}", headers=other).status_code == 404
    assert client.post(f"/api/studio/workflows/{mine['id']}/run", headers=other, json={}).status_code == 404


# ---------------------------------------------------------------------------
# The chain
# ---------------------------------------------------------------------------
def test_fetch_check_validate_assign_notify_webhook(client, company, hrms):
    me = _me(client, company)
    conn = _connection(client, company, hrms)
    _published_mapping(client, company)
    stream = _stream(client, company, conn["id"], import_options={"period": PERIOD})
    k = _key(client, company)
    submit(client, k["key"], "salary_register", {"period_month": PERIOD, "records": _register_records()})
    hook = _data(client.post("/api/studio/webhooks", headers=company, json={
        "name": "Finance", "url": f"{hrms}/receive", "events": ["workflow.finished"]}))
    wf = _flow(client, company, {
        "trigger": {"type": "manual"},
        "actions": [
            {"type": "sync", "params": {"stream_id": stream["id"]}},
            {"type": "check_readiness", "params": {"required": ["register", "master"]}},
            {"type": "start_validation"},
            {"type": "assign_findings", "params": {"owner_user_id": me, "due_in_days": 3,
                                                   "severities": ["CRITICAL", "WARNING", "INFO"]}},
            _notify(me),
            {"type": "webhook", "params": {"webhook_id": hook["id"], "message": "{{period}} validated"}},
        ]})
    started = _run(client, company, wf["id"])
    assert started["status"] == "queued" and started["kind"] == "workflow"
    _settle()
    run = _get_run(client, company, started["id"])
    steps = run["workflow"]["steps"]
    assert run["status"] == "partially_completed", run  # the sync rejected two HRMS records: a warning
    assert [s["status"] for s in steps] == ["warning", "completed", "completed", "completed", "completed", "completed"]
    assert steps[0]["ref"]["run_id"] and "rejected" in steps[0]["message"]
    assert run["workflow"]["validation_run_id"] and run["links"]["validation_run_id"] == run["workflow"]["validation_run_id"]
    assert run["versions"]["workflow"].endswith("v1")
    child = _get_run(client, company, steps[0]["ref"]["run_id"])
    assert child["trigger"] == "workflow"
    db = SessionLocal()
    try:
        owned = db.query(FindingState).filter(FindingState.entity_id == uuid.UUID(company["X-Entity-Id"])).all()
        assert owned and all(str(f.owner_user_id) == me and f.due_date for f in owned)
        assert all(f.state in ("open", "acknowledged") for f in owned), "a workflow never waives or resolves"
        sent = db.query(StudioEvent).filter(StudioEvent.type == "workflow.message",
                                            StudioEvent.entity_id == uuid.UUID(company["X-Entity-Id"])).one()
        assert sent.data["message"] == f"{PERIOD} validated" and sent.only_webhook_id == uuid.UUID(hook["id"])
        assert sent.causation["workflow_id"] == wf["id"]
    finally:
        db.close()
    notes = _data(client.get("/api/studio/notifications", headers=company))
    assert notes["unread"] == 1 and PERIOD in notes["items"][0]["title"]
    assert notes["items"][0]["link"].startswith("/payroll/results?run=")
    # The month's integration picture shows the sync and the workflow.
    month = _data(client.get(f"/api/studio/period/{PERIOD[:7]}", headers=company))
    kinds = {r["kind"] for r in month["runs"]}
    assert {"sync", "workflow", "import"} <= kinds


def test_readiness_failure_takes_the_failure_branch(client, company):
    me = _me(client, company)
    wf = _flow(client, company, {
        "trigger": {"type": "manual"},
        "actions": [{"type": "check_readiness", "params": {"required": ["register", "attendance"]}},
                    {"type": "start_validation"}],
        "on_failure": [_notify(me, "{{workflow}} stopped")]})
    run = _run(client, company, wf["id"])
    _settle()
    run = _get_run(client, company, run["id"])
    assert run["status"] == "failed" and "not ready" in run["error"]["message"]
    assert "no register, attendance" in run["error"]["message"]
    assert [s["status"] for s in run["workflow"]["steps"]] == ["failed", "skipped"]
    assert run["workflow"]["failure_branch"][0]["status"] == "completed"
    assert run["error"]["recommended_action"]
    notes = _data(client.get("/api/studio/notifications", headers=company))["items"]
    assert notes[0]["title"].endswith("stopped")


def test_a_failing_step_retries_then_fails(client, company):
    me = _me(client, company)
    wf = _flow(client, company, {"trigger": {"type": "manual"}, "actions": [
        {"type": "check_readiness", "retries": 2, "params": {"required": ["register"]}}, _notify(me)]})
    run = _run(client, company, wf["id"])
    _settle()
    run = _get_run(client, company, run["id"])
    assert run["status"] == "failed" and run["workflow"]["steps"][0]["attempt"] == 3


def test_steps_time_out_and_runs_can_be_cancelled(client, company, hrms):
    me = _me(client, company)
    conn = _connection(client, company, hrms)
    _published_mapping(client, company)
    stream = _stream(client, company, conn["id"])
    wf = _flow(client, company, {"trigger": {"type": "manual"},
                                 "actions": [{"type": "sync", "timeout_minutes": 1, "params": {"stream_id": stream["id"]}},
                                             _notify(me)],
                                 "on_failure": [_notify(me, "timed out")]})
    run = _run(client, company, wf["id"])
    db = SessionLocal()
    try:
        # One worker turn: the workflow starts its sync and waits.
        from app.services.studio import runs as runs_svc

        claimed = runs_svc.claim(db, "t")
        flows.process(db, claimed)
        r = db.get(StudioRun, uuid.UUID(run["id"]))
        state = dict(r.result_ref)
        assert state["steps"][0]["status"] == "waiting"
        child_id = state["steps"][0]["ref"]["run_id"]
        # Pretend the step started long ago.
        steps = [dict(s) for s in state["steps"]]
        steps[0]["started_at"] = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
        r.result_ref = {**state, "steps": steps}
        db.commit()
    finally:
        db.close()
    # Hold the child: it must not finish before the timeout is seen.
    db = SessionLocal()
    try:
        child = db.get(StudioRun, uuid.UUID(child_id))
        child.queued_at = datetime.now(UTC) + timedelta(hours=1)
        db.commit()
        claimed = runs_svc.claim(db, "t")
        assert claimed.id == uuid.UUID(run["id"])
        flows.process(db, claimed)
    finally:
        db.close()
    timed = _get_run(client, company, run["id"])
    assert timed["status"] == "failed" and "timed out" in timed["error"]["message"]

    # Cancellation stops the run and the sync it is waiting on.
    run2 = _run(client, company, wf["id"])
    db = SessionLocal()
    try:
        claimed = runs_svc.claim(db, "t")
        while claimed is not None and claimed.id != uuid.UUID(run2["id"]):
            claimed = runs_svc.claim(db, "t")
        flows.process(db, claimed)
        child2 = dict(db.get(StudioRun, uuid.UUID(run2["id"])).result_ref)["steps"][0]["ref"]["run_id"]
    finally:
        db.close()
    cancelled = _data(client.post(f"/api/studio/runs/{run2['id']}/cancel", headers=company))
    assert cancelled["status"] == "cancelled"
    assert _get_run(client, company, child2)["status"] == "cancelled"


# ---------------------------------------------------------------------------
# Events, duplicates, loops
# ---------------------------------------------------------------------------
def test_an_event_starts_a_workflow_once_and_never_its_own(client, company, hrms):
    me = _me(client, company)
    conn = _connection(client, company, hrms)
    _published_mapping(client, company)
    stream = _stream(client, company, conn["id"])
    # On every finished import, sync again — the classic loop.
    wf = _flow(client, company, {"trigger": {"type": "import.completed"},
                                 "conditions": [{"field": "data.object_type", "op": "eq", "value": "employee_master"}],
                                 "actions": [{"type": "sync", "params": {"stream_id": stream["id"]}}, _notify(me)]})
    first = _data(client.post(f"/api/studio/streams/{stream['id']}/sync", headers=company))
    _settle()
    db = SessionLocal()
    try:
        flows_runs = db.query(StudioRun).filter(StudioRun.workflow_id == uuid.UUID(wf["id"]),
                                                StudioRun.kind == "workflow").all()
        assert len(flows_runs) == 1, "the person's sync fired it once; its own sync did not fire it again"
        w = db.get(StudioWorkflow, uuid.UUID(wf["id"]))
        assert "never triggers itself" in w.last_skip["reason"]
        # Fanning the same event out again starts nothing new.
        event = (db.query(StudioEvent).filter(StudioEvent.type == "import.completed",
                                              StudioEvent.entity_id == uuid.UUID(company["X-Entity-Id"]))
                 .order_by(StudioEvent.created_at).first())
        assert event.data["run_id"] == first["id"]
        assert flows.on_event(db, event) == 0
        db.commit()
        assert db.query(StudioWorkflowFire).filter(StudioWorkflowFire.workflow_id == w.id).count() == 1
        # A chain of workflows stops at the limit.
        event.causation = {"workflow_id": str(uuid.uuid4()), "depth": flows.MAX_DEPTH}
        event.id = uuid.uuid4()
        assert flows.fire(db, w, trigger_key="deep", trigger={}, actor=db.get(__import__("app.models", fromlist=["User"]).User, uuid.UUID(me)),
                          actor_label="t", causation=event.causation) is None
        assert "cannot loop" in w.last_skip["reason"]
        db.rollback()
    finally:
        db.close()


def test_runaway_starts_are_capped(client, company):
    me = _me(client, company)
    wf = _flow(client, company, {"trigger": {"type": "manual"}, "actions": [_notify(me)]})
    client.patch(f"/api/studio/workflows/{wf['id']}", headers=company, json={"max_runs_per_hour": 1})
    _run(client, company, wf["id"])
    r = client.post(f"/api/studio/workflows/{wf['id']}/run", headers=company, json={"period": PERIOD})
    assert r.status_code == 409 and "limit" in r.text


def test_inputs_ready_fires_once_per_set_of_inputs(client, company):
    me = _me(client, company)
    wf = _flow(client, company, {"trigger": {"type": "inputs.ready", "required": ["register", "master"]},
                                 "actions": [_notify(me, "{{period}} is ready")]})
    k = _key(client, company)
    ids = sorted({r["employee_id"] for r in _register_records()})
    master = {"effective_from": PERIOD, "records": [{"employee_id": i, "employee_name": f"P {i}"} for i in ids]}
    submit(client, k["key"], "employee_master", master)
    _settle()
    db = SessionLocal()
    count = lambda: db.query(StudioRun).filter(StudioRun.workflow_id == uuid.UUID(wf["id"])).count()  # noqa: E731
    try:
        assert count() == 0, "a master alone is not ready"
        submit(client, k["key"], "salary_register", {"period_month": PERIOD, "records": _register_records()})
        _settle()
        assert count() == 1
        submit(client, k["key"], "employee_master", master)  # the same inputs again
        _settle()
        assert count() == 1, "unchanged inputs do not fire twice"
    finally:
        db.close()
    notes = _data(client.get("/api/studio/notifications", headers=company))["items"]
    assert notes[0]["title"] == f"{PERIOD} is ready"


# ---------------------------------------------------------------------------
# Dry runs, approval, notifications
# ---------------------------------------------------------------------------
def test_dry_run_does_nothing(client, company):
    me = _me(client, company)
    definition = {"trigger": {"type": "import.completed"},
                  "conditions": [{"field": "data.counts.rejected", "op": "gt", "value": 0}],
                  "actions": [{"type": "check_readiness", "params": {"required": ["register"]}},
                              _notify(me, "{{event.data.counts.rejected}} rejected")]}
    plan = _data(client.post("/api/studio/workflows/dry-run", headers=company, json={
        "definition": definition, "sample": {"data": {"counts": {"rejected": 3}, "period_month": PERIOD}}}))
    assert plan["would_run"] and plan["conditions"][0]["actual"] == 3
    assert plan["steps"][0]["warning"].startswith("Would fail now")
    assert plan["steps"][1]["title"] == "3 rejected" and plan["steps"][1]["recipients"]
    quiet = _data(client.post("/api/studio/workflows/dry-run", headers=company, json={
        "definition": definition, "sample": {"data": {"counts": {"rejected": 0}}}}))
    assert not quiet["would_run"]
    db = SessionLocal()
    try:
        assert db.query(StudioRun).filter(StudioRun.entity_id == uuid.UUID(company["X-Entity-Id"])).count() == 0
        assert db.query(StudioNotification).filter(StudioNotification.entity_id == uuid.UUID(company["X-Entity-Id"])).count() == 0
    finally:
        db.close()


def test_publishing_follows_the_approval_policy(client, company):
    me = _me(client, company)
    wf = _flow(client, company, {"trigger": {"type": "manual"}, "actions": [_notify(me)]}, publish=False)
    assert client.post(f"/api/studio/workflows/{wf['id']}/run", headers=company, json={}).status_code == 409
    assert client.put("/api/org/approval-policy", headers=company,
                      json={"studio_publish_requires_independent_approver": True}).status_code == 200
    refused = client.post(f"/api/studio/workflows/{wf['id']}/publish", headers=company)
    assert refused.status_code == 409 and "someone other" in refused.text


def test_notifications_are_private(client, company):
    me = _me(client, company)
    wf = _flow(client, company, {"trigger": {"type": "manual"}, "actions": [_notify(me)]})
    _run(client, company, wf["id"])
    _settle()
    mine = _data(client.get("/api/studio/notifications", headers=company))
    assert mine["unread"] == 1
    other = _company(client, "flows-peer")
    theirs = _data(client.get("/api/studio/notifications", headers=other))
    assert theirs["unread"] == 0 and theirs["items"] == []
    # Marking someone else's notification read does nothing.
    assert _data(client.post("/api/studio/notifications/read", headers=other,
                             json={"ids": [mine["items"][0]["id"]]}))["marked"] == 0
    assert _data(client.post("/api/studio/notifications/read", headers=company, json={}))["marked"] == 1
    assert _data(client.get("/api/studio/notifications", headers=company))["unread"] == 0


def test_the_outbox_fan_out_starts_workflows_in_its_own_transaction(client, company):
    """An event fanned out and rolled back is picked up again — and still starts one run."""
    me = _me(client, company)
    wf = _flow(client, company, {"trigger": {"type": "period.reopened"}, "actions": [_notify(me)]})
    db = SessionLocal()
    try:
        from app.models import Entity
        from app.services.studio import events

        entity = db.get(Entity, uuid.UUID(company["X-Entity-Id"]))
        events.emit(db, org_id=entity.org_id, entity_id=entity.id, type="period.reopened",
                    data={"period_month": PERIOD})
        db.commit()
        ev = db.query(StudioEvent).filter(StudioEvent.type == "period.reopened",
                                          StudioEvent.entity_id == entity.id).one()
        flows.on_event(db, ev)
        db.rollback()  # the fan-out died before committing
        while hooks_svc.fan_out(db):  # earlier tests leave their events behind
            pass
        ev.dispatched_at = None  # as if a second worker saw it again
        db.commit()
        while hooks_svc.fan_out(db):
            pass
        assert db.query(StudioRun).filter(StudioRun.workflow_id == uuid.UUID(wf["id"])).count() == 1
    finally:
        db.close()
