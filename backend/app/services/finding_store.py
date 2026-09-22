"""
Persisting findings and advancing their lifecycle.

The entry point is :func:`record_run`, called after validation produces findings
for a period. It writes the run, writes each finding, and reconciles the
per-fingerprint state: new findings open, repeat findings increment, and
findings that stopped appearing resolve themselves.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import date, datetime, UTC
from decimal import Decimal
from typing import Any
from collections.abc import Iterable

from sqlalchemy.orm import Session

from app.models import (
    FindingRecord,
    FindingState,
    FindingStateEvent,
    User,
    ValidationRun,
)


def fingerprint(entity_id: uuid.UUID, employee_id: str, rule_id: str, component: str | None) -> str:
    """
    A stable identity for "this issue, about this person, under this rule".

    Deliberately excludes the period: that is what lets an explanation given in
    April still apply in May, and what makes recurrence countable. It also
    excludes the amounts, so a PF shortfall that changes size month to month is
    recognised as the same ongoing problem rather than a fresh one each time.
    """
    parts = "|".join([str(entity_id), employee_id or "", rule_id or "", (component or "").lower()])
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()[:32]


def _dec(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def _truncate(value: Any, limit: int = 255) -> str | None:
    if value in (None, ""):
        return None
    text = str(value)
    return text[:limit]


def waived_fingerprints(db: Session, entity_id: uuid.UUID, period: date) -> set[str]:
    """Fingerprints whose waiver is in force for ``period``."""
    states = (
        db.query(FindingState)
        .filter(FindingState.entity_id == entity_id, FindingState.state == "waived")
        .all()
    )
    return {s.fingerprint for s in states if s.is_waived_for(period)}


def record_run(
    db: Session,
    *,
    entity_id: uuid.UUID,
    user_id: uuid.UUID,
    period_month: date,
    findings: Iterable[dict[str, Any]],
    employee_count: int,
    register_id: uuid.UUID | None = None,
    summary: dict[str, Any] | None = None,
) -> ValidationRun:
    """
    Persist one period's findings and reconcile lifecycle state.

    Re-validating a period replaces that period's records rather than stacking
    another copy, so a corrected register produces one history, not two.
    """
    period_month = period_month.replace(day=1)

    failures = [f for f in findings if f.get("status") == "FAIL"]

    # A re-run supersedes the previous run for this period.
    for stale in (
        db.query(ValidationRun)
        .filter(ValidationRun.entity_id == entity_id, ValidationRun.period_month == period_month)
        .all()
    ):
        db.delete(stale)
    db.flush()

    waived_now = waived_fingerprints(db, entity_id, period_month)

    run = ValidationRun(
        entity_id=entity_id,
        user_id=user_id,
        period_month=period_month,
        register_id=register_id,
        employee_count=employee_count,
        summary=summary or {},
    )
    db.add(run)
    db.flush()

    gross = Decimal("0")
    open_impact = Decimal("0")
    critical = 0
    warning = 0
    seen: dict[str, dict[str, Any]] = {}

    for finding in failures:
        fp = fingerprint(
            entity_id,
            str(finding.get("employee_id") or ""),
            str(finding.get("rule_id") or ""),
            finding.get("component"),
        )
        impact = _dec(finding.get("financial_impact"))
        is_waived = fp in waived_now

        gross += impact
        if not is_waived:
            open_impact += impact
            if finding.get("severity") == "CRITICAL":
                critical += 1
            elif finding.get("severity") == "WARNING":
                warning += 1

        db.add(
            FindingRecord(
                run_id=run.id,
                entity_id=entity_id,
                period_month=period_month,
                fingerprint=fp,
                employee_id=str(finding.get("employee_id") or ""),
                employee_name=_truncate(finding.get("employee_name")),
                rule_id=str(finding.get("rule_id") or ""),
                rule_name=_truncate(finding.get("rule_name"), 255) or "",
                component=_truncate(finding.get("component")),
                severity=str(finding.get("severity") or "INFO"),
                status=str(finding.get("status") or "FAIL"),
                expected_value=_truncate(finding.get("expected_value")),
                actual_value=_truncate(finding.get("actual_value")),
                difference=_truncate(finding.get("difference")),
                financial_impact=impact,
                reason=finding.get("reason"),
                suggested_fix=finding.get("suggested_fix"),
                was_waived=is_waived,
            )
        )
        # One state row per fingerprint even if a rule fires twice in a period.
        seen[fp] = finding

    run.total_findings = len(failures)
    run.critical_count = critical
    run.warning_count = warning
    run.total_financial_impact = gross
    run.open_financial_impact = open_impact

    _reconcile_states(db, entity_id, period_month, seen)
    db.flush()
    return run


def _reconcile_states(
    db: Session,
    entity_id: uuid.UUID,
    period_month: date,
    seen: dict[str, dict[str, Any]],
) -> None:
    """Open new fingerprints, advance repeats, resolve those that stopped."""
    existing = {
        state.fingerprint: state
        for state in db.query(FindingState).filter(FindingState.entity_id == entity_id).all()
    }

    for fp, finding in seen.items():
        state = existing.get(fp)
        impact = _dec(finding.get("financial_impact"))
        if state is None:
            db.add(
                FindingState(
                    entity_id=entity_id,
                    fingerprint=fp,
                    employee_id=str(finding.get("employee_id") or ""),
                    employee_name=_truncate(finding.get("employee_name")),
                    rule_id=str(finding.get("rule_id") or ""),
                    rule_name=_truncate(finding.get("rule_name"), 255) or "",
                    component=_truncate(finding.get("component")),
                    severity=str(finding.get("severity") or "INFO"),
                    state="open",
                    first_seen_period=period_month,
                    last_seen_period=period_month,
                    occurrence_count=1,
                    last_financial_impact=impact,
                )
            )
            continue

        # Count each period once, so re-running a month does not inflate the
        # recurrence figure people will use to judge severity.
        if state.last_seen_period != period_month:
            state.occurrence_count += 1
        state.last_seen_period = max(state.last_seen_period, period_month)
        state.last_financial_impact = impact
        state.severity = str(finding.get("severity") or state.severity)
        if state.state == "resolved":
            # It came back. Reopen rather than leave a stale "resolved".
            state.state = "open"
            state.resolved_period = None
        db.add(state)

    # Anything previously open that this period did not produce has stopped.
    for fp, state in existing.items():
        if fp in seen or state.state in ("resolved", "waived"):
            continue
        if state.last_seen_period >= period_month:
            continue  # belongs to a later period; this is a back-fill run
        state.state = "resolved"
        state.resolved_period = period_month
        db.add(state)


def set_state(
    db: Session,
    *,
    state: FindingState,
    to_state: str,
    actor: User | None,
    reason: str | None = None,
    waived_until: date | None = None,
    note: str | None = None,
) -> FindingState:
    """
    Apply a human decision and append it to the audit trail.

    The event row is what makes the decision defensible later, so it is written
    on every transition, including ones that look trivial at the time.
    """
    previous = state.state
    state.state = to_state
    state.decided_by_user_id = actor.id if actor else None
    state.decided_at = datetime.now(UTC)
    if note is not None:
        state.note = note
    if to_state == "waived":
        state.waiver_reason = reason
        state.waived_until = waived_until
    else:
        state.waiver_reason = None
        state.waived_until = None
    db.add(state)

    db.add(
        FindingStateEvent(
            state_id=state.id,
            entity_id=state.entity_id,
            from_state=previous,
            to_state=to_state,
            reason=reason,
            waived_until=waived_until,
            actor_user_id=actor.id if actor else None,
            actor_email=actor.email if actor else None,
        )
    )
    db.flush()
    return state
