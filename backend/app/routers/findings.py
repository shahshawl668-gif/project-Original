"""
The findings worklist.

Validation produces findings; this is where they are worked. The list is keyed
by fingerprint rather than by run, so an exception explained in April is still
explained in September, and the thing HR sees is "what is outstanding" rather
than "what did this upload say".
"""
from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_entity, get_current_user, require_entity_write
from app.envelope import ok
from app.models import Entity, FindingState, FindingStateEvent, User, ValidationRun
from app.schemas.findings import (
    FindingDecision,
    FindingEventOut,
    FindingStateOut,
    ValidationRunOut,
)
from app.services import finding_store

router = APIRouter()


@router.get("")
def list_findings(
    state: str | None = Query(default=None),
    rule_id: str | None = Query(default=None),
    employee_id: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    min_occurrences: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    """
    Outstanding findings, worst first.

    Default ordering puts the recurring and expensive ones at the top: a
    CRITICAL in its ninth month is a process failure, not a typo, and it should
    not be buried under this month's fresh noise.
    """
    query = db.query(FindingState).filter(FindingState.entity_id == entity.id)
    if state:
        query = query.filter(FindingState.state == state)
    if rule_id:
        query = query.filter(FindingState.rule_id == rule_id)
    if employee_id:
        query = query.filter(FindingState.employee_id == employee_id)
    if severity:
        query = query.filter(FindingState.severity == severity)
    if min_occurrences:
        query = query.filter(FindingState.occurrence_count >= min_occurrences)

    rows = query.all()
    severity_rank = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
    rows.sort(
        key=lambda r: (
            severity_rank.get(r.severity, 3),
            -r.occurrence_count,
            -float(r.last_financial_impact or 0),
        )
    )
    return ok([FindingStateOut.model_validate(r).model_dump(mode="json") for r in rows])


@router.get("/summary")
def findings_summary(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    """
    Counts and exposure by lifecycle state.

    ``waived_exposure`` is reported separately rather than netted off: an
    accepted exception is still money at risk, and a dashboard that hides it is
    telling the reader something untrue.
    """
    rows = db.query(FindingState).filter(FindingState.entity_id == entity.id).all()
    today = date.today()

    buckets: dict[str, dict] = {}
    for row in rows:
        bucket = buckets.setdefault(row.state, {"count": 0, "exposure": 0.0})
        bucket["count"] += 1
        bucket["exposure"] += float(row.last_financial_impact or 0)

    open_rows = [r for r in rows if r.state in ("open", "acknowledged")]
    waived_rows = [r for r in rows if r.state == "waived"]
    expiring = [
        r for r in waived_rows
        if r.waived_until is not None and r.waived_until >= today
        and (r.waived_until - today).days <= 60
    ]

    return ok(
        {
            "by_state": buckets,
            "open_count": len(open_rows),
            "open_exposure": round(sum(float(r.last_financial_impact or 0) for r in open_rows), 2),
            "waived_count": len(waived_rows),
            "waived_exposure": round(sum(float(r.last_financial_impact or 0) for r in waived_rows), 2),
            "recurring_count": sum(1 for r in open_rows if r.occurrence_count >= 3),
            "waivers_expiring_soon": [
                {
                    "fingerprint": r.fingerprint,
                    "employee_id": r.employee_id,
                    "rule_id": r.rule_id,
                    "waived_until": r.waived_until.isoformat(),
                }
                for r in expiring
            ],
        }
    )


@router.get("/runs")
def list_runs(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    rows = (
        db.query(ValidationRun)
        .filter(ValidationRun.entity_id == entity.id)
        .order_by(ValidationRun.period_month.desc())
        .all()
    )
    return ok([ValidationRunOut.model_validate(r).model_dump(mode="json") for r in rows])


@router.get("/{fingerprint}")
def get_finding(
    fingerprint: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    state = _load(db, entity, fingerprint)
    events = (
        db.query(FindingStateEvent)
        .filter(FindingStateEvent.state_id == state.id)
        .order_by(FindingStateEvent.created_at.desc())
        .all()
    )
    return ok(
        {
            "finding": FindingStateOut.model_validate(state).model_dump(mode="json"),
            "history": [FindingEventOut.model_validate(e).model_dump(mode="json") for e in events],
        }
    )


@router.post("/{fingerprint}/decision")
def decide(
    fingerprint: str,
    body: FindingDecision,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_entity_write),
):
    """
    Record a decision: acknowledge it, waive it, or put it back on the list.

    A waiver must state its grounds. The point of the worklist is that someone
    took a view; "waived" with no reason attached is a gap in the audit trail
    that will be noticed at exactly the wrong moment.
    """
    state = _load(db, entity, fingerprint)

    if body.state == "waived" and not (body.reason or "").strip():
        raise HTTPException(status_code=400, detail="A waiver must state a reason")

    finding_store.set_state(
        db,
        state=state,
        to_state=body.state,
        actor=user,
        reason=body.reason,
        waived_until=body.waived_until,
        note=body.note,
    )
    db.commit()
    db.refresh(state)
    return ok(FindingStateOut.model_validate(state).model_dump(mode="json"))


def _load(db: Session, entity: Entity, fingerprint: str) -> FindingState:
    state = (
        db.query(FindingState)
        .filter(FindingState.entity_id == entity.id, FindingState.fingerprint == fingerprint)
        .first()
    )
    if state is None:
        raise HTTPException(status_code=404, detail="Finding not found")
    return state
