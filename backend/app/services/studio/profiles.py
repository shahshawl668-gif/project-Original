"""
Mapping profiles and their versions.

A profile (``key``) has numbered versions. A draft can be edited, previewed
against sample records, compared with any other version and published; a
published version is **immutable** — changing it means a new draft — so the
runs that used version 3 always used exactly version 3. Publishing needs an
owner or manager, and where the organisation requires it (approval policy
``studio_publish_requires_independent_approver``) someone other than the
author. Retiring a version stops it being chosen; runs keep their reference.

The version a sync uses is the one pinned on the stream, or else the latest
published version whose ``effective_from`` is on or before the run date.
"""
from __future__ import annotations

import re
import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.services.clock import india_today
from app.models import ComponentConfig, Entity, StudioMapping, User
from app.services import approvals, audit
from app.services.payroll_parse import normalize_col
from app.services.studio import mapping as engine

KEY = re.compile(r"^[a-z0-9][a-z0-9_-]{1,99}$")


class ProfileError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def components(db: Session, entity_id: Any) -> list[str]:
    return [normalize_col(c.component_name)
            for c in db.query(ComponentConfig).filter(ComponentConfig.entity_id == entity_id).all()]


def _check(db: Session, entity: Entity, object_type: str, spec: dict[str, Any]) -> dict[str, Any]:
    try:
        return engine.check_spec(spec, object_type, components(db, entity.id))
    except engine.SpecError as exc:
        raise ProfileError(str(exc)) from exc


def versions(db: Session, entity_id: Any, key: str) -> list[StudioMapping]:
    return (db.query(StudioMapping)
            .filter(StudioMapping.entity_id == entity_id, StudioMapping.key == key)
            .order_by(StudioMapping.version.desc()).all())


def create(db: Session, entity: Entity, actor: User, *, key: str, name: str, object_type: str,
           spec: dict[str, Any], change_reason: str | None, effective_from: date | None = None) -> StudioMapping:
    key = (key or "").strip().lower()
    if not KEY.match(key):
        raise ProfileError("The key is lower-case letters, digits, - and _, e.g. hrms-employees.")
    if object_type not in ("employee_master", "ctc", "attendance", "salary_register"):
        raise ProfileError("Object type must be employee_master, ctc, attendance or salary_register.")
    existing = versions(db, entity.id, key)
    if existing and existing[0].object_type != object_type:
        raise ProfileError(f"{key} maps {existing[0].object_type}; use another key for {object_type}.")
    row = StudioMapping(
        org_id=entity.org_id, entity_id=entity.id, key=key, name=(name or key).strip()[:255],
        object_type=object_type, version=(existing[0].version + 1) if existing else 1, status="draft",
        spec=_check(db, entity, object_type, spec), effective_from=effective_from,
        change_reason=change_reason, created_by=actor.id,
    )
    db.add(row)
    db.flush()
    audit.record(db, entity_id=entity.id, user=actor, action="studio.mapping.drafted", object_type="studio_mapping",
                 object_id=str(row.id), summary=f"Drafted mapping {key} v{row.version}"
                 + (f": {change_reason}" if change_reason else ""))
    return row


def update_draft(db: Session, entity: Entity, row: StudioMapping, actor: User, *, spec: dict[str, Any] | None,
                 name: str | None, change_reason: str | None, effective_from: date | None) -> StudioMapping:
    if row.status != "draft":
        raise ProfileError("A published mapping cannot change. Draft a new version from it.", 409)
    if spec is not None:
        row.spec = _check(db, entity, row.object_type, spec)
    if name:
        row.name = name.strip()[:255]
    if change_reason is not None:
        row.change_reason = change_reason
    row.effective_from = effective_from if effective_from is not None else row.effective_from
    return row


def new_version_from(db: Session, entity: Entity, row: StudioMapping, actor: User, reason: str | None) -> StudioMapping:
    return create(db, entity, actor, key=row.key, name=row.name, object_type=row.object_type,
                  spec=row.spec, change_reason=reason or f"From v{row.version}", effective_from=row.effective_from)


def publish(db: Session, entity: Entity, row: StudioMapping, actor: User) -> StudioMapping:
    if row.status != "draft":
        raise ProfileError("Only a draft can be published.", 409)
    try:
        approvals.require_independent(db, entity.org_id, "studio_publish_requires_independent_approver",
                                      preparer_id=row.created_by, approver_id=actor.id, what="a data mapping")
    except approvals.ApprovalRefused as exc:
        raise ProfileError(str(exc), 409) from exc
    _check(db, entity, row.object_type, row.spec)
    row.status = "published"
    row.published_by = actor.id
    row.published_at = datetime.now(UTC)
    audit.record(db, entity_id=entity.id, user=actor, action="studio.mapping.published", object_type="studio_mapping",
                 object_id=str(row.id), summary=f"Published mapping {row.key} v{row.version}",
                 detail={"independent": row.created_by != actor.id})
    return row


def retire(db: Session, entity: Entity, row: StudioMapping, actor: User, reason: str) -> StudioMapping:
    if row.status != "published":
        raise ProfileError("Only a published version can be retired.", 409)
    if not (reason or "").strip():
        raise ProfileError("Say why it is being retired.")
    row.status = "retired"
    row.retired_at = datetime.now(UTC)
    audit.record(db, entity_id=entity.id, user=actor, action="studio.mapping.retired", object_type="studio_mapping",
                 object_id=str(row.id), summary=f"Retired mapping {row.key} v{row.version}: {reason.strip()}")
    return row


def in_force(db: Session, entity_id: Any, key: str, on: date | None = None, pinned: int | None = None) -> StudioMapping | None:
    on = on or india_today()
    rows = versions(db, entity_id, key)
    if pinned is not None:
        return next((r for r in rows if r.version == pinned and r.status in ("published", "retired")), None)
    for r in rows:
        if r.status == "published" and (r.effective_from is None or r.effective_from <= on):
            return r
    return None


def get(db: Session, entity: Entity, mapping_id: str) -> StudioMapping:
    try:
        row = db.get(StudioMapping, uuid.UUID(mapping_id))
    except ValueError:
        row = None
    if row is None or row.entity_id != entity.id:
        raise ProfileError("Mapping not found.", 404)
    return row


def describe(row: StudioMapping) -> dict[str, Any]:
    return {
        "id": str(row.id), "key": row.key, "name": row.name, "object_type": row.object_type,
        "version": row.version, "status": row.status, "spec": row.spec,
        "effective_from": row.effective_from.isoformat() if row.effective_from else None,
        "change_reason": row.change_reason,
        "created_by": str(row.created_by) if row.created_by else None,
        "published_by": str(row.published_by) if row.published_by else None,
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "retired_at": row.retired_at.isoformat() if row.retired_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "label": f"{row.key} v{row.version}",
    }


def preview(spec: dict[str, Any], records: list[Any], limit: int = 200) -> dict[str, Any]:
    """Apply a specification to sample records: every output and every error, by row."""
    results = engine.apply(spec, records[:limit])
    ok = [r for r in results if r.output is not None]
    return {
        "rows": len(results),
        "mapped": len(ok),
        "rejected": len(results) - len(ok),
        "truncated": len(records) > limit,
        "results": [{"row": r.row, "output": r.output, "errors": r.errors, "source_record_id": r.source_record_id,
                     "defaults_used": r.defaults_used} for r in results],
    }
