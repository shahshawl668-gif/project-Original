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

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_entity, get_current_user, require_entity_write
from app.envelope import ok
from app.models import (
    Entity,
    FindingAttachment,
    FindingComment,
    FindingState,
    FindingStateEvent,
    User,
    ValidationRun,
)
from app.schemas.findings import (
    FindingDecision,
    FindingEventOut,
    FindingStateOut,
    ValidationRunOut,
)
from app.services import audit, issues

router = APIRouter()


class AssignmentRequest(BaseModel):
    owner_user_id: uuid.UUID | None = None
    due_date: date | None = None


class CommentRequest(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class BulkRequest(BaseModel):
    fingerprints: list[str] = Field(min_length=1, max_length=500)
    action: str = Field(pattern="^(decision|assign)$")
    state: str | None = Field(default=None, pattern="^(open|acknowledged|waived|resolved)$")
    reason: str | None = Field(default=None, max_length=2000)
    waived_until: date | None = None
    note: str | None = Field(default=None, max_length=2000)
    owner_user_id: uuid.UUID | None = None
    due_date: date | None = None


def _issue_out(db: Session, state: FindingState) -> dict:
    owners = issues.owners_by_id(db, {state.owner_user_id})
    counts = issues._counts(db, [state.id])
    return issues.describe(state, owners, counts, date.today())


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
    if issues.expire_waivers(db, entity.id):
        db.commit()
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
    if issues.expire_waivers(db, entity.id):
        db.commit()
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


@router.get("/worklist")
def worklist(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    state: str | None = Query(default="active", pattern="^(active|open|acknowledged|waived|resolved)?$"),
    severity: str | None = Query(default=None, pattern="^(CRITICAL|WARNING|INFO)?$"),
    rule_id: str | None = Query(default=None, max_length=32),
    owner: str | None = Query(default=None, max_length=64),
    overdue: bool = Query(default=False),
    recurring: bool = Query(default=False),
    q: str | None = Query(default=None, max_length=100),
    sort: str = Query(default="priority", pattern="^(priority|due_date|impact|last_seen)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    """The findings worklist, paged on the server, with the counts its filters need."""
    if issues.expire_waivers(db, entity.id):
        db.commit()
    try:
        out = issues.worklist(
            db, entity, user, page=page, page_size=page_size, state=state or None,
            severity=severity or None, rule_id=rule_id or None, owner=owner or None,
            overdue=overdue, recurring=recurring, q=q, sort=sort,
        )
    except issues.IssueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(out)


@router.get("/assignees")
def list_assignees(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    """Who can be given a finding to work: write roles with access to this company."""
    return ok(issues.assignees(db, entity))


@router.post("/bulk")
def bulk(
    body: BulkRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_entity_write),
):
    """
    One decision or assignment applied to many findings.

    Each finding gets its own event with the shared reason. Fingerprints that
    are not this company's are reported as skipped rather than confirmed or
    denied individually.
    """
    if body.action == "decision" and not body.state:
        raise HTTPException(status_code=400, detail="Choose what to do with the selected findings")
    wanted = list(dict.fromkeys(body.fingerprints))
    rows = {
        s.fingerprint: s for s in db.query(FindingState).filter(
            FindingState.entity_id == entity.id, FindingState.fingerprint.in_(wanted)
        )
    }
    updated = 0
    skipped: list[dict[str, str]] = []
    try:
        for fp in wanted:
            state = rows.get(fp)
            if state is None:
                skipped.append({"fingerprint": fp, "reason": "Not found in this company"})
                continue
            if body.action == "decision":
                if state.state == body.state:
                    skipped.append({"fingerprint": fp, "reason": f"Already {body.state}"})
                    continue
                issues.decide(db, state=state, actor=user, to_state=body.state, reason=body.reason,
                              waived_until=body.waived_until, note=body.note)
            else:
                issues.assign(db, entity=entity, state=state, actor=user,
                              owner_user_id=body.owner_user_id, due_date=body.due_date)
            updated += 1
    except issues.IssueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit.record(
        db, entity_id=entity.id, org_id=entity.org_id, user=user,
        action="findings.bulk_" + body.action, object_type="finding", object_id=None,
        summary=(f"{updated} finding(s) → {body.state}" if body.action == "decision"
                 else f"{updated} finding(s) assigned"),
        detail={"fingerprints": wanted[:500], "reason": body.reason, "state": body.state},
    )
    db.commit()
    return ok({"updated": updated, "skipped": skipped})


@router.get("/runs")
def list_runs(
    include_superseded: bool = Query(default=False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    """Each period's current run; with ``include_superseded``, every run ever made.

    Current-only by default because every existing reader of this list treats
    it as one row per period — a trend chart fed superseded runs would count a
    re-validated month twice.
    """
    query = db.query(ValidationRun).filter(ValidationRun.entity_id == entity.id)
    if not include_superseded:
        query = query.filter(ValidationRun.status == "current")
    rows = query.order_by(
        ValidationRun.period_month.desc(), ValidationRun.run_number.desc()
    ).all()
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
    comments = (
        db.query(FindingComment).filter(FindingComment.state_id == state.id)
        .order_by(FindingComment.created_at).all()
    )
    attachments = (
        db.query(FindingAttachment).filter(FindingAttachment.state_id == state.id)
        .order_by(FindingAttachment.created_at).all()
    )
    return ok(
        {
            "finding": _issue_out(db, state),
            "history": [FindingEventOut.model_validate(e).model_dump(mode="json") for e in events],
            "comments": [
                {"id": str(c.id), "body": c.body, "author_email": c.author_email,
                 "created_at": c.created_at.isoformat() if c.created_at else None}
                for c in comments
            ],
            "attachments": [
                {"id": str(a.id), "filename": a.filename, "content_type": a.content_type, "size": a.size,
                 "sha256": a.sha256, "uploaded_by_email": a.uploaded_by_email,
                 "created_at": a.created_at.isoformat() if a.created_at else None}
                for a in attachments
            ],
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
    try:
        issues.decide(db, state=state, actor=user, to_state=body.state, reason=body.reason,
                      waived_until=body.waived_until, note=body.note)
    except issues.IssueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    db.refresh(state)
    return ok(_issue_out(db, state))


@router.patch("/{fingerprint}/assignment")
def set_assignment(
    fingerprint: str,
    body: AssignmentRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_entity_write),
):
    state = _load(db, entity, fingerprint)
    try:
        issues.assign(db, entity=entity, state=state, actor=user,
                      owner_user_id=body.owner_user_id, due_date=body.due_date)
    except issues.IssueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    db.refresh(state)
    return ok(_issue_out(db, state))


@router.post("/{fingerprint}/comments")
def add_comment(
    fingerprint: str,
    body: CommentRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_entity_write),
):
    state = _load(db, entity, fingerprint)
    try:
        comment = issues.add_comment(db, state=state, actor=user, body=body.body)
    except issues.IssueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return ok({"id": str(comment.id), "body": comment.body, "author_email": comment.author_email,
               "created_at": comment.created_at.isoformat() if comment.created_at else None})


@router.post("/{fingerprint}/attachments")
async def add_attachment(
    fingerprint: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_entity_write),
):
    state = _load(db, entity, fingerprint)
    # Read one byte past the limit, so an oversized upload is refused without
    # holding all of it.
    data = await file.read(issues.ATTACHMENT_MAX_BYTES + 1)
    try:
        attachment = issues.add_attachment(db, state=state, actor=user, filename=file.filename or "", data=data)
    except issues.IssueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit.record(
        db, entity_id=entity.id, org_id=entity.org_id, user=user, action="finding.attachment_added",
        object_type="finding", object_id=fingerprint,
        summary=f"Attached {attachment.filename} to {state.rule_id} for {state.employee_id}",
        detail={"sha256": attachment.sha256, "size": attachment.size},
    )
    db.commit()
    return ok({"id": str(attachment.id), "filename": attachment.filename,
               "content_type": attachment.content_type, "size": attachment.size,
               "sha256": attachment.sha256, "uploaded_by_email": attachment.uploaded_by_email,
               "created_at": attachment.created_at.isoformat() if attachment.created_at else None})


@router.get("/{fingerprint}/attachments/{attachment_id}")
def download_attachment(
    fingerprint: str,
    attachment_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    state = _load(db, entity, fingerprint)
    attachment = db.query(FindingAttachment).filter(
        FindingAttachment.id == attachment_id, FindingAttachment.state_id == state.id,
        FindingAttachment.entity_id == entity.id,
    ).first()
    if attachment is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    safe = "".join(ch for ch in attachment.filename if ch.isalnum() or ch in "._- ") or "attachment"
    return Response(
        content=attachment.data, media_type=attachment.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{safe}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


def _load(db: Session, entity: Entity, fingerprint: str) -> FindingState:
    state = (
        db.query(FindingState)
        .filter(FindingState.entity_id == entity.id, FindingState.fingerprint == fingerprint)
        .first()
    )
    if state is None:
        raise HTTPException(status_code=404, detail="Finding not found")
    return state
