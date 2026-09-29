"""PeopleOps Reports: approved dataset preview and company-scoped saved definitions."""
from __future__ import annotations

import io
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
from app.models import Entity, ReportDefinition, ReportDefinitionVersion, User
from app.services import audit, report_builder, report_exports, tenancy

router = APIRouter()


class DefinitionInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    specification: dict[str, Any]
    visibility: str = "private"
    status: str = "draft"


class PreviewInput(BaseModel):
    specification: dict[str, Any]


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
