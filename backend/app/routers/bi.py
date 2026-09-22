"""
Business intelligence endpoints.

These are the questions asked *about* payroll rather than of it: why cost moved,
what is accumulating, and where it sits. Validation feeds them — exposure is
computed from the findings that validation left open — so the two halves of the
product are one dataset, not two.
"""
from __future__ import annotations

from datetime import date, datetime, UTC

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import (
    get_current_entity,
    get_current_user,
    get_identity,
    require_entity_write,
    require_entity_admin,
    require_pay_equity,
)
from app.envelope import ok
from app.models import Entity, User
from app.schemas.exposure_config import ExposureConfig
from app.services import analytics, audit, compliance_calendar, pay_equity, workforce_analytics
from app.services import tenancy
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


DIMENSION_FILTERS = (
    "business_unit", "department", "cost_center", "work_location", "work_state",
    "grade", "designation", "employment_type", "skill_category",
)


def _filters(**kwargs) -> dict[str, list[str]]:
    return {k: v for k, v in kwargs.items() if v}


@router.get("/cost-analysis")
def cost_analysis(
    group_by: str = Query(default="department"),
    granularity: str = Query(default="month", pattern="^(month|quarter|year)$"),
    measure: str = Query(default="ctc"),
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

    Every response carries the whole cost taxonomy — earnings, employer
    contributions, employee deductions and the CTC roll-up — so changing which
    figure is on screen is a client-side choice rather than another round trip.
    ``measure`` only selects what the series and the ranking are drawn on.

    Filters combine across dimensions and accept several values each, so
    "engineering and product, in Bangalore, grades M3 and above" is one request.
    """
    try:
        return ok(
            analytics.cost_analysis(
                db, entity.id,
                group_by=group_by,
                granularity=granularity,
                measure=measure,
                date_from=_period(date_from, "date_from") if date_from else None,
                date_to=_period(date_to, "date_to") if date_to else None,
                filters=_filters(
                    business_unit=business_unit, department=department,
                    cost_center=cost_center, work_location=work_location,
                    work_state=work_state, grade=grade, designation=designation,
                    employment_type=employment_type, skill_category=skill_category,
                ),
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/cost-compare")
def cost_compare(
    period_a: str = Query(...),
    period_b: str = Query(...),
    group_by: str = Query(default="department"),
    measure: str = Query(default="ctc"),
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
    Two wage months side by side, across the taxonomy and by one dimension.

    The pair is free, which is what makes one endpoint answer both questions
    that get asked: two months in the same year, and the same month a year
    apart.
    """
    try:
        return ok(
            analytics.cost_compare(
                db, entity.id,
                period_a=_period(period_a, "period_a"),
                period_b=_period(period_b, "period_b"),
                group_by=group_by,
                measure=measure,
                filters=_filters(
                    business_unit=business_unit, department=department,
                    cost_center=cost_center, work_location=work_location,
                    work_state=work_state, grade=grade, designation=designation,
                    employment_type=employment_type, skill_category=skill_category,
                ),
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/headcount-movement")
def headcount_movement(
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
    """
    Opening, joiners, exits and closing headcount for each stored month.

    Movement is measured by presence on the register, because that is a verified
    statement — the money moved. Joining and exit dates from the employee master
    are reported alongside as corroboration, never instead of it.
    """
    filters = _filters(
        business_unit=business_unit, department=department, cost_center=cost_center,
        work_location=work_location, work_state=work_state, grade=grade,
        designation=designation, employment_type=employment_type,
        skill_category=skill_category,
    )
    result = workforce_analytics.headcount_movement(
        db, entity.id,
        date_from=_period(date_from, "date_from") if date_from else None,
        date_to=_period(date_to, "date_to") if date_to else None,
        filters=filters,
    )
    for point in result["periods"]:
        point["joiner_ids"] = [
            identity.employee(eid)["employee_id"] for eid in point["joiner_ids"]
        ]
        point["exit_ids"] = [
            identity.employee(eid)["employee_id"] for eid in point["exit_ids"]
        ]
    result["identity"] = identity.as_dict()
    return ok(result)


@router.get("/compensation")
def compensation(
    period: str | None = Query(default=None),
    group_by: str = Query(default="grade"),
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
    """
    How pay is distributed, for one month, on annualised CTC.

    The median and the quartiles rather than the average alone: one large
    package moves an average and nothing else does, which is why a C&B team
    does not reason with one.
    """
    filters = _filters(
        business_unit=business_unit, department=department, cost_center=cost_center,
        work_location=work_location, work_state=work_state, grade=grade,
        designation=designation, employment_type=employment_type,
        skill_category=skill_category,
    )
    try:
        result = workforce_analytics.compensation_analysis(
            db, entity.id,
            period=_period(period, "period") if period else None,
            group_by=group_by,
            filters=filters,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    result["employees"] = [identity.apply(row) for row in result["employees"]]
    result["identity"] = identity.as_dict()
    return ok(result)


@router.get("/pay-equity/settings")
def pay_equity_settings(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    """Whether the analysis is switched on for this entity, and who switched it on."""
    return ok({
        "enabled": bool(getattr(entity, "pay_equity_enabled", False)),
        "enabled_by": getattr(entity, "pay_equity_enabled_by", None),
        "enabled_at": (
            entity.pay_equity_enabled_at.isoformat()
            if getattr(entity, "pay_equity_enabled_at", None) else None
        ),
        "can_change": tenancy.role_at_least(db, user, "manager"),
        "minimum_group_size": pay_equity.MIN_GROUP_SIZE,
    })


class PayEquityToggle(BaseModel):
    enabled: bool
    # Free text, stored on the audit entry rather than the entity: the record of
    # *why* an employer authorised this belongs in the trail, not in a column
    # someone can quietly edit later.
    authorisation_note: str | None = None


@router.put("/pay-equity/settings")
def set_pay_equity_settings(
    body: PayEquityToggle,
    db: Session = Depends(get_db),
    user: User = Depends(require_entity_admin),
    entity: Entity = Depends(get_current_entity),
):
    """
    Switch the gender pay gap analysis on or off for this entity.

    Owner or manager only, and recorded either way. Turning it on is an
    authorisation, and an authorisation nobody can point to afterwards is not
    one.
    """
    entity.pay_equity_enabled = bool(body.enabled)
    if body.enabled:
        entity.pay_equity_enabled_by = user.email
        entity.pay_equity_enabled_at = datetime.now(UTC)
    audit.record(
        db, entity_id=entity.id, user=user,
        action="pay_equity.enabled" if body.enabled else "pay_equity.disabled",
        object_type="entity", object_id=str(entity.id),
        summary=(
            "Authorised gender pay gap analysis for this entity"
            if body.enabled else
            "Withdrew authorisation for gender pay gap analysis"
        ),
        detail={"note": (body.authorisation_note or "").strip()[:500]},
    )
    db.commit()
    db.refresh(entity)
    return ok({
        "enabled": entity.pay_equity_enabled,
        "enabled_by": entity.pay_equity_enabled_by,
        "enabled_at": entity.pay_equity_enabled_at.isoformat()
                      if entity.pay_equity_enabled_at else None,
    })


@router.get("/pay-equity")
def pay_equity_analysis(
    period: str | None = Query(default=None),
    group_by: str = Query(default="grade"),
    min_group_size: int = Query(default=pay_equity.MIN_GROUP_SIZE, ge=1, le=500),
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
    entity: Entity = Depends(require_pay_equity),
):
    """
    The gender pay gap, unadjusted and like-for-like, for one wage month.

    Aggregate only — no individual appears at any permission level. Groups below
    the minimum size are withheld and reported as withheld. Every request is
    written to the audit trail, because who looked at this is itself a
    governance question.
    """
    filters = _filters(
        business_unit=business_unit, department=department, cost_center=cost_center,
        work_location=work_location, work_state=work_state, grade=grade,
        designation=designation, employment_type=employment_type,
        skill_category=skill_category,
    )
    try:
        result = pay_equity.pay_equity(
            db, entity.id,
            period=_period(period, "period") if period else None,
            group_by=group_by,
            min_group_size=min_group_size,
            filters=filters,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    audit.record(
        db, entity_id=entity.id, user=user, action="pay_equity.viewed",
        object_type="analysis", object_id=result.get("period"),
        summary=f"Viewed the gender pay gap analysis for {result.get('period_label') or 'no period'}",
        detail={"group_by": group_by, "filters": filters},
    )
    db.commit()
    return ok(result)


@router.get("/measures")
def measures():
    """The cost taxonomy — every measure, its layer and what it means."""
    return ok(analytics.measure_catalogue())


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
