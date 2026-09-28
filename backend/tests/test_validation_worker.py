"""The worker.

PR 1 tested the queue in isolation. This tests the thing that drains it, and the
tests worth having are the ones about what happens when it goes wrong: a worker
killed mid-job, two workers racing for one job, a job that keeps failing, a
register deleted underneath one.

The happy path gets one test. It is not where the risk is.
"""
from __future__ import annotations

import io
import json
import threading
import uuid
from datetime import date

import pytest

from app.database import SessionLocal
from app.models import ComponentConfig, Entity, User, ValidationJob
from app.models.register import SalaryRegister
from app.services import validation_jobs as jobs
from app.services import validation_worker as worker

PASSWORD = "Passw0rd!x"
PERIOD = date(2026, 6, 1)

COMPONENTS = [
    {"component_name": "Basic", "pf_applicable": True, "esic_applicable": True,
     "pt_applicable": True, "lwf_applicable": True, "included_in_wages": True, "taxable": True},
    {"component_name": "HRA", "esic_applicable": True, "pt_applicable": True, "taxable": True},
]

REGISTER_CSV = """employee_id,employee_name,basic,hra,paid_days,state,pf_employee,esic_employee,pt
E001,Asha Rao,30000,12000,30,Karnataka,1800,0,200
E002,Bharat Singh,18000,7000,30,Karnataka,2160,0,200
E003,Chitra Menon,12000,4000,30,Karnataka,1440,135,0
"""


@pytest.fixture(autouse=True)
def _empty_queue():
    """`claim` is global, so another test's leftovers would be claimed here."""
    db = SessionLocal()
    try:
        db.query(ValidationJob).delete()
        db.commit()
    finally:
        db.close()
    yield


@pytest.fixture()
def ready(client, request):
    """An entity with components and a stored register, plus a queued job for it."""
    email = f"vw-{request.node.name[:34]}@worker-example.com".replace("_", "-")
    r = client.post("/api/auth/signup",
                    json={"email": email, "password": PASSWORD, "company_name": "Worker Tests"})
    if r.status_code != 200:
        r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    headers = {"Authorization": f"Bearer {r.json()['data']['access_token']}"}
    entity_id = client.post("/api/org/entities",
                            json={"name": f"VW-{request.node.name[:24]}",
                                  "primary_state": "Karnataka"},
                            headers=headers).json()["data"]["id"]
    headers["X-Entity-Id"] = entity_id
    for comp in COMPONENTS:
        client.post("/api/components", json=comp, headers=headers)

    upload = client.post(
        "/api/payroll/upload",
        files={"file": ("register.csv", io.BytesIO(REGISTER_CSV.encode()), "text/csv")},
        data={"meta": json.dumps({"period_month": PERIOD.isoformat()})},
        headers=headers,
    )
    assert upload.status_code == 200, upload.text

    db = SessionLocal()
    try:
        entity = db.get(Entity, uuid.UUID(entity_id))
        user = db.query(User).filter(User.email == email).one()
        register = (
            db.query(SalaryRegister)
            .filter(SalaryRegister.entity_id == entity.id,
                    SalaryRegister.period_month == PERIOD)
            .one()
        )
        job = jobs.enqueue(
            db,
            entity_id=entity.id,
            user_id=user.id,
            period_month=PERIOD,
            register_id=register.id,
        )
        db.commit()
        ids = (job.id, entity.id, register.id)
    finally:
        db.close()
    return headers, ids


# ---------------------------------------------------------------------------
def test_the_worker_validates_the_register_and_records_a_run(ready):
    _, (job_id, _entity_id, _register_id) = ready
    db = SessionLocal()
    try:
        assert worker.run_once(db, "w1") is True
        job = db.get(ValidationJob, job_id)
        assert job.state == "succeeded", job.error
        assert job.run_id is not None
        assert job.employee_total == 3
        assert job.employee_done == 3
        assert job.finished_at is not None
        assert job.error is None
    finally:
        db.close()


def test_an_empty_queue_is_not_an_error(ready):
    db = SessionLocal()
    try:
        assert worker.run_once(db, "w1") is True      # the queued job
        assert worker.run_once(db, "w1") is False     # nothing left
    finally:
        db.close()


def test_progress_never_exceeds_the_total(ready):
    _, (job_id, _e, _r) = ready
    db = SessionLocal()
    try:
        worker.run_once(db, "w1")
        job = db.get(ValidationJob, job_id)
        assert 0 <= job.employee_done <= job.employee_total
    finally:
        db.close()


def test_the_run_the_worker_recorded_is_the_one_the_client_can_read(client, ready):
    """A run nobody can fetch is the same as no run at all."""
    headers, (job_id, _e, _r) = ready

    db = SessionLocal()
    try:
        worker.run_once(db, "w1")
        job = db.get(ValidationJob, job_id)
        assert job.state == "succeeded", job.error
        run_id = str(job.run_id)
    finally:
        db.close()

    runs = client.get("/api/findings/runs", headers=headers)
    assert runs.status_code == 200, runs.text
    assert run_id in {str(r["id"]) for r in runs.json()["data"]}

    findings = client.get("/api/findings", headers=headers)
    assert findings.status_code == 200, findings.text


# --- failure modes ---------------------------------------------------------
def test_two_workers_racing_for_one_job_run_it_once(ready):
    """SKIP LOCKED on PostgreSQL; on SQLite there is one writer anyway."""
    _, (job_id, _e, _r) = ready
    outcomes: list[bool] = []
    errors: list[BaseException] = []

    def attempt(name):
        db = SessionLocal()
        try:
            outcomes.append(worker.run_once(db, name))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            db.close()

    threads = [threading.Thread(target=attempt, args=(f"w{i}",)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert not errors, errors
    db = SessionLocal()
    try:
        job = db.get(ValidationJob, job_id)
        assert job.state == "succeeded", job.error
        # Claimed once. A second claim would have incremented attempts again.
        assert job.attempts == 1, f"job ran {job.attempts} times"
    finally:
        db.close()


def test_a_job_whose_worker_died_is_reclaimed(ready):
    """A lease that stopped being renewed is the only crash signal there is."""
    from datetime import UTC, datetime, timedelta

    from app.models import LEASE_SECONDS

    _, (job_id, _e, _r) = ready
    db = SessionLocal()
    try:
        # Claim it, then abandon it the way a SIGKILL would.
        claimed = jobs.claim(db, "dead-worker")
        assert claimed is not None
        claimed.heartbeat_at = datetime.now(UTC) - timedelta(seconds=LEASE_SECONDS * 2)
        db.commit()

        assert worker.run_once(db, "live-worker") is True
        job = db.get(ValidationJob, job_id)
        assert job.state == "succeeded", job.error
        assert job.attempts == 2, "the reclaim should count as another attempt"
        # succeed() releases the lock, so the lock itself is gone by now; the
        # attempt count is what proves a second worker picked the job up.
        assert job.locked_by is None
    finally:
        db.close()


def test_a_job_with_no_register_fails_rather_than_hanging(ready):
    _, (job_id, _e, _r) = ready
    db = SessionLocal()
    try:
        db.get(ValidationJob, job_id).register_id = None
        db.commit()

        assert worker.run_once(db, "w1") is True
        job = db.get(ValidationJob, job_id)
        assert job.state == "queued", "first failure should be retried, not terminal"
        assert job.error and "register" in job.error.lower()
    finally:
        db.close()


def test_a_job_that_keeps_failing_stops_rather_than_looping(ready):
    """Terminal means terminal. An endless retry is a busy loop, not resilience."""
    _, (job_id, _e, _r) = ready
    db = SessionLocal()
    try:
        job = db.get(ValidationJob, job_id)
        job.register_id = None
        job.max_attempts = 2
        db.commit()

        worker.run_once(db, "w1")
        assert db.get(ValidationJob, job_id).state == "queued"

        worker.run_once(db, "w1")
        job = db.get(ValidationJob, job_id)
        assert job.state == "failed"
        assert job.attempts == 2

        # Nothing claims a terminal job again.
        assert worker.run_once(db, "w1") is False
    finally:
        db.close()


def test_an_entity_with_no_components_fails_with_a_readable_reason(ready):
    _, (job_id, entity_id, _r) = ready
    db = SessionLocal()
    try:
        db.query(ComponentConfig).filter(ComponentConfig.entity_id == entity_id).delete()
        db.commit()

        worker.run_once(db, "w1")
        job = db.get(ValidationJob, job_id)
        assert job.state == "queued"
        assert "component" in (job.error or "").lower()
    finally:
        db.close()


def test_drain_empties_the_queue_and_reports_how_many_ran(ready):
    db = SessionLocal()
    try:
        assert worker.drain(db, "w1") == 1
        assert worker.drain(db, "w1") == 0
    finally:
        db.close()


def test_the_worker_does_not_start_unless_the_environment_asks(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "validation_worker_enabled", False)
    assert worker.start_in_thread() == []


def test_the_loop_stops_when_asked():
    stopper = threading.Event()
    thread = threading.Thread(target=worker.loop, args=("w-loop", stopper), daemon=True)
    thread.start()
    stopper.set()
    thread.join(timeout=30)
    assert not thread.is_alive(), "the loop ignored its stop event"
