"""
Syncing a connection's streams: fetch, map, import, checkpoint.

**Behaviour, per stream, stated rather than implied:**

* *Source of truth and direction.* Inbound only: the external system is the
  source of truth for the fields it sends. PeopleOpsLab never writes back to
  it; results leave through the integration API and webhooks instead.
* *Matching.* Employee id (plus effective date for CTC). Leading zeros kept.
* *Upsert.* ``import_options.mode`` — ``upsert`` (default: update matches,
  add new, leave the rest) or ``replace`` (the version becomes the fetch).
* *Duplicates and conflicts.* Identical repeats skipped; conflicting records
  for one employee all rejected; rejected records wait in the run for a
  correction at source or a retry — the manual-correction policy.
* *Full or incremental.* Incremental sends the last committed watermark as a
  "modified since" parameter; full fetches everything.
* *Deletion.* Never inferred from absence. ``import_options.deletions``:
  ``ignore`` (default), ``report`` (after a full sync, employees stored but
  absent from the fetch are listed on the run — nothing is removed), or
  ``replace`` (a full replace removes them; only for a stream declared
  complete). Deactivation is the date of exit the source sends.
* *Checkpoint.* Advanced in the **same transaction** that stores the records
  and finishes the run, and only if the run stored something. A crash before
  that commit leaves the old checkpoint, so the next run fetches the same
  records again — and upsert makes that replay produce "unchanged", never
  duplicates.
* *Retries.* A provider outage (connection error, 5xx, 429) is retried with
  backoff up to ``max_attempts``; a refusal (bad credentials, destination not
  allowed) fails at once with what to do.
"""
from __future__ import annotations

import calendar
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import Entity, StudioConnection, StudioRun, StudioStream, User
from app.services import audit
from app.services.studio import connections, egress, imports, profiles, runs
from app.services.studio import secrets as vault

EVERY = ("hour", "day", "week")
DEFAULT_TZ = "Asia/Kolkata"


class SyncError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class TransientSyncError(Exception):
    """A failure worth retrying: the worker requeues the run with backoff."""


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------
def check_schedule(schedule: dict[str, Any] | None) -> dict[str, Any]:
    if not schedule:
        return {}
    every = schedule.get("every")
    if every not in EVERY:
        raise SyncError("A schedule runs every hour, day or week — or leave it empty for manual only.")
    tz = schedule.get("timezone") or DEFAULT_TZ
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise SyncError(f"Unknown time zone {tz}.") from exc
    at = schedule.get("at") or "02:00"
    try:
        hh, mm = (int(x) for x in at.split(":"))
    except ValueError as exc:
        raise SyncError("The time is HH:MM, 24-hour.") from exc
    if not (0 <= hh < 24 and 0 <= mm < 60):
        raise SyncError("The time is HH:MM, 24-hour.")
    out = {"every": every, "at": f"{hh:02d}:{mm:02d}", "timezone": tz}
    if every == "week":
        weekday = int(schedule.get("weekday", 0))
        if not 0 <= weekday <= 6:
            raise SyncError("Weekday is 0 (Monday) to 6 (Sunday).")
        out["weekday"] = weekday
    return out


def next_run(schedule: dict[str, Any], after: datetime) -> datetime | None:
    """The first scheduled moment strictly after ``after``, in UTC."""
    if not schedule:
        return None
    tz = ZoneInfo(schedule.get("timezone") or DEFAULT_TZ)
    hh, mm = (int(x) for x in schedule.get("at", "02:00").split(":"))
    local = after.astimezone(tz)
    if schedule["every"] == "hour":
        candidate = local.replace(minute=mm, second=0, microsecond=0)
        if candidate <= local:
            candidate += timedelta(hours=1)
    elif schedule["every"] == "day":
        candidate = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if candidate <= local:
            candidate += timedelta(days=1)
    else:
        candidate = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
        candidate += timedelta(days=(schedule.get("weekday", 0) - candidate.weekday()) % 7)
        if candidate <= local:
            candidate += timedelta(days=7)
    return candidate.astimezone(UTC)


# ---------------------------------------------------------------------------
# Streams
# ---------------------------------------------------------------------------
def _check_stream(db: Session, entity: Entity, body: dict[str, Any]) -> dict[str, Any]:
    object_type = body.get("object_type")
    if object_type not in ("employee_master", "ctc", "attendance", "salary_register"):
        raise SyncError("Object type must be employee_master, ctc, attendance or salary_register.")
    pagination = body.get("pagination") or {"type": "none"}
    if pagination.get("type", "none") not in ("none", "page", "offset", "cursor"):
        raise SyncError("Pagination is none, page, offset or cursor.")
    if int(pagination.get("size", 500)) > 5000:
        raise SyncError("A page may be at most 5,000 records.")
    sync_mode = body.get("sync_mode") or "full"
    if sync_mode not in ("full", "incremental"):
        raise SyncError("Sync mode is full or incremental.")
    if sync_mode == "incremental" and not (body.get("watermark_field") and body.get("watermark_param")):
        raise SyncError("Incremental sync needs the field that says when a record changed (watermark field) and "
                        "the parameter the system filters by (watermark parameter).")
    options = dict(body.get("import_options") or {})
    mode = options.get("mode") or ("replace" if object_type == "salary_register" else "upsert")
    if object_type == "ctc":
        mode = "upsert"
    options["mode"] = mode
    deletions = options.get("deletions") or "ignore"
    if deletions not in ("ignore", "report", "replace"):
        raise SyncError("Deletions are ignore, report or replace.")
    if deletions == "replace" and (sync_mode != "full" or object_type not in ("employee_master", "attendance")):
        raise SyncError("Replace (remove what the source no longer sends) needs a full sync of a master or attendance stream.")
    if deletions == "replace":
        options["mode"] = "replace"
    options["deletions"] = deletions
    period = options.get("period") or ("current_month" if object_type == "employee_master" else "previous_month")
    if period not in ("current_month", "previous_month") and not _is_month(period):
        raise SyncError("Period is current_month, previous_month or a date like 2026-06-01.")
    options["period"] = period
    mapping_key = body.get("mapping_key") or None
    if mapping_key:
        versions = profiles.versions(db, entity.id, mapping_key)
        if not versions:
            raise SyncError(f"No mapping called {mapping_key}.")
        if versions[0].object_type != object_type:
            raise SyncError(f"Mapping {mapping_key} is for {versions[0].object_type}, not {object_type}.")
    return {
        "name": (body.get("name") or object_type).strip()[:100], "object_type": object_type,
        "path": (body.get("path") or "").strip(), "records_path": (body.get("records_path") or "").strip(),
        "pagination": pagination, "sync_mode": sync_mode, "watermark_field": body.get("watermark_field"),
        "watermark_param": body.get("watermark_param"), "import_options": options,
        "mapping_key": mapping_key, "mapping_version": body.get("mapping_version"),
        "schedule": check_schedule(body.get("schedule")), "max_attempts": max(1, min(int(body.get("max_attempts", 3)), 10)),
        "max_pages": max(1, min(int(body.get("max_pages", 200)), 2000)), "enabled": bool(body.get("enabled", True)),
    }


def _is_month(value: str) -> bool:
    try:
        date.fromisoformat(value)
        return True
    except (TypeError, ValueError):
        return False


def save_stream(db: Session, entity: Entity, conn: StudioConnection, actor: User, body: dict[str, Any],
                stream: StudioStream | None = None) -> StudioStream:
    values = _check_stream(db, entity, body)
    if conn.provider == "rest" and not values["path"]:
        raise SyncError("A REST stream needs the path it is read from, e.g. /employees.")
    if stream is None:
        stream = StudioStream(connection_id=conn.id, entity_id=entity.id, checkpoint={}, **values)
        db.add(stream)
    else:
        for k, v in values.items():
            setattr(stream, k, v)
    stream.next_run_at = next_run(stream.schedule, _now()) if stream.enabled and stream.schedule else None
    db.flush()
    audit.record(db, entity_id=entity.id, user=actor, action="studio.stream.saved", object_type="studio_stream",
                 object_id=str(stream.id), summary=f"Saved {stream.object_type} stream “{stream.name}” on “{conn.name}”"
                 + (f", {stream.schedule['every']}ly at {stream.schedule['at']} {stream.schedule['timezone']}"
                    if stream.schedule else ", manual only"))
    return stream


def reset_checkpoint(db: Session, entity: Entity, stream: StudioStream, actor: User) -> None:
    old = dict(stream.checkpoint or {})
    stream.checkpoint = {}
    audit.record(db, entity_id=entity.id, user=actor, action="studio.stream.checkpoint_reset",
                 object_type="studio_stream", object_id=str(stream.id),
                 summary=f"Reset the checkpoint of “{stream.name}” — the next sync fetches everything",
                 detail={"previous": old})


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------
def _period(options: dict[str, Any], today: date) -> date:
    period = options.get("period")
    first = today.replace(day=1)
    if period == "current_month":
        return first
    if period == "previous_month":
        return (first - timedelta(days=1)).replace(day=1)
    return date.fromisoformat(period).replace(day=1)


def start(db: Session, entity: Entity, stream: StudioStream, *, actor: User, actor_label: str,
          actor_type: str = "user", trigger: str = "manual") -> StudioRun:
    conn = db.get(StudioConnection, stream.connection_id)
    if conn is None or conn.status != "active":
        raise SyncError("The connection is disabled.", 409)
    if conn.provider != "rest":
        raise SyncError("A file connection is not fetched; upload a file with its mapping instead.", 409)
    live = next((r for r in db.query(StudioRun).filter(StudioRun.kind == "sync", StudioRun.entity_id == entity.id,
                                                        StudioRun.status.in_(("queued", "running"))).all()
                 if (r.options or {}).get("stream_id") == str(stream.id)), None)
    if live is not None:
        return live
    tz = ZoneInfo((stream.schedule or {}).get("timezone") or DEFAULT_TZ)
    today = _now().astimezone(tz).date()
    period = _period(stream.import_options or {}, today)
    options = {**(stream.import_options or {}), "stream_id": str(stream.id), "sync_mode": stream.sync_mode,
               "validate": bool((stream.import_options or {}).get("validate"))}
    effective_from = None
    period_month = None
    if stream.object_type == "employee_master":
        options["effective_from"] = period.isoformat()
        effective_from = period
    elif stream.object_type in ("attendance", "salary_register"):
        options["period_month"] = period.isoformat()
        period_month = period
    if stream.object_type == "salary_register":
        options.setdefault("run_type", "regular")
    versions: dict[str, Any] = {}
    if stream.mapping_key:
        version = profiles.in_force(db, entity.id, stream.mapping_key, today, stream.mapping_version)
        if version is None:
            raise SyncError(f"Mapping {stream.mapping_key} has no published version in force. Publish one first.", 409)
        versions = {"mapping": f"{version.key} v{version.version}", "mapping_id": str(version.id)}
    run = runs.create(
        db, org_id=entity.org_id, entity_id=entity.id, kind="sync", object_type=stream.object_type,
        actor_type=actor_type, actor_user_id=actor.id, actor_label=actor_label, trigger=trigger,
        environment=conn.environment, source_system=conn.name, source_object=stream.path or stream.name,
        batch_id=f"{stream.name}-{_now():%Y%m%d%H%M%S}", period_month=period_month, effective_from=effective_from,
        options=options, versions=versions, connection_id=conn.id,
    )
    run.max_attempts = stream.max_attempts
    stream.last_run_id = run.id
    return run


def _missing_in_source(db: Session, run: StudioRun, fetched_ids: set[str]) -> dict[str, Any] | None:
    options = run.options or {}
    if options.get("deletions") != "report" or options.get("sync_mode") != "full":
        return None
    if run.object_type == "employee_master":
        from app.services.workforce import master_as_of

        stored = set(master_as_of(db, run.entity_id, date.fromisoformat(options["effective_from"])))
    elif run.object_type == "attendance":
        from app.models import AttendanceRegister, AttendanceRow

        reg = (db.query(AttendanceRegister).filter(AttendanceRegister.entity_id == run.entity_id,
                                                    AttendanceRegister.period_month == date.fromisoformat(options["period_month"])).first())
        stored = {r.employee_id for r in db.query(AttendanceRow).filter(AttendanceRow.register_id == reg.id)} if reg else set()
    else:
        return None
    gone = sorted(stored - fetched_ids)
    return {"count": len(gone), "employee_ids": gone[:100]}


def process(db: Session, run: StudioRun) -> StudioRun:
    """Fetch, map, import and checkpoint one sync run. Commits."""
    stream = db.get(StudioStream, uuid.UUID(run.options["stream_id"]))
    conn = db.get(StudioConnection, run.connection_id) if run.connection_id else None
    if stream is None or conn is None:
        runs.finish(db, run, "failed", error_category="configuration",
                    error_message="The stream or connection this sync belonged to no longer exists.")
        db.commit()
        return run
    runs.heartbeat(db, run, "fetching")
    watermark = (stream.checkpoint or {}).get("watermark") if stream.sync_mode == "incremental" else None
    try:
        records, meta = connections.fetch(db, conn, stream, watermark=watermark)
    except egress.EgressRefused as exc:
        connections.health(conn, False, exc.message)
        runs.finish(db, run, "failed", error_category="configuration", error_message=exc.message)
        db.commit()
        return run
    except vault.SecretStoreUnavailable as exc:
        connections.health(conn, False, str(exc))
        runs.finish(db, run, "failed", error_category="configuration", error_message=str(exc))
        db.commit()
        return run
    except egress.EgressFailed as exc:
        connections.health(conn, False, exc.message)
        if exc.transient:
            db.commit()
            raise TransientSyncError(exc.message) from exc
        runs.finish(db, run, "failed", error_category="configuration", error_message=exc.message)
        db.commit()
        return run
    connections.health(conn, True)
    run.result_ref = {**(run.result_ref or {}), "pages": meta["pages"], "fetched": len(records),
                      "watermark_sent": watermark}
    if not records:
        runs.finish(db, run, "completed", counts={"received": 0, "accepted": 0},
                    result_ref={"note": "The source had no records" + (" changed since the last sync." if watermark else ".")})
        stream.checkpoint = {**(stream.checkpoint or {}), "last_run_id": str(run.id), "at": _now().isoformat()}
        db.commit()
        return run

    def advance(db: Session, run: StudioRun, counts: dict[str, int]) -> None:
        # Same transaction as the stored records: the checkpoint can never
        # get ahead of the data it describes.
        if counts.get("accepted", 0) == 0:
            return
        db.flush()
        new = dict(stream.checkpoint or {})
        if stream.sync_mode == "incremental" and stream.watermark_field:
            from app.services.studio.mapping import dig

            marks = [str(v) for r in records if isinstance(r, dict)
                     and (v := dig(r, stream.watermark_field)) not in (None, "")]
            if marks:
                new["watermark"] = max(marks + ([watermark] if watermark else []))
        new["last_run_id"] = str(run.id)
        new["at"] = _now().isoformat()
        stream.checkpoint = new
        fetched_ids: set[str] = set()
        missing = None
        if (run.options or {}).get("deletions") == "report":
            from app.models import StudioMapping, StudioRunRejection
            from app.services.studio import mapping as engine

            rejected_rows = {r.row_number for r in db.query(StudioRunRejection.row_number)
                             .filter(StudioRunRejection.run_id == run.id)}
            spec = None
            if (run.versions or {}).get("mapping_id"):
                spec = db.get(StudioMapping, uuid.UUID(run.versions["mapping_id"])).spec
            for i, r in enumerate(records, start=1):
                if i in rejected_rows or not isinstance(r, dict):
                    continue
                if spec is not None:
                    eid = (engine.apply_one(spec, r, i).output or {}).get("employee_id")
                else:
                    eid = next((r.get(k) for k in ("employee_id", "emp_id", "employee_code")
                                if r.get(k) not in (None, "")), None)
                if eid is not None:
                    fetched_ids.add(str(eid).strip())
            missing = _missing_in_source(db, run, fetched_ids)
        if missing is not None:
            run.result_ref = {**(run.result_ref or {}), "missing_in_source": missing}

    return imports.ingest_records(db, run, records, on_committed=advance)


def schedule_due(db: Session, limit: int = 20) -> int:
    """Start the syncs whose time has come. Returns how many were queued."""
    now = _now()
    locking = "FOR UPDATE SKIP LOCKED" if db.bind.dialect.name == "postgresql" else ""
    rows = db.execute(text(
        "SELECT id FROM studio_streams WHERE enabled = :t AND next_run_at IS NOT NULL AND next_run_at <= :now "
        f"ORDER BY next_run_at LIMIT :limit {locking}"  # nosec B608
    ), {"t": True, "now": now, "limit": limit}).all()
    started = 0
    for (sid,) in rows:
        stream = db.get(StudioStream, sid if isinstance(sid, uuid.UUID) else uuid.UUID(str(sid)))
        if stream is None:
            continue
        stream.next_run_at = next_run(stream.schedule, now)
        entity = db.get(Entity, stream.entity_id)
        conn = db.get(StudioConnection, stream.connection_id)
        if entity is None or conn is None or conn.status != "active":
            continue
        creator = db.get(User, conn.created_by) if conn.created_by else None
        if creator is None:
            continue
        try:
            start(db, entity, stream, actor=creator, actor_label=f"Schedule of “{conn.name}”",
                  actor_type="user", trigger="schedule")
            started += 1
        except SyncError as exc:
            connections.health(conn, False, str(exc))
    db.commit()
    return started


def month_end(d: date) -> date:
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])
