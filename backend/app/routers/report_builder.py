"""PeopleOps Reports: approved dataset preview and company-scoped saved definitions."""
from __future__ import annotations

import hashlib
import io
from datetime import UTC, datetime
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import get_current_entity, get_current_user
from app.envelope import ok
from app.models import Entity, ReportDefinition, ReportDefinitionVersion, ReportJob, ReportSchedule, User
from app.services import audit, report_builder, report_exports, report_jobs, tenancy

router = APIRouter()


class DefinitionInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    specification: dict[str, Any]
    visibility: str = "private"
    status: str = "draft"


class PreviewInput(BaseModel):
    specification: dict[str, Any]


class QueueInput(BaseModel):
    format: str = "xlsx"


class ScheduleInput(BaseModel):
    frequency: str = Field(pattern="^(monthly|weekly)$")
    day: int = Field(ge=0, le=28)
    hour: int = Field(default=9, ge=0, le=23)
    months: int = Field(default=1, ge=1, le=24)
    format: str = Field(default="xlsx", pattern="^(xlsx|pdf)$")
    enabled: bool = True


def _reader(db: Session, user: User, entity: Entity) -> None:
    if not tenancy.role_at_least(db, user, "analyst", entity):
        raise HTTPException(status_code=403, detail="Report Builder requires analyst access")


def _allowed(db: Session, user: User, entity: Entity, report: ReportDefinition) -> None:
    if report.entity_id != entity.id or report.org_id != entity.org_id or report.status == "retired":
        raise HTTPException(status_code=404, detail="Report not found")
    if report.visibility == "private" and report.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Report not found")


def _get(db: Session, user: User, entity: Entity, report_id: uuid.UUID) -> ReportDefinition:
    report = db.get(ReportDefinition, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    _allowed(db, user, entity, report)
    return report


def _write(db: Session, user: User, entity: Entity, report: ReportDefinition) -> None:
    if report.owner_user_id != user.id and not tenancy.role_at_least(db, user, "manager", entity):
        raise HTTPException(status_code=403, detail="Only the owner or a company manager can edit")
    if report.status == "published" and not tenancy.role_at_least(db, user, "manager", entity):
        raise HTTPException(status_code=403, detail="Publishing changes requires a manager")


def _validate(body: DefinitionInput, db: Session, user: User, entity: Entity) -> dict:
    if body.visibility not in ("private", "shared") or body.status not in ("draft", "published"):
        raise HTTPException(status_code=422, detail="Invalid visibility or status")
    if (body.visibility == "shared" or body.status == "published") and not tenancy.role_at_least(db, user, "manager", entity):
        raise HTTPException(status_code=403, detail="Sharing and publication require a company manager")
    try:
        return report_builder.validate(body.specification)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def _detail(report: ReportDefinition) -> dict:
    return {
        "id": str(report.id), "name": report.name, "description": report.description,
        "owner_user_id": str(report.owner_user_id) if report.owner_user_id else None,
        "visibility": report.visibility, "status": report.status, "version": report.version,
        "specification": report.specification,
        "created_at": report.created_at.isoformat() if report.created_at else None,
        "updated_at": report.updated_at.isoformat() if report.updated_at else None,
    }


@router.get("/datasets")
def datasets(db: Session = Depends(get_db), user: User = Depends(get_current_user),
             entity: Entity = Depends(get_current_entity)):
    _reader(db, user, entity)
    return ok({"datasets": report_builder.dataset_catalogue()})


@router.post("/preview")
def preview(body: PreviewInput, db: Session = Depends(get_db), user: User = Depends(get_current_user),
            entity: Entity = Depends(get_current_entity)):
    _reader(db, user, entity)
    try:
        result = report_builder.preview(db, entity.id, body.specification)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return ok(result)


@router.get("/saved")
def saved(db: Session = Depends(get_db), user: User = Depends(get_current_user),
          entity: Entity = Depends(get_current_entity)):
    _reader(db, user, entity)
    rows = (db.query(ReportDefinition)
            .filter(ReportDefinition.entity_id == entity.id, ReportDefinition.org_id == entity.org_id,
                    ReportDefinition.status != "retired")
            .order_by(ReportDefinition.updated_at.desc()).all())
    return ok({"reports": [_detail(row) for row in rows
                           if row.visibility == "shared" or row.owner_user_id == user.id]})


@router.post("/saved")
def create(body: DefinitionInput, db: Session = Depends(get_db),
           user: User = Depends(get_current_user), entity: Entity = Depends(get_current_entity)):
    _reader(db, user, entity)
    spec = _validate(body, db, user, entity)
    report = ReportDefinition(org_id=entity.org_id, entity_id=entity.id, owner_user_id=user.id,
                              name=body.name.strip(), description=body.description,
                              visibility=body.visibility, status=body.status,
                              specification=spec, version=1)
    db.add(report)
    db.flush()
    db.add(ReportDefinitionVersion(report_id=report.id, entity_id=entity.id, version=1,
                                   name=report.name, specification=spec, changed_by=user.id))
    audit.record(db, entity_id=entity.id, user=user, action="report.created",
                 object_type="report_definition", object_id=str(report.id), summary="Created a report definition")
    db.commit()
    db.refresh(report)
    return ok(_detail(report))



def _job(db: Session, user: User, entity: Entity, job_id: uuid.UUID) -> ReportJob:
    job = db.get(ReportJob, job_id)
    if job is None or job.entity_id != entity.id or job.org_id != entity.org_id:
        raise HTTPException(status_code=404, detail="Report job not found")
    _get(db, user, entity, job.definition_id)
    if job.requester_id != user.id and not tenancy.role_at_least(db, user, "manager", entity):
        raise HTTPException(status_code=404, detail="Report job not found")
    return job


def _job_detail(job: ReportJob) -> dict:
    expired = bool(job.expires_at and report_jobs._aware(job.expires_at) <= datetime.now(UTC))
    return {
        "id": str(job.id), "definition_id": str(job.definition_id),
        "definition_name": job.definition_name, "definition_version": job.definition_version,
        "state": "expired" if expired else job.state,
        "stage": "expired" if expired else job.stage, "attempt": job.attempt,
        "record_count": job.record_count, "control_totals": job.control_totals,
        "source_references": job.source_references,
        "artifact_bytes": job.artifact_bytes, "artifact_sha256": job.artifact_sha256,
        "queued_at": job.queued_at.isoformat() if job.queued_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "expires_at": job.expires_at.isoformat() if job.expires_at else None,
        "error_code": job.error_code, "error_message": job.error_message,
        "cancel_requested": job.cancel_requested,
        "format": job.format or "xlsx", "origin": job.origin or "person",
    }


@router.post("/saved/{report_id}/jobs")
def queue_report(report_id: uuid.UUID, body: QueueInput | None = None, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user), entity: Entity = Depends(get_current_entity)):
    _reader(db, user, entity)
    report = _get(db, user, entity, report_id)
    fmt = (body.format if body else "xlsx")
    if fmt not in report_exports.FORMATS:
        raise HTTPException(status_code=422, detail="Output must be Excel (xlsx) or PDF (pdf)")
    spec = report_builder.validate(report.specification)
    if not spec["date_from"] or not spec["date_to"]:
        raise HTTPException(status_code=422, detail="Choose both period bounds before generation")
    job = report_jobs.enqueue(db, entity=entity, report=report, user=user, fmt=fmt)
    audit.record(db, entity_id=entity.id, user=user, action="report.queued",
                 object_type="report_job", object_id=str(job.id), summary="Queued aggregate report")
    db.commit()
    db.refresh(job)
    return ok(_job_detail(job))


@router.get("/jobs")
def list_jobs(db: Session = Depends(get_db), user: User = Depends(get_current_user),
              entity: Entity = Depends(get_current_entity)):
    _reader(db, user, entity)
    jobs = (db.query(ReportJob).filter(ReportJob.entity_id == entity.id,
                                      ReportJob.org_id == entity.org_id,
                                      ReportJob.requester_id == user.id)
            .order_by(ReportJob.queued_at.desc()).limit(50).all())
    # A report may have become private or retired since the job was generated.
    visible = []
    for job in jobs:
        try:
            _get(db, user, entity, job.definition_id)
            visible.append(_job_detail(job))
        except HTTPException:
            continue
    return ok({"jobs": visible})


@router.get("/jobs/{job_id}")
def get_job(job_id: uuid.UUID, db: Session = Depends(get_db),
            user: User = Depends(get_current_user), entity: Entity = Depends(get_current_entity)):
    _reader(db, user, entity)
    return ok(_job_detail(_job(db, user, entity, job_id)))


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: uuid.UUID, db: Session = Depends(get_db),
               user: User = Depends(get_current_user), entity: Entity = Depends(get_current_entity)):
    _reader(db, user, entity)
    job = _job(db, user, entity, job_id)
    if job.state == "queued":
        job.state, job.stage = "cancelled", "cancelled"
    elif job.state == "running":
        job.cancel_requested = True
        job.stage = "cancelling"
    else:
        raise HTTPException(status_code=409, detail="The job has already finished")
    db.commit()
    return ok(_job_detail(job))


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: uuid.UUID, db: Session = Depends(get_db),
              user: User = Depends(get_current_user), entity: Entity = Depends(get_current_entity)):
    _reader(db, user, entity)
    old = _job(db, user, entity, job_id)
    if old.state != "failed":
        raise HTTPException(status_code=409, detail="Only failed jobs can be retried")
    report = _get(db, user, entity, old.definition_id)
    fresh = report_jobs.enqueue(db, entity=entity, report=report, user=user, fmt=old.format or "xlsx")
    db.commit()
    db.refresh(fresh)
    return ok(_job_detail(fresh))


@router.get("/jobs/{job_id}/download")
def download_job(job_id: uuid.UUID, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user), entity: Entity = Depends(get_current_entity)):
    _reader(db, user, entity)
    job = _job(db, user, entity, job_id)
    if job.state != "succeeded":
        raise HTTPException(status_code=409, detail="Report is not ready")
    if not job.artifact or (job.expires_at and report_jobs._aware(job.expires_at) <= report_jobs._now()):
        raise HTTPException(status_code=410, detail="Report download has expired")
    if hashlib.sha256(job.artifact).hexdigest() != job.artifact_sha256:
        raise HTTPException(status_code=500, detail="Stored report checksum mismatch")
    audit.record(db, entity_id=entity.id, user=user, action="report.downloaded",
                 object_type="report_job", object_id=str(job.id),
                 summary="Downloaded generated report", detail={"version": job.definition_version})
    db.commit()
    media_type, extension = report_exports.FORMATS[job.format or "xlsx"]
    filename = f"peopleops-report-{job.id.hex[:12]}-v{job.definition_version}.{extension}"
    return StreamingResponse(io.BytesIO(job.artifact), media_type=media_type,
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/saved/{report_id}.xlsx")
def export_saved(report_id: uuid.UUID, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user), entity: Entity = Depends(get_current_entity)):
    """Compatibility download for current aggregate reports; generated jobs are preferred."""
    _reader(db, user, entity)
    report = _get(db, user, entity, report_id)
    try:
        payload, info = report_exports.build(db, entity, report, user)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if len(payload) > settings.report_artifact_max_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Report exceeds the configured export size")
    audit.record(db, entity_id=entity.id, user=user, action="report.downloaded",
                 object_type="report_definition", object_id=str(report.id),
                 summary="Downloaded a saved report",
                 detail={"version": report.version, "rows": info["record_count"]})
    db.commit()
    filename = f"peopleops-report-{report.id.hex[:12]}-v{report.version}.xlsx"
    return StreamingResponse(io.BytesIO(payload),
                             media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/saved/{report_id}")
def get_saved(report_id: uuid.UUID, db: Session = Depends(get_db),
              user: User = Depends(get_current_user), entity: Entity = Depends(get_current_entity)):
    _reader(db, user, entity)
    return ok(_detail(_get(db, user, entity, report_id)))


@router.put("/saved/{report_id}")
def update(report_id: uuid.UUID, body: DefinitionInput, db: Session = Depends(get_db),
           user: User = Depends(get_current_user), entity: Entity = Depends(get_current_entity)):
    _reader(db, user, entity)
    report = _get(db, user, entity, report_id)
    _write(db, user, entity, report)
    spec = _validate(body, db, user, entity)
    report.name, report.description = body.name.strip(), body.description
    report.specification, report.visibility, report.status = spec, body.visibility, body.status
    report.version += 1
    db.add(ReportDefinitionVersion(report_id=report.id, entity_id=entity.id, version=report.version,
                                   name=report.name, specification=spec, changed_by=user.id))
    audit.record(db, entity_id=entity.id, user=user, action="report.updated",
                 object_type="report_definition", object_id=str(report.id), summary="Updated a report definition",
                 detail={"version": report.version})
    db.commit()
    db.refresh(report)
    return ok(_detail(report))


@router.post("/saved/{report_id}/clone")
def clone(report_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user),
          entity: Entity = Depends(get_current_entity)):
    _reader(db, user, entity)
    original = _get(db, user, entity, report_id)
    report = ReportDefinition(org_id=entity.org_id, entity_id=entity.id, owner_user_id=user.id,
                              name=f"Copy of {original.name}"[:120], description=original.description,
                              visibility="private", status="draft", specification=original.specification, version=1)
    db.add(report)
    db.flush()
    db.add(ReportDefinitionVersion(report_id=report.id, entity_id=entity.id, version=1,
                                   name=report.name, specification=report.specification, changed_by=user.id))
    db.commit()
    db.refresh(report)
    return ok(_detail(report))


@router.get("/saved/{report_id}/versions")
def versions(report_id: uuid.UUID, db: Session = Depends(get_db),
             user: User = Depends(get_current_user), entity: Entity = Depends(get_current_entity)):
    _reader(db, user, entity)
    _get(db, user, entity, report_id)
    rows = (db.query(ReportDefinitionVersion)
            .filter(ReportDefinitionVersion.entity_id == entity.id,
                    ReportDefinitionVersion.report_id == report_id)
            .order_by(ReportDefinitionVersion.version.desc()).all())
    return ok({"versions": [{"version": row.version, "name": row.name,
                             "specification": row.specification,
                             "changed_by": str(row.changed_by) if row.changed_by else None,
                             "created_at": row.created_at.isoformat() if row.created_at else None}
                            for row in rows]})


@router.post("/saved/{report_id}/preview")
def preview_saved(report_id: uuid.UUID, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user), entity: Entity = Depends(get_current_entity)):
    _reader(db, user, entity)
    report = _get(db, user, entity, report_id)
    return ok(report_builder.preview(db, entity.id, report.specification))


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------
def _schedule_detail(row: ReportSchedule | None) -> dict | None:
    if row is None:
        return None
    return {
        "id": str(row.id), "frequency": row.frequency, "day": row.day, "hour": row.hour,
        "months": row.months, "format": row.format, "enabled": row.enabled,
        "next_run_at": row.next_run_at.isoformat() if row.next_run_at else None,
        "last_run_at": row.last_run_at.isoformat() if row.last_run_at else None,
        "last_job_id": str(row.last_job_id) if row.last_job_id else None,
        "last_error": row.last_error,
        "delivery": "Generated files in this product, for you. The platform sends no email.",
    }


def _own_schedule(db: Session, user: User, report: ReportDefinition) -> ReportSchedule | None:
    return (db.query(ReportSchedule)
            .filter(ReportSchedule.definition_id == report.id, ReportSchedule.owner_user_id == user.id)
            .first())


@router.get("/saved/{report_id}/schedule")
def get_schedule(report_id: uuid.UUID, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user), entity: Entity = Depends(get_current_entity)):
    """Your schedule for this report, if you have one. Each person schedules for themselves."""
    _reader(db, user, entity)
    return ok({"schedule": _schedule_detail(_own_schedule(db, user, _get(db, user, entity, report_id)))})


@router.put("/saved/{report_id}/schedule")
def put_schedule(report_id: uuid.UUID, body: ScheduleInput, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user), entity: Entity = Depends(get_current_entity)):
    _reader(db, user, entity)
    report = _get(db, user, entity, report_id)
    if body.frequency == "monthly" and not 1 <= body.day <= 28:
        raise HTTPException(status_code=422, detail="A monthly schedule runs on day 1 to 28")
    if body.frequency == "weekly" and not 0 <= body.day <= 6:
        raise HTTPException(status_code=422, detail="A weekly schedule runs on a weekday, 0 (Monday) to 6 (Sunday)")
    row = _own_schedule(db, user, report)
    if row is None:
        row = ReportSchedule(org_id=entity.org_id, entity_id=entity.id, definition_id=report.id,
                             owner_user_id=user.id, frequency=body.frequency, day=body.day)
        db.add(row)
    row.frequency, row.day, row.hour = body.frequency, body.day, body.hour
    row.months, row.format, row.enabled = body.months, body.format, body.enabled
    row.last_error = None
    row.next_run_at = report_jobs.next_run(body.frequency, body.day, body.hour, report_jobs._now()) if body.enabled else None
    audit.record(db, entity_id=entity.id, user=user, action="report.scheduled",
                 object_type="report_definition", object_id=str(report.id),
                 summary=("Scheduled" if body.enabled else "Paused the schedule of") + " a saved report",
                 detail={"frequency": body.frequency, "day": body.day, "hour": body.hour,
                         "months": body.months, "format": body.format})
    db.commit()
    db.refresh(row)
    return ok({"schedule": _schedule_detail(row)})


@router.delete("/saved/{report_id}/schedule")
def delete_schedule(report_id: uuid.UUID, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user), entity: Entity = Depends(get_current_entity)):
    _reader(db, user, entity)
    report = _get(db, user, entity, report_id)
    row = _own_schedule(db, user, report)
    if row is None:
        raise HTTPException(status_code=404, detail="This report has no schedule of yours")
    db.delete(row)
    audit.record(db, entity_id=entity.id, user=user, action="report.unscheduled",
                 object_type="report_definition", object_id=str(report.id),
                 summary="Removed the schedule of a saved report")
    db.commit()
    return ok({"schedule": None})
