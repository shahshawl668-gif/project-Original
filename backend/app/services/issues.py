"""
Findings as work: ownership, due dates, comments, evidence, grouped decisions
and waivers that end.

The worklist is keyed by fingerprint, not by run, so everything here attaches
to a ``FindingState`` and survives re-validation. Three rules the code holds to:

* **A waiver always ends.** A waiver given without an end date lasts
  ``WAIVER_DEFAULT_DAYS``; none may run past ``WAIVER_MAX_DAYS``. When it
  lapses the finding is reopened and the reopening is recorded, so "accepted
  once" cannot quietly become "invisible forever".
* **Grouped decisions are individual decisions.** Resolving forty findings at
  once writes forty events with the same reason — the audit trail of each one
  must stand on its own.
* **Evidence is checked before it is kept.** Size, extension and the file's
  own first bytes must agree; an upload that claims to be a PDF and is not is
  refused.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.services.clock import india_today
from app.models import (
    Entity,
    FindingAttachment,
    FindingComment,
    FindingState,
    FindingStateEvent,
    OrgMembership,
    User,
)
from app.services import explain, finding_store, tenancy

WAIVER_DEFAULT_DAYS = 90
WAIVER_MAX_DAYS = 366
ATTACHMENT_MAX_BYTES = 5 * 1024 * 1024
WRITE_ROLES = ("owner", "manager", "analyst")

#: extension → (content type, predicate on the first bytes)
ALLOWED_ATTACHMENTS: dict[str, tuple[str, Any]] = {
    "pdf": ("application/pdf", lambda b: b.startswith(b"%PDF")),
    "png": ("image/png", lambda b: b.startswith(b"\x89PNG\r\n\x1a\n")),
    "jpg": ("image/jpeg", lambda b: b.startswith(b"\xff\xd8\xff")),
    "jpeg": ("image/jpeg", lambda b: b.startswith(b"\xff\xd8\xff")),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", lambda b: b.startswith(b"PK\x03\x04")),
    "xls": ("application/vnd.ms-excel", lambda b: b.startswith(b"\xd0\xcf\x11\xe0")),
    "csv": ("text/csv", lambda b: _is_text(b)),
    "txt": ("text/plain", lambda b: _is_text(b)),
}

ACTIVE_STATES = ("open", "acknowledged")


class IssueError(ValueError):
    pass


def _is_text(data: bytes) -> bool:
    try:
        data[:65536].decode("utf-8")
    except UnicodeDecodeError:
        return False
    return b"\x00" not in data[:65536]


# ---------------------------------------------------------------------------
# Waivers
# ---------------------------------------------------------------------------
def waiver_end(requested: date | None, today: date | None = None) -> date:
    """The date a new waiver ends: as asked, within bounds, never open-ended."""
    today = today or india_today()
    if requested is None:
        return today + timedelta(days=WAIVER_DEFAULT_DAYS)
    if requested < today:
        raise IssueError("A waiver cannot end in the past")
    if requested > today + timedelta(days=WAIVER_MAX_DAYS):
        raise IssueError(f"A waiver can last at most {WAIVER_MAX_DAYS} days; review it again then")
    return requested


def expire_waivers(db: Session, entity_id: Any, today: date | None = None) -> int:
    """Reopen every waiver whose end date has passed, recording why."""
    today = today or india_today()
    lapsed = (
        db.query(FindingState)
        .filter(
            FindingState.entity_id == entity_id,
            FindingState.state == "waived",
            FindingState.waived_until.isnot(None),
            FindingState.waived_until < today,
        )
        .all()
    )
    for state in lapsed:
        ended = state.waived_until
        finding_store.set_state(
            db, state=state, to_state="open", actor=None,
            reason=f"Waiver expired on {ended.isoformat()}; the finding is open again until someone decides.",
        )
    if lapsed:
        db.flush()
    return len(lapsed)


def decide(
    db: Session, *, state: FindingState, actor: User, to_state: str,
    reason: str | None, waived_until: date | None, note: str | None,
) -> FindingState:
    """One human decision, with the rules every decision path shares."""
    reason = (reason or "").strip() or None
    if to_state in ("waived", "resolved") and not reason:
        raise IssueError("A waiver must state a reason" if to_state == "waived"
                         else "Say why this is resolved — what was corrected, or why it was never an error")
    until = waiver_end(waived_until) if to_state == "waived" else None
    before = state.state
    out = finding_store.set_state(
        db, state=state, to_state=to_state, actor=actor, reason=reason, waived_until=until, note=note,
    )
    if before != to_state:
        from app.models import Entity
        from app.services.studio import events

        entity = db.get(Entity, state.entity_id)
        if entity is not None:
            events.emit(db, org_id=entity.org_id, entity_id=entity.id, type="finding.state_changed",
                        data={"fingerprint": state.fingerprint, "rule_id": state.rule_id,
                              "from": before, "to": to_state})
    return out


# ---------------------------------------------------------------------------
# People
# ---------------------------------------------------------------------------
def assignees(db: Session, entity: Entity) -> list[dict[str, str]]:
    """Members who can work this company's findings: write roles with access to it."""
    rows = (
        db.query(OrgMembership, User)
        .join(User, User.id == OrgMembership.user_id)
        .filter(OrgMembership.org_id == entity.org_id)
        .all()
    )
    out = []
    for _membership, user in rows:
        role = tenancy.effective_entity_role(db, user, entity)
        if role in WRITE_ROLES:
            out.append({"user_id": str(user.id), "email": user.email, "role": role})
    return sorted(out, key=lambda a: a["email"])


def assign(
    db: Session, *, entity: Entity, state: FindingState, actor: User,
    owner_user_id: uuid.UUID | None, due_date: date | None,
) -> FindingState:
    if owner_user_id is not None:
        allowed = {a["user_id"] for a in assignees(db, entity)}
        if str(owner_user_id) not in allowed:
            # Same answer whether the person does not exist or cannot work this
            # company: which people exist elsewhere is not this caller's business.
            raise IssueError("That person cannot work this company's findings")
    before = (state.owner_user_id, state.due_date)
    state.owner_user_id = owner_user_id
    state.due_date = due_date
    db.add(state)
    if before != (owner_user_id, due_date):
        owner = db.get(User, owner_user_id).email if owner_user_id else "nobody"
        db.add(FindingStateEvent(
            state_id=state.id, entity_id=state.entity_id,
            from_state=state.state, to_state=state.state,
            reason=f"Assigned to {owner}" + (f", due {due_date.isoformat()}" if due_date else ", no due date"),
            actor_user_id=actor.id, actor_email=actor.email,
        ))
    db.flush()
    return state


# ---------------------------------------------------------------------------
# Comments and evidence
# ---------------------------------------------------------------------------
def add_comment(db: Session, *, state: FindingState, actor: User, body: str) -> FindingComment:
    body = (body or "").strip()
    if not body:
        raise IssueError("A comment cannot be empty")
    comment = FindingComment(
        entity_id=state.entity_id, state_id=state.id, body=body[:4000],
        author_user_id=actor.id, author_email=actor.email,
    )
    db.add(comment)
    db.flush()
    return comment


def add_attachment(
    db: Session, *, state: FindingState, actor: User, filename: str, data: bytes,
) -> FindingAttachment:
    name = (filename or "").strip().replace("\\", "/").split("/")[-1][:255]
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in ALLOWED_ATTACHMENTS:
        raise IssueError("Attach a PDF, image (PNG or JPEG), spreadsheet (XLSX or XLS), CSV or text file")
    if not data:
        raise IssueError("The file is empty")
    if len(data) > ATTACHMENT_MAX_BYTES:
        raise IssueError("Files are limited to 5 MB")
    content_type, looks_right = ALLOWED_ATTACHMENTS[ext]
    if not looks_right(data):
        raise IssueError(f"The file's contents are not a valid .{ext} file")
    attachment = FindingAttachment(
        entity_id=state.entity_id, state_id=state.id, filename=name,
        content_type=content_type, size=len(data), sha256=hashlib.sha256(data).hexdigest(),
        data=data, uploaded_by_user_id=actor.id, uploaded_by_email=actor.email,
    )
    db.add(attachment)
    db.flush()
    return attachment


# ---------------------------------------------------------------------------
# The worklist
# ---------------------------------------------------------------------------
SEVERITY_ORDER = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}


def describe(state: FindingState, owners: dict[Any, str], counts: dict[str, dict[Any, int]],
             today: date) -> dict[str, Any]:
    impact = state.last_financial_impact
    return {
        "id": str(state.id),
        "fingerprint": state.fingerprint,
        "employee_id": state.employee_id,
        "employee_name": state.employee_name,
        "rule_id": state.rule_id,
        "rule_name": state.rule_name,
        "component": state.component,
        "severity": state.severity,
        "state": state.state,
        "first_seen_period": state.first_seen_period.isoformat(),
        "last_seen_period": state.last_seen_period.isoformat(),
        "occurrence_count": state.occurrence_count,
        "last_financial_impact": float(impact or 0),
        "impact_calculated": explain.impact_known(state.rule_id, impact),
        "resolved_period": state.resolved_period.isoformat() if state.resolved_period else None,
        "note": state.note,
        "waiver_reason": state.waiver_reason,
        "waived_until": state.waived_until.isoformat() if state.waived_until else None,
        # Waivers given before every waiver had to end: flagged for review
        # rather than silently given an end date nobody chose.
        "waiver_open_ended": state.state == "waived" and state.waived_until is None,
        "decided_at": state.decided_at.isoformat() if state.decided_at else None,
        "owner_user_id": str(state.owner_user_id) if state.owner_user_id else None,
        "owner_email": owners.get(state.owner_user_id),
        "due_date": state.due_date.isoformat() if state.due_date else None,
        "overdue": bool(state.due_date and state.due_date < today and state.state in ACTIVE_STATES),
        "comment_count": counts["comments"].get(state.id, 0),
        "attachment_count": counts["attachments"].get(state.id, 0),
    }


def _counts(db: Session, ids: list[Any]) -> dict[str, dict[Any, int]]:
    if not ids:
        return {"comments": {}, "attachments": {}}
    comments = dict(
        db.query(FindingComment.state_id, func.count(FindingComment.id))
        .filter(FindingComment.state_id.in_(ids)).group_by(FindingComment.state_id).all()
    )
    attachments = dict(
        db.query(FindingAttachment.state_id, func.count(FindingAttachment.id))
        .filter(FindingAttachment.state_id.in_(ids)).group_by(FindingAttachment.state_id).all()
    )
    return {"comments": comments, "attachments": attachments}


def owners_by_id(db: Session, ids: set[Any]) -> dict[Any, str]:
    ids = {i for i in ids if i is not None}
    if not ids:
        return {}
    return dict(db.query(User.id, User.email).filter(User.id.in_(ids)).all())


def worklist(
    db: Session, entity: Entity, user: User, *, page: int, page_size: int,
    state: str | None, severity: str | None, rule_id: str | None, owner: str | None,
    overdue: bool, recurring: bool, q: str | None, sort: str,
) -> dict[str, Any]:
    today = india_today()
    base = db.query(FindingState).filter(FindingState.entity_id == entity.id)

    counts = dict(
        db.query(FindingState.state, func.count(FindingState.id))
        .filter(FindingState.entity_id == entity.id).group_by(FindingState.state).all()
    )
    active = base.filter(FindingState.state.in_(ACTIVE_STATES))
    overdue_count = active.filter(FindingState.due_date.isnot(None), FindingState.due_date < today).count()
    unassigned = active.filter(FindingState.owner_user_id.is_(None)).count()

    query = base
    if state == "active":
        query = query.filter(FindingState.state.in_(ACTIVE_STATES))
    elif state:
        query = query.filter(FindingState.state == state)
    if severity:
        query = query.filter(FindingState.severity == severity)
    if rule_id:
        query = query.filter(FindingState.rule_id == rule_id)
    if owner == "me":
        query = query.filter(FindingState.owner_user_id == user.id)
    elif owner == "none":
        query = query.filter(FindingState.owner_user_id.is_(None))
    elif owner:
        try:
            query = query.filter(FindingState.owner_user_id == uuid.UUID(owner))
        except ValueError as exc:
            raise IssueError("Unknown owner filter") from exc
    if overdue:
        query = query.filter(
            FindingState.state.in_(ACTIVE_STATES),
            FindingState.due_date.isnot(None), FindingState.due_date < today,
        )
    if recurring:
        query = query.filter(FindingState.occurrence_count >= 3)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(
            FindingState.employee_id.ilike(like), FindingState.employee_name.ilike(like),
            FindingState.rule_id.ilike(like), FindingState.rule_name.ilike(like),
        ))

    rules = [
        {"rule_id": r, "rule_name": n, "count": c}
        for r, n, c in query.with_entities(
            FindingState.rule_id, func.min(FindingState.rule_name), func.count(FindingState.id)
        ).group_by(FindingState.rule_id).order_by(func.count(FindingState.id).desc()).limit(200).all()
    ]
    total = query.count()

    if sort == "due_date":
        # Dated first, soonest first; undated last.
        query = query.order_by(FindingState.due_date.is_(None), FindingState.due_date, FindingState.id)
    elif sort == "impact":
        query = query.order_by(FindingState.last_financial_impact.desc(), FindingState.id)
    elif sort == "last_seen":
        query = query.order_by(FindingState.last_seen_period.desc(), FindingState.id)
    else:
        from sqlalchemy import case

        rank = case(
            (FindingState.severity == "CRITICAL", 0), (FindingState.severity == "WARNING", 1), else_=2,
        )
        query = query.order_by(
            rank, FindingState.occurrence_count.desc(), FindingState.last_financial_impact.desc(), FindingState.id,
        )

    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    owners = owners_by_id(db, {r.owner_user_id for r in rows})
    extra = _counts(db, [r.id for r in rows])
    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": max(1, -(-total // page_size)),
        "items": [describe(r, owners, extra, today) for r in rows],
        "counts": {s: counts.get(s, 0) for s in ("open", "acknowledged", "waived", "resolved")},
        "overdue": overdue_count,
        "unassigned": unassigned,
        "rules": rules,
    }
