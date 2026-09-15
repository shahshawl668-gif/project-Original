"""
Business intelligence endpoints.

These are the questions asked *about* payroll rather than of it: why cost moved,
what is accumulating, and where it sits. Validation feeds them — exposure is
computed from the findings that validation left open — so the two halves of the
product are one dataset, not two.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_entity, get_current_user, require_entity_write
from app.envelope import ok
from app.models import Entity, User
from app.schemas.exposure_config import ExposureConfig
from app.services import analytics
from app.services.config_service import ConfigService

router = APIRouter()


def _period(value: str | None, field: str = "period") -> date:
    if not value:
        raise HTTPException(status_code=400, detail=f"'{field}' is required (YYYY-MM-DD)")
    try:
        return date.fromisoformat(value).replace(day=1)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"'{field}' must be an ISO date (YYYY-MM-DD)")


@router.get("/cost-bridge")
def cost_bridge(
    period: str = Query(...),
    compare_to: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    """Why payroll cost moved between two months."""
    return ok(
        analytics.cost_bridge(
            db,
            entity.id,
            _period(period),
            _period(compare_to, "compare_to") if compare_to else None,
        )
    )


@router.get("/trend")
def cost_trend(
    months: int = Query(default=12, ge=1, le=60),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    return ok(analytics.cost_trend(db, entity.id, months))


@router.get("/cost-analysis")
def cost_analysis(
    group_by: str = Query(default="department"),
    granularity: str = Query(default="month", pattern="^(month|quarter|year)$"),
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
):
    """
    Payroll cost by any reporting dimension, over month, quarter or year.

    Filters combine across dimensions and accept several values each, so
    "engineering and product, in Bangalore, grades M3 and above" is one request.
    """
    filters = {
        "business_unit": business_unit, "department": department, "cost_center": cost_center,
        "work_location": work_location, "work_state": work_state, "grade": grade,
        "designation": designation, "employment_type": employment_type,
        "skill_category": skill_category,
    }
    try:
        return ok(
            analytics.cost_analysis(
                db, entity.id,
                group_by=group_by,
                granularity=granularity,
                date_from=_period(date_from, "date_from") if date_from else None,
                date_to=_period(date_to, "date_to") if date_to else None,
                filters={k: v for k, v in filters.items() if v},
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/dimensions")
def dimensions(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    """Which dimensions exist and what values they hold, for building filters."""
    return ok(analytics.dimension_values(db, entity.id))


@router.get("/exposure")
def exposure(
    as_of: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    """Accumulated statutory shortfall, aged, with interest and damages."""
    config = ConfigService(db).get_exposure_config(entity.id)
    cutoff = date.fromisoformat(as_of) if as_of else None
    return ok(analytics.statutory_exposure(db, entity.id, config, cutoff))


@router.get("/exposure/config")
def get_exposure_config(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    return ok(ConfigService(db).get_exposure_config(entity.id).model_dump(mode="json"))


@router.put("/exposure/config")
def put_exposure_config(
    body: ExposureConfig,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_entity_write),
):
    service = ConfigService(db)
    service.save_exposure_config(entity.id, body)
    return ok(service.get_exposure_config(entity.id).model_dump(mode="json"))


@router.post("/exposure/config/reset")
def reset_exposure_config(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_entity_write),
):
    return ok(ConfigService(db).reset_exposure_config(entity.id).model_dump(mode="json"))
