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

from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.models import (
    FindingRecord,
    FindingState,
    FindingStateEvent,
    User,
    ValidationRun,
    ValidationRunEmployee,
)
from app.models.findings import ENGINE_VERSION
from app.services.explain import deduplicated_exposure
from app.services.register_uploads import gzip_json


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


def current_run(db: Session, entity_id: uuid.UUID, period_month: date) -> ValidationRun | None:
    """The run that is the period's answer now. Superseded runs are history."""
    return (
        db.query(ValidationRun)
        .filter(
            ValidationRun.entity_id == entity_id,
            ValidationRun.period_month == period_month.replace(day=1),
            ValidationRun.status == "current",
        )
        .order_by(ValidationRun.run_number.desc())
        .first()
    )


def _employee_row(
    run: ValidationRun,
    position: int,
    result: dict[str, Any],
    source: dict[str, Any] | None,
) -> dict[str, Any]:
    findings = result.get("findings") or []
    failed = [f for f in findings if f.get("status") == "FAIL"]
    source = source or {}

    def _text(*keys: str) -> str | None:
        for key in keys:
            value = source.get(key)
            if value not in (None, ""):
                return str(value)[:255]
        return None

    net = source.get("net_pay", source.get("net", source.get("net_salary")))
    return {
        "id": uuid.uuid4(),
        "run_id": run.id,
        "entity_id": run.entity_id,
        "position": position,
        "employee_id": str(result.get("employee_id") or "")[:64],
        "employee_name": _truncate(result.get("employee_name")),
        "department": _text("department"),
        "work_state": (_text("work_state", "state", "location_state") or "")[:64] or None,
        "row_kind": _truncate(result.get("row_kind_label"), 64),
        "risk_score": int(result.get("risk_score") or 0),
        "risk_level": str(result.get("risk_level") or "LOW")[:16],
        "failed_checks": len(failed),
        "critical_count": sum(1 for f in failed if f.get("severity") == "CRITICAL"),
        "warning_count": sum(1 for f in failed if f.get("severity") == "WARNING"),
        "passed_checks": (result.get("coverage_counts") or {}).get(
            "passed", sum(1 for f in findings if f.get("status") == "PASS")),
        "cannot_validate_checks": (result.get("coverage_counts") or {}).get("cannot_validate", 0),
        "not_applicable_checks": (result.get("coverage_counts") or {}).get("not_applicable", 0),
        # The same rupees reported by overlapping checks are counted once, as
        # in the run total, so the employee figures add up to it.
        "financial_impact": deduplicated_exposure(failed)["exposure"],
        "gross": _dec(result.get("gross_total")) if result.get("gross_total") is not None else None,
        "net_pay": _dec(net) if net not in (None, "") else None,
        "detail_gz": gzip_json(result),
    }


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
    results: list[dict[str, Any]] | None = None,
    source_rows: list[dict[str, Any]] | None = None,
    upload_id: uuid.UUID | None = None,
    source: str = "api",
    job_id: uuid.UUID | None = None,
    run_type: str | None = None,
    params: dict[str, Any] | None = None,
    input_digests: dict[str, Any] | None = None,
    config_snapshot: dict[str, Any] | None = None,
    started_at: datetime | None = None,
) -> ValidationRun:
    """
    Persist one period's findings as a new run, and reconcile lifecycle state.

    Nothing is deleted. The period's previous current run becomes
    ``superseded`` and points at this one, so every result ever reported stays
    readable and two runs can be compared. The partial unique index on
    (entity, period) WHERE status = 'current' is what holds if two validations
    of one period finish at once: the second fails and is retried, rather than
    leaving two runs that both claim to be the answer.
    """
    period_month = period_month.replace(day=1)
    now = datetime.now(UTC)

    failures = [f for f in findings if f.get("status") == "FAIL"]

    previous = (
        db.query(ValidationRun)
        .filter(ValidationRun.entity_id == entity_id, ValidationRun.period_month == period_month)
        .all()
    )
    run_number = max((r.run_number or 1 for r in previous), default=0) + 1

    from app.services.issues import expire_waivers

    # Lapsed waivers reopen before the run reads them, with their own event.
    expire_waivers(db, entity_id)
    waived_now = waived_fingerprints(db, entity_id, period_month)

    run = ValidationRun(
        id=uuid.uuid4(),
        entity_id=entity_id,
        user_id=user_id,
        period_month=period_month,
        register_id=register_id,
        employee_count=employee_count,
        summary=summary or {},
        status="current",
        run_number=run_number,
        source=source,
        job_id=job_id,
        upload_id=upload_id,
        run_type=run_type,
        params=params,
        engine_version=ENGINE_VERSION,
        input_digests=input_digests,
        config_snapshot=config_snapshot,
        started_at=started_at or now,
        finished_at=now,
        duration_ms=int(((now - _aware(started_at)).total_seconds()) * 1000) if started_at else None,
    )
    for stale in previous:
        if stale.status == "current":
            stale.status = "superseded"
            stale.superseded_at = now
            stale.superseded_by_run_id = run.id
            db.add(stale)
    # The superseded flag must land before the new current row, or the partial
    # unique index sees two current runs for a moment and refuses the insert.
    db.flush()
    db.add(run)
    db.flush()

    if results is not None:
        by_eid: dict[str, dict[str, Any]] = {}
        for row in source_rows or []:
            key = str(row.get("employee_id") or row.get("emp_id") or row.get("employee_code") or "").strip()
            by_eid.setdefault(key, row)
        # Core bulk insert, in batches: 20,000 ORM objects held in the session
        # until commit cost memory and time the result never needed.
        batch: list[dict[str, Any]] = []
        for position, result in enumerate(results):
            batch.append(_employee_row(run, position, result, by_eid.get(str(result.get("employee_id") or ""))))
            if len(batch) >= 1000:
                db.execute(insert(ValidationRunEmployee), batch)
                batch = []
        if batch:
            db.execute(insert(ValidationRunEmployee), batch)

    gross = Decimal("0")
    open_impact = Decimal("0")
    critical = 0
    warning = 0
    seen: dict[str, dict[str, Any]] = {}
    finding_rows: list[dict[str, Any]] = []
    waived_flags: list[bool] = []

    for finding in failures:
        fp = fingerprint(
            entity_id,
            str(finding.get("employee_id") or ""),
            str(finding.get("rule_id") or ""),
            finding.get("component"),
        )
        impact = _dec(finding.get("financial_impact"))
        is_waived = fp in waived_now
        waived_flags.append(is_waived)

        gross += impact
        if not is_waived:
            open_impact += impact
            if finding.get("severity") == "CRITICAL":
                critical += 1
            elif finding.get("severity") == "WARNING":
                warning += 1

        finding_rows.append(
            {
                "id": uuid.uuid4(),
                "run_id": run.id,
                "entity_id": entity_id,
                "period_month": period_month,
                "fingerprint": fp,
                "employee_id": str(finding.get("employee_id") or ""),
                "employee_name": _truncate(finding.get("employee_name")),
                "rule_id": str(finding.get("rule_id") or ""),
                "rule_name": _truncate(finding.get("rule_name"), 255) or "",
                "component": _truncate(finding.get("component")),
                "severity": str(finding.get("severity") or "INFO"),
                "status": str(finding.get("status") or "FAIL"),
                "expected_value": _truncate(finding.get("expected_value")),
                "actual_value": _truncate(finding.get("actual_value")),
                "difference": _truncate(finding.get("difference")),
                "financial_impact": impact,
                "reason": finding.get("reason"),
                "rule_version_id": uuid.UUID(finding["rule_version_id"]) if finding.get("rule_version_id") else None,
                "evidence": finding.get("evidence"),
                "suggested_fix": finding.get("suggested_fix"),
                "was_waived": is_waived,
            }
        )
        if len(finding_rows) >= 2000:
            db.execute(insert(FindingRecord), finding_rows)
            finding_rows = []
        # One state row per fingerprint even if a rule fires twice in a period.
        seen[fp] = finding
    if finding_rows:
        db.execute(insert(FindingRecord), finding_rows)

    # Exposure without counting the same rupees twice, and without presenting
    # an uncalculated impact as zero: see services/explain.py.
    gross_exposure = deduplicated_exposure(failures)
    open_exposure = deduplicated_exposure([f for f, w in zip(failures, waived_flags, strict=True) if not w])
    run.total_findings = len(failures)
    run.critical_count = critical
    run.warning_count = warning
    run.total_financial_impact = gross_exposure["exposure"]
    run.open_financial_impact = open_exposure["exposure"]
    run.summary = {
        **(run.summary or {}),
        "exposure": {
            "gross": float(gross_exposure["exposure"]),
            "open": float(open_exposure["exposure"]),
            "overlap_excluded": float(gross_exposure["overlap_excluded"]),
            "impact_not_calculated": gross_exposure["impact_not_calculated"],
            "raw_sum_before_deduplication": float(gross),
        },
    }

    _reconcile_states(db, entity_id, period_month, seen)
    db.flush()
    return run


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


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
        if state.last_seen_period > period_month:
            continue  # belongs to a later period; this is a back-fill run
        # Last seen in this very period and absent from this run: a corrected
        # register was re-validated and the issue is gone. That is a resolution,
        # and the comparison between the two runs depends on it being recorded.
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
