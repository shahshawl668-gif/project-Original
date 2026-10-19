"""
Lookups for the report screens, filing readiness and the financial exposure settings.

Kept deliberately small: the month and dimension lookups the report screens use, the
statutory filing calendar, and the financial-exposure settings that validation reads.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import (
    get_current_entity,
    get_current_user,
    require_entity_write,
)
from app.envelope import ok
from app.models import Entity, User
from app.schemas.exposure_config import ExposureConfig
from app.services import analytics, compliance_calendar
from app.services.config_service import ConfigService

router = APIRouter()


def _period(value: str | None, field: str = "period") -> date:
    if not value:
        raise HTTPException(status_code=400, detail=f"'{field}' is required (YYYY-MM-DD)")
    try:
        return date.fromisoformat(value).replace(day=1)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"'{field}' must be an ISO date (YYYY-MM-DD)")


@router.get("/periods")
def periods(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    """Months that hold a register, so a comparison can only name a real one."""
    return ok(analytics.available_periods(db, entity.id))


@router.get("/compliance")
def compliance(
    period: str | None = Query(default=None),
    months: int = Query(default=6, ge=1, le=24),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    """
    Filing readiness against the statutory calendar.

    Readiness, not confirmation: this product does not connect to EPFO, ESIC,
    state PT portals or TRACES, so it reports the due date and what would make a
    filing wrong — never that one happened.
    """
    if period:
        return ok(compliance_calendar.filing_readiness(db, entity.id, _period(period)))
    return ok(compliance_calendar.filing_calendar(db, entity.id, months))


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
