"""
The queue.

Nothing calls this yet — it is built before the endpoint that will use it, so
that the behaviour under failure is settled while it is still cheap to change.

The tests that matter are not "a job can be queued". They are the ones about
what happens when a worker dies, when two workers race, and when the same
request arrives twice — because those are the cases that, unhandled, lose a
client's month during close week.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from app.database import SessionLocal
from app.models import (
    LEASE_SECONDS,
    Entity,
    Organization,
    User,
    ValidationJob,
    ValidationRun,
)
from app.services import validation_jobs as jobs

PERIOD = date(2026, 6, 1)


@pytest.fixture()
def world(client, request):
    """One entity and one user, straight in the database — no HTTP involved."""
    import hashlib

    slug = hashlib.sha256(request.node.name.encode()).hexdigest()[:12]
    db = SessionLocal()
    try:
        org = Organization(name=f"Queue Co {slug}")
        db.add(org)
        db.flush()
        entity = Entity(org_id=org.id, name=f"Queue Entity {slug}", code=f"Q{slug[:8].upper()}")
        user = User(
            email=f"queue-{slug}@jobs-example.com",
            password_hash="x",  # nosec B106 - never authenticated against
            company_name="Queue Co",
            role="user",
        )
        db.add_all([entity, user])
        db.commit()
        yield {"entity_id": entity.id, "user_id": user.id}
    finally:
        db.close()


def make(db, world, **kw) -> ValidationJob:
    return jobs.enqueue(
        db,
        entity_id=world["entity_id"],
        user_id=world["user_id"],
        period_month=kw.pop("period_month", PERIOD),
        **kw,
    )


@pytest.fixture()
def db():
    """
    A session with an empty queue.

    `claim` is deliberately global — any worker takes the oldest job anywhere,
    which is what makes workers interchangeable in production. It also means one
    test's leftover job is claimable by the next, so the table is cleared
    between tests rather than the claim being narrowed to suit them.
    """
    session = SessionLocal()
    session.query(ValidationJob).delete()
    session.commit()
    try:
        yield session
    finally:
        session.rollback()
        session.query(ValidationJob).delete()
        session.commit()
        session.close()


# ---------------------------------------------------------------------------
# Enqueuing
# ---------------------------------------------------------------------------
def test_a_queued_job_starts_with_nothing_done(db, world):
    job = make(db, world, run_type="increment", params={"as_of_date": "2026-06-30"})
    db.commit()

    assert job.state == "queued"
    assert job.attempts == 0
    assert job.employee_done == 0
    assert job.run_id is None
    assert job.params["as_of_date"] == "2026-06-30"


def test_the_same_period_cannot_be_queued_twice(db, world):
    """A double-click must not validate the month twice."""
    make(db, world)
    db.commit()

    with pytest.raises(jobs.AlreadyQueued):
        make(db, world)


def test_a_finished_period_can_be_validated_again(db, world):
    """The guard is on live work, not on the period forever."""
    first = make(db, world)
    db.commit()
    jobs.succeed(db, first, run_id=None)
    db.commit()

    again = make(db, world)
    db.commit()
    assert again.id != first.id
    assert again.state == "queued"


# ---------------------------------------------------------------------------
# Claiming
# ---------------------------------------------------------------------------
def test_claiming_marks_the_job_running_and_counts_the_attempt(db, world):
    make(db, world)
    db.commit()

    job = jobs.claim(db, "worker-1")
    db.commit()

    assert job is not None
    assert job.state == "running"
    assert job.locked_by == "worker-1"
    assert job.attempts == 1
    assert job.started_at is not None and job.heartbeat_at is not None


def test_only_one_worker_gets_a_given_job(db, world):
    """
    The second claim finds nothing.

    On PostgreSQL this is FOR UPDATE SKIP LOCKED doing the work. On SQLite there
    are no concurrent writers, so the same outcome follows from the state change
    — which is the point: the caller sees identical behaviour either way.
    """
    make(db, world)
    db.commit()

    first = jobs.claim(db, "worker-1")
    db.commit()
    second = jobs.claim(db, "worker-2")

    assert first is not None
    assert second is None


def test_nothing_to_claim_returns_none(db, world):
    assert jobs.claim(db, "worker-1") is None


def test_the_oldest_job_is_claimed_first(db, world):
    older = make(db, world, period_month=date(2026, 4, 1))
    older.queued_at = datetime.now(UTC) - timedelta(hours=2)
    newer = make(db, world, period_month=date(2026, 5, 1))
    newer.queued_at = datetime.now(UTC)
    db.commit()

    claimed = jobs.claim(db, "worker-1")
    assert claimed is not None
    assert claimed.id == older.id


# ---------------------------------------------------------------------------
# Crash recovery — the reason the lease exists
# ---------------------------------------------------------------------------
def test_a_job_whose_worker_died_is_reclaimed(db, world):
    """
    A deploy or an OOM kill leaves a job in 'running' with nobody on it.

    Without this it would sit there for the rest of the close, and the client
    would be told their validation was in progress indefinitely.
    """
    make(db, world)
    db.commit()
    lost = jobs.claim(db, "worker-that-dies")
    lost.heartbeat_at = datetime.now(UTC) - timedelta(seconds=LEASE_SECONDS + 30)
    db.commit()

    reclaimed = jobs.claim(db, "worker-2")
    db.commit()

    assert reclaimed is not None
    assert reclaimed.id == lost.id
    assert reclaimed.locked_by == "worker-2"
    assert reclaimed.attempts == 2, "a reclaim is another attempt, and must count as one"


def test_a_live_worker_keeps_its_job(db, world):
    make(db, world)
    db.commit()
    held = jobs.claim(db, "worker-1")
    jobs.heartbeat(db, held)
    db.commit()

    assert jobs.claim(db, "worker-2") is None
    assert jobs.lease_expired(held) is False


def test_a_job_that_never_heartbeat_is_still_reclaimable(db, world):
    """Dying between the claim and the first heartbeat is the tightest window."""
    make(db, world)
    db.commit()
    stuck = jobs.claim(db, "worker-1")
    stuck.heartbeat_at = None
    stuck.started_at = datetime.now(UTC) - timedelta(seconds=LEASE_SECONDS + 30)
    db.commit()

    assert jobs.lease_expired(stuck) is True
    assert jobs.claim(db, "worker-2") is not None


# ---------------------------------------------------------------------------
# Failing
# ---------------------------------------------------------------------------
def test_a_failure_with_attempts_left_goes_back_to_the_queue(db, world):
    make(db, world)
    db.commit()
    job = jobs.claim(db, "worker-1")
    jobs.fail(db, job, error="connection reset")
    db.commit()

    assert job.state == "queued"
    assert job.error == "connection reset"
    assert job.finished_at is None


def test_a_failure_that_exhausts_its_attempts_stops(db, world):
    """
    A rule that raises on one employee's data will raise every time. An endless
    retry loop is a worse failure than a visible one.
    """
    job = make(db, world)
    job.max_attempts = 2
    db.commit()

    for _ in range(2):
        claimed = jobs.claim(db, "worker-1")
        assert claimed is not None
        jobs.fail(db, claimed, error="boom")
        db.commit()

    assert job.state == "failed"
    assert job.finished_at is not None
    assert jobs.claim(db, "worker-2") is None, "a failed job must not be picked up again"


def test_a_long_error_is_truncated_rather_than_refused(db, world):
    make(db, world)
    db.commit()
    job = jobs.claim(db, "worker-1")
    jobs.fail(db, job, error="x" * 5000)
    db.commit()
    assert len(job.error) == 2000


# ---------------------------------------------------------------------------
# Progress and completion
# ---------------------------------------------------------------------------
def test_progress_never_exceeds_the_total(db, world):
    """A progress bar reading 11,000 of 10,000 is one nobody trusts again."""
    make(db, world)
    db.commit()
    job = jobs.claim(db, "worker-1")
    job.employee_total = 100
    jobs.heartbeat(db, job, done=250)
    db.commit()

    assert job.employee_done == 100
    assert jobs.describe(job)["percent"] == 100


def test_success_records_the_run_and_completes_the_count(db, world):
    """
    The handover: a finished job points at the run that holds the findings.

    `run_id` is a real foreign key, so this creates a real run rather than
    inventing an id — PostgreSQL rejects a dangling reference even though
    SQLite, with foreign keys off by default, would let it through.
    """
    make(db, world)
    db.commit()
    job = jobs.claim(db, "worker-1")
    job.employee_total = 40
    jobs.heartbeat(db, job, done=17)
    db.commit()

    run = ValidationRun(
        user_id=world["user_id"],
        entity_id=world["entity_id"],
        period_month=PERIOD,
        employee_count=40,
    )
    db.add(run)
    db.flush()

    jobs.succeed(db, job, run_id=run.id)
    db.commit()

    assert job.state == "succeeded"
    assert job.run_id == run.id
    assert job.employee_done == 40, "a finished job showing 17 of 40 reads as broken"
    assert job.error is None
    assert jobs.claim(db, "worker-2") is None


def test_cancelling_is_terminal_and_frees_the_period(db, world):
    make(db, world)
    db.commit()
    job = jobs.claim(db, "worker-1")
    jobs.mark_cancelled(db, job)
    db.commit()

    assert job.state == "cancelled"
    assert jobs.claim(db, "worker-2") is None
    make(db, world)  # the period is free again
    db.commit()


def test_describe_reports_percent_without_dividing_by_zero(db, world):
    job = make(db, world)
    db.commit()
    assert jobs.describe(job)["percent"] == 0
