"""
Report downloads.

One endpoint shape for nine reports, because a finance team that has learned how
to get one should not have to learn again for the next. Every workbook carries
its own provenance sheet — see services/reporting.py.
"""
from __future__ import annotations

import io

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_entity, get_current_user, get_identity
from app.envelope import ok
from app.models import Entity, User
from app.services import audit, reporting, tenancy
from app.services.budgeting import parse_period

router = APIRouter()

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("")
def catalogue(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    """
    Which reports exist and what each one covers.

    A report the caller cannot download is not listed: offering a card that
    always 403s teaches people to ignore errors.
    """
    allowed = getattr(entity, "pay_equity_enabled", False) and tenancy.role_at_least(
        db, user, "manager"
    )
    reports = [
        report for report in reporting.catalogue()
        if report["key"] not in reporting.RESTRICTED_REPORTS or allowed
    ]
    return ok({"reports": reports})


@router.get("/{kind}.xlsx")
def download(
    kind: str,
    group_by: str = Query(default="department"),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    business_unit: list[str] | None = Query(default=None),
    department: list[str] | None = Query(default=None),
    cost_center: list[str] | None = Query(default=None),
    work_location: list[str] | None = Query(default=None),
    work_state: list[str] | None = Query(default=None),
    grade: list[str] | None = Query(default=None),
    designation: list[str] | None = Query(default=None),
    employment_type: list[str] | None = Query(default=None),
    skill_category: list[str] | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
    identity = Depends(get_identity),
):
    if kind in reporting.RESTRICTED_REPORTS:
        # The same two conditions the screen enforces: the entity has authorised
        # the analysis, and the caller is an owner or manager. An export must not
        # be the way around a gate.
        if not getattr(entity, "pay_equity_enabled", False):
            raise HTTPException(
                status_code=403,
                detail="Pay equity analysis is not enabled for this entity.",
            )
        if not tenancy.role_at_least(db, user, "manager"):
            raise HTTPException(
                status_code=403,
                detail="Pay equity analysis is restricted to owners and managers.",
            )

    filters = {
        "business_unit": business_unit, "department": department, "cost_center": cost_center,
        "work_location": work_location, "work_state": work_state, "grade": grade,
        "designation": designation, "employment_type": employment_type,
        "skill_category": skill_category,
    }
    try:
        payload, filename = reporting.build(
            db, entity,
            kind=kind, user=user, identity=identity, group_by=group_by,
            date_from=parse_period(date_from) if date_from else None,
            date_to=parse_period(date_to) if date_to else None,
            filters={k: v for k, v in filters.items() if v},
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    # A download is an export of payroll data leaving the product, so it is
    # logged like any other change to the record.
    audit.record(
        db, entity_id=entity.id, user=user, action="report.downloaded",
        object_type="report", object_id=kind,
        summary=f"Downloaded the {kind} report",
        detail={"masked": identity.masked, "filters": {k: v for k, v in filters.items() if v}},
    )
    db.commit()

    return StreamingResponse(
        io.BytesIO(payload),
        media_type=XLSX,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
