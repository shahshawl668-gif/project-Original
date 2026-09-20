"""
Building, signing and evidencing a period.

The snapshot assembled here is the product's answer to "what did you know when
you approved this?" — so it records not only the findings but the configuration
that produced them. A finding is only defensible alongside the rule and the rate
that generated it; without that, a reader six months later cannot tell whether
the check was right, only that it ran.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime, UTC
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import (
    Entity,
    FindingState,
    MinimumWageRate,
    PeriodSignOff,
    SignOffEvent,
    User,
    ValidationRun,
)
from app.services import analytics
from app.services.config_service import ConfigService


def _json_default(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    return str(value)


def digest(snapshot: dict) -> str:
    """A stable digest of a snapshot, so tampering or drift is detectable."""
    canonical = json.dumps(snapshot, sort_keys=True, default=_json_default)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_snapshot(db: Session, entity: Entity, period_month: date) -> dict:
    """
    Everything a signer is accepting responsibility for.

    Open and accepted findings are listed separately but both are included: the
    point of the record is that the accepted ones were accepted knowingly, which
    requires them to have been in front of the person who signed.
    """
    period_month = period_month.replace(day=1)
    config_service = ConfigService(db)

    run = (
        db.query(ValidationRun)
        .filter(ValidationRun.entity_id == entity.id, ValidationRun.period_month == period_month)
        .first()
    )

    states = (
        db.query(FindingState)
        .filter(
            FindingState.entity_id == entity.id,
            FindingState.state.in_(("open", "acknowledged", "waived")),
            FindingState.first_seen_period <= period_month,
        )
        .all()
    )

    def _finding(state: FindingState) -> dict:
        return {
            "fingerprint": state.fingerprint,
            "employee_id": state.employee_id,
            "employee_name": state.employee_name,
            "rule_id": state.rule_id,
            "rule_name": state.rule_name,
            "severity": state.severity,
            "state": state.state,
            "occurrence_count": state.occurrence_count,
            "first_seen_period": state.first_seen_period.isoformat(),
            "financial_impact": float(state.last_financial_impact or 0),
            "waiver_reason": state.waiver_reason,
            "waived_until": state.waived_until.isoformat() if state.waived_until else None,
        }

    outstanding = [_finding(s) for s in states if s.state in ("open", "acknowledged")]
    accepted = [_finding(s) for s in states if s.state == "waived"]

    exposure_config = config_service.get_exposure_config(entity.id)
    exposure = analytics.statutory_exposure(db, entity.id, exposure_config)

    try:
        bridge = analytics.cost_bridge(db, entity.id, period_month)
    except Exception:
        # A period with no comparable prior month still signs off; the bridge
        # is context, not a precondition.
        bridge = None

    rates = (
        db.query(MinimumWageRate)
        .filter(
            MinimumWageRate.entity_id == entity.id,
            MinimumWageRate.effective_from <= period_month,
        )
        .all()
    )

    return {
        "entity": {
            "id": str(entity.id),
            "name": entity.name,
            "legal_name": entity.legal_name,
            "code": entity.code,
            "pf_establishment_code": entity.pf_establishment_code,
            "esic_employer_code": entity.esic_employer_code,
            "tan": entity.tan,
            "pan": entity.pan,
            "primary_state": entity.primary_state,
        },
        "period_month": period_month.isoformat(),
        "validation_run": (
            {
                "id": str(run.id),
                "employee_count": run.employee_count,
                "total_findings": run.total_findings,
                "critical_count": run.critical_count,
                "warning_count": run.warning_count,
                "gross_financial_impact": float(run.total_financial_impact),
                "open_financial_impact": float(run.open_financial_impact),
                "validated_at": run.created_at.isoformat() if run.created_at else None,
            }
            if run
            else None
        ),
        "outstanding_findings": outstanding,
        "accepted_findings": accepted,
        "exposure": exposure,
        "cost_bridge": bridge,
        # The rules and rates in force. Without these a finding cannot be
        # re-derived, and an evidence pack that cannot be re-derived is a
        # screenshot.
        "configuration": {
            "statutory": config_service.get_full_config(entity.id).model_dump(mode="json"),
            "rule_thresholds": config_service.get_rule_thresholds(entity.id).model_dump(mode="json"),
            "exposure": exposure_config.model_dump(mode="json"),
            "minimum_wage_rates": [
                {
                    "state": r.state,
                    "zone": r.zone,
                    "scheduled_employment": r.scheduled_employment,
                    "skill_category": r.skill_category,
                    "total_per_month": float(r.total_per_month),
                    "effective_from": r.effective_from.isoformat(),
                    "source_reference": r.source_reference,
                }
                for r in rates
            ],
        },
        "built_at": datetime.now(UTC).isoformat(),
    }


def get_or_create(db: Session, entity: Entity, period_month: date) -> PeriodSignOff:
    period_month = period_month.replace(day=1)
    signoff = (
        db.query(PeriodSignOff)
        .filter(
            PeriodSignOff.entity_id == entity.id,
            PeriodSignOff.period_month == period_month,
        )
        .first()
    )
    if signoff is None:
        signoff = PeriodSignOff(entity_id=entity.id, period_month=period_month, state="draft")
        db.add(signoff)
        db.flush()
    return signoff


def _record_event(
    db: Session,
    signoff: PeriodSignOff,
    *,
    from_state: str,
    to_state: str,
    actor: User | None,
    reason: str | None = None,
    superseded: dict | None = None,
) -> None:
    db.add(
        SignOffEvent(
            signoff_id=signoff.id,
            entity_id=signoff.entity_id,
            from_state=from_state,
            to_state=to_state,
            reason=reason,
            snapshot_digest=signoff.snapshot_digest,
            superseded_snapshot=superseded,
            actor_user_id=actor.id if actor else None,
            actor_email=actor.email if actor else None,
        )
    )


def submit(db: Session, entity: Entity, period_month: date, actor: User, notes: str | None) -> PeriodSignOff:
    """Prepare a period for approval, capturing what it looks like now."""
    signoff = get_or_create(db, entity, period_month)
    previous = signoff.state

    snapshot = build_snapshot(db, entity, period_month)
    signoff.snapshot = snapshot
    signoff.snapshot_digest = digest(snapshot)
    signoff.state = "pending_approval"
    signoff.prepared_by_user_id = actor.id
    signoff.prepared_at = datetime.now(UTC)
    signoff.notes = notes
    signoff.employee_count = (snapshot.get("validation_run") or {}).get("employee_count", 0)
    signoff.open_findings = len(snapshot["outstanding_findings"])
    signoff.accepted_exposure = Decimal(
        str(sum(f["financial_impact"] for f in snapshot["accepted_findings"]))
    )
    db.add(signoff)
    _record_event(db, signoff, from_state=previous, to_state="pending_approval", actor=actor)
    db.flush()
    return signoff


def sign(db: Session, signoff: PeriodSignOff, actor: User, notes: str | None) -> PeriodSignOff:
    """
    Approve the period.

    The snapshot is re-taken at this moment rather than reusing the one from
    submission: the signer is accepting what is true now, and anything that
    changed between preparation and approval is precisely what they need to
    have seen.
    """
    previous = signoff.state
    entity = db.get(Entity, signoff.entity_id)

    snapshot = build_snapshot(db, entity, signoff.period_month)
    signoff.snapshot = snapshot
    signoff.snapshot_digest = digest(snapshot)
    signoff.state = "signed"
    signoff.signed_by_user_id = actor.id
    signoff.signed_by_email = actor.email
    signoff.signed_at = datetime.now(UTC)
    if notes:
        signoff.notes = notes
    signoff.open_findings = len(snapshot["outstanding_findings"])
    signoff.accepted_exposure = Decimal(
        str(sum(f["financial_impact"] for f in snapshot["accepted_findings"]))
    )
    db.add(signoff)
    _record_event(db, signoff, from_state=previous, to_state="signed", actor=actor)
    db.flush()
    return signoff


def reopen(db: Session, signoff: PeriodSignOff, actor: User, reason: str) -> PeriodSignOff:
    """
    Reopen a signed period, preserving what was signed.

    The superseded snapshot is carried into the event rather than overwritten.
    A record that can be quietly replaced is not a record, and the reason a
    period was reopened is usually the most interesting thing about it.
    """
    previous = signoff.state
    superseded = signoff.snapshot
    _record_event(
        db, signoff,
        from_state=previous, to_state="reopened",
        actor=actor, reason=reason, superseded=superseded,
    )
    signoff.state = "reopened"
    db.add(signoff)
    db.flush()
    return signoff
