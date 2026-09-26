"""
Minimum wage rates and compliance.

Rates are maintained by the tenant (see the model's note on why no shipped
dataset stays correct), so this is mostly a maintenance surface — plus a
coverage report that shows the gaps before they turn into findings, and a check
that runs a stored register against the table.
"""
from __future__ import annotations

import calendar
import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_entity, get_current_user, require_entity_write
from app.envelope import ok
from app.models import Entity, MinimumWageApplicability, MinimumWageRate, SalaryRegister, SalaryRegisterRow, User
from app.schemas.minimum_wage import (
    MinimumWageDecisionIn,
    MinimumWageImport,
    MinimumWageRateIn,
    MinimumWageRateOut,
)
from app.services import minimum_wage as mw
from app.services import audit
from app.services.workforce import master_as_of

router = APIRouter()


def _decision_payload(row: MinimumWageApplicability | None) -> dict:
    if row is None:
        return {"status": "not_set", "applicable": None, "effective_from": None}
    return {
        "status": "applicable" if row.applicable else "not_applicable",
        "applicable": row.applicable,
        "effective_from": row.effective_from.isoformat(),
        "reason": row.reason,
        "source_reference": row.source_reference,
    }


@router.get("/applicability")
def get_applicability(
    as_of: date | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    decision = mw.applicability_as_of(db, entity.id, as_of or date.today())
    history = (
        db.query(MinimumWageApplicability)
        .filter(MinimumWageApplicability.entity_id == entity.id)
        .order_by(MinimumWageApplicability.effective_from.desc())
        .all()
    )
    return ok({"current": _decision_payload(decision), "history": [_decision_payload(row) for row in history]})


@router.post("/applicability")
def set_applicability(
    body: MinimumWageDecisionIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_entity_write),
):
    exists = (
        db.query(MinimumWageApplicability)
        .filter(
            MinimumWageApplicability.entity_id == entity.id,
            MinimumWageApplicability.effective_from == body.effective_from,
        )
        .first()
    )
    if exists:
        raise HTTPException(status_code=409, detail="A decision already exists for this effective date.")
    decision = MinimumWageApplicability(
        entity_id=entity.id, user_id=user.id, **body.model_dump()
    )
    db.add(decision)
    audit.record(
        db, entity_id=entity.id, user=user, action="minimum_wage.applicability_set",
        object_type="minimum_wage_applicability", object_id=body.effective_from.isoformat(),
        summary=f"Minimum-wage check {'applies' if body.applicable else 'does not apply'} from {body.effective_from}",
        detail={"reason": body.reason, "source_reference": body.source_reference},
    )
    db.commit()
    return ok(_decision_payload(decision))


@router.get("/rates")
def list_rates(
    state: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    query = db.query(MinimumWageRate).filter(MinimumWageRate.entity_id == entity.id)
    if state:
        query = query.filter(MinimumWageRate.state == state)
    rows = query.order_by(
        MinimumWageRate.state,
        MinimumWageRate.skill_category,
        MinimumWageRate.effective_from.desc(),
    ).all()
    return ok([MinimumWageRateOut.model_validate(r).model_dump(mode="json") for r in rows])


@router.post("/rates")
def create_rate(
    body: MinimumWageRateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_entity_write),
):
    rate = MinimumWageRate(entity_id=entity.id, user_id=user.id, **body.model_dump())
    db.add(rate)
    db.commit()
    db.refresh(rate)
    return ok(MinimumWageRateOut.model_validate(rate).model_dump(mode="json"))


@router.post("/rates/import")
def import_rates(
    body: MinimumWageImport,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_entity_write),
):
    result = mw.import_rates(
        db,
        entity_id=entity.id,
        user_id=user.id,
        rows=[r.model_dump() for r in body.rates],
        replace=body.replace,
    )
    db.commit()
    return ok(result)


@router.delete("/rates/{rate_id}")
def delete_rate(
    rate_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_entity_write),
):
    rate = db.get(MinimumWageRate, rate_id)
    if rate is None or rate.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Rate not found")
    db.delete(rate)
    db.commit()
    return ok({"deleted": str(rate_id)})


@router.get("/coverage")
def coverage(
    as_of: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    """
    Which (state, skill) pairs in the workforce have no rate on file.

    Worth looking at before a run rather than after: every gap here becomes an
    employee the tool cannot vouch for.
    """
    cutoff = date.fromisoformat(as_of) if as_of else date.today()
    master = master_as_of(db, entity.id, cutoff)
    required = [
        (r.work_state, r.skill_category)
        for r in master.values()
        if r.work_state and r.skill_category
    ]
    report = mw.coverage_report(db, entity.id, required, as_of=cutoff)
    report["applicability"] = _decision_payload(mw.applicability_as_of(db, entity.id, cutoff))
    report["employees_without_classification"] = sum(
        1 for r in master.values() if not r.work_state or not r.skill_category
    )
    return ok(report)


@router.post("/check")
def check_period(
    period: str = Query(...),
    basis: str = Query(default="wages_excl_hra"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    """Run the stored register for ``period`` against the rate table."""
    if basis not in mw.COMPARISON_BASES:
        raise HTTPException(
            status_code=400,
            detail=f"basis must be one of: {', '.join(sorted(mw.COMPARISON_BASES))}",
        )
    try:
        period_month = date.fromisoformat(period).replace(day=1)
    except ValueError:
        raise HTTPException(status_code=400, detail="'period' must be an ISO date (YYYY-MM-DD)")

    month_end = date(
        period_month.year, period_month.month,
        calendar.monthrange(period_month.year, period_month.month)[1],
    )
    decision = mw.applicability_as_of(db, entity.id, month_end)
    if decision is None:
        raise HTTPException(
            status_code=409,
            detail="Select Yes or No for minimum-wage applicability before checking this entity and period.",
        )
    if not decision.applicable:
        return ok({
            "period": period_month.isoformat(), "status": "not_applicable",
            "reason": decision.reason, "effective_from": decision.effective_from.isoformat(),
            "employees_checked": 0, "below_minimum": 0, "could_not_verify": 0,
            "total_shortfall": 0, "findings": [],
        })

    register = (
        db.query(SalaryRegister)
        .filter(
            SalaryRegister.entity_id == entity.id,
            SalaryRegister.period_month == period_month,
        )
        .first()
    )
    if register is None:
        raise HTTPException(status_code=404, detail=f"No salary register for {period_month}")

    # The master as it stood at month end, so a later transfer or reclassification
    # does not rewrite what was owed then.
    master = master_as_of(db, entity.id, month_end)
    calendar_days = Decimal(calendar.monthrange(period_month.year, period_month.month)[1])

    rows = db.query(SalaryRegisterRow).filter(SalaryRegisterRow.register_id == register.id).all()

    findings = []
    for row in rows:
        record = master.get(row.employee_id)
        finding = mw.check_employee(
            db,
            entity.id,
            employee_id=row.employee_id,
            employee_name=row.employee_name,
            components=row.components or {},
            state=(record.work_state if record else None) or entity.primary_state,
            skill_category=record.skill_category if record else None,
            paid_days=row.paid_days,
            calendar_days=calendar_days,
            as_of=month_end,
            basis=basis,
            zone=None,
            scheduled_employment=None,
        )
        if finding:
            findings.append(finding)

    shortfalls = [f for f in findings if f["rule_id"] == "MW-001"]
    unverifiable = [f for f in findings if f["rule_id"] == "MW-003"]
    return ok(
        {
            "period": period_month.isoformat(),
            "basis": basis,
            "employees_checked": len(rows),
            "below_minimum": len(shortfalls),
            "could_not_verify": len(unverifiable),
            "total_shortfall": round(sum(f["financial_impact"] for f in shortfalls), 2),
            "findings": findings,
        }
    )
