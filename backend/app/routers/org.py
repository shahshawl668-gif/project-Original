"""
Organization and entity management.

``GET /api/org/context`` is the endpoint the frontend calls on boot: it returns
the organization, the caller's role, and the entities they may open, so the
entity switcher can render without a second round trip.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import (
    SYSTEM_USER_EMAIL,
    get_current_entity,
    get_current_user,
    require_org_admin,
)
from app.envelope import ok
from app.models import (
    Entity,
    EntityAccess,
    EntityRoleOverride,
    FindingState,
    OrgInvitation,
    OrgMembership,
    Organization,
    PeriodSignOff,
    SalaryRegister,
    SupportAccessGrant,
    User,
)
from app.schemas.org import (
    ContextOut,
    EntityCreate,
    EntityRoleUpdate,
    EntityOut,
    EntityUpdate,
    InvitationAccept,
    InvitationCreate,
    InvitationRegister,
    MemberUpdate,
    OrganizationOut,
    OrganizationUpdate,
)
from app.security import hash_password
from app.services import audit, auth_security, invitations, support_access, tenancy

router = APIRouter()


@router.get("/context")
def get_context(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    membership = tenancy.get_membership(db, user)
    org = db.get(Organization, membership.org_id) if membership else None
    entities = tenancy.accessible_entities(db, user)
    if getattr(request.state, "auth_claims", {}).get("portal") == "support":
        org = db.get(Organization, entity.org_id)
        entities = [item for item in entities if item.org_id == entity.org_id]
    entity_roles = {str(item.id): tenancy.effective_entity_role(db, user, item) or "viewer" for item in entities}
    can_manage_group = bool(
        membership and membership.org_id == entity.org_id
        and tenancy.role_at_least(db, user, "manager")
        and (
            membership.role == "owner"
            or db.query(EntityAccess.id).filter(
                EntityAccess.org_id == membership.org_id,
                EntityAccess.user_id == user.id,
            ).first() is None
        )
    )
    payload = ContextOut(
        can_manage_group=can_manage_group,
        active_role=entity_roles.get(str(entity.id), "viewer"),
        entity_roles=entity_roles,
        organization=OrganizationOut.model_validate(org) if org else None,
        role=membership.role if membership and membership.org_id == entity.org_id else "viewer" if org else None,
        active_entity=EntityOut.model_validate(entity),
        entities=[EntityOut.model_validate(e) for e in entities],
    )
    return ok(payload.model_dump(mode="json"))


@router.get("/portfolio")
def portfolio(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """
    Every company this person can see, with the state of each one.

    A group runs several employers and the question on any given morning is
    which of them needs attention — not what the one you happen to have selected
    looks like. Answering that by switching entity and re-reading a dashboard
    five times is how things get missed.

    Deliberately one request rather than one per company: a practice with thirty
    clients would otherwise open thirty connections to render a landing page.
    """
    entities = tenancy.accessible_entities(db, user)
    if not entities:
        return ok({"entities": [], "totals": {}})

    entity_ids = [e.id for e in entities]

    # Latest register per entity, and how many people were on it.
    latest_period: dict[uuid.UUID, date] = {}
    headcount: dict[uuid.UUID, int] = {}
    for entity_id, period, count in (
        db.query(
            SalaryRegister.entity_id,
            SalaryRegister.period_month,
            SalaryRegister.employee_count,
        )
        .filter(SalaryRegister.entity_id.in_(entity_ids))
        .order_by(SalaryRegister.entity_id, SalaryRegister.period_month.desc())
        .all()
    ):
        if entity_id not in latest_period:
            latest_period[entity_id] = period
            headcount[entity_id] = count or 0

    # Open findings, and the ones that cannot wait, counted per entity.
    open_counts: dict[uuid.UUID, int] = {}
    critical_counts: dict[uuid.UUID, int] = {}
    exposure: dict[uuid.UUID, Decimal] = {}
    for state in (
        db.query(FindingState)
        .filter(FindingState.entity_id.in_(entity_ids), FindingState.state == "open")
        .all()
    ):
        open_counts[state.entity_id] = open_counts.get(state.entity_id, 0) + 1
        exposure[state.entity_id] = exposure.get(state.entity_id, Decimal("0")) + (
            state.last_financial_impact or Decimal("0")
        )
        if (state.severity or "").upper() == "CRITICAL":
            critical_counts[state.entity_id] = critical_counts.get(state.entity_id, 0) + 1

    signoffs = {
        (s.entity_id, s.period_month): s.state
        for s in db.query(PeriodSignOff)
        .filter(PeriodSignOff.entity_id.in_(entity_ids))
        .all()
    }

    rows = []
    for entity in entities:
        period = latest_period.get(entity.id)
        rows.append(
            {
                "id": str(entity.id),
                "name": entity.name,
                "code": entity.code,
                "primary_state": entity.primary_state,
                "last_register_period": period.isoformat() if period else None,
                "employee_count": headcount.get(entity.id, 0),
                "open_findings": open_counts.get(entity.id, 0),
                "critical_findings": critical_counts.get(entity.id, 0),
                "exposure": float(exposure.get(entity.id, Decimal("0"))),
                "signoff_state": signoffs.get((entity.id, period)) if period else None,
            }
        )

    # Sorted by what needs doing: anything critical first, then anything open,
    # then alphabetically. A landing page that sorts by name buries the problem.
    rows.sort(key=lambda r: (-r["critical_findings"], -r["open_findings"], r["name"].lower()))

    totals = {
        "entities": len(rows),
        "employees": sum(r["employee_count"] for r in rows),
        "open_findings": sum(r["open_findings"] for r in rows),
        "critical_findings": sum(r["critical_findings"] for r in rows),
        "exposure": sum(r["exposure"] for r in rows),
        "awaiting_register": sum(1 for r in rows if r["last_register_period"] is None),
    }
    return ok({"entities": rows, "totals": totals})


@router.get("/entities")
def list_entities(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    entities = tenancy.accessible_entities(db, user)
    return ok([EntityOut.model_validate(e).model_dump(mode="json") for e in entities])


@router.post("/entities")
def create_entity(
    body: EntityCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_org_admin),
):
    membership = tenancy.get_membership(db, user)
    if membership is None:
        raise HTTPException(status_code=400, detail="No organization for this user")

    code = (body.code or "").strip().upper() or tenancy.unique_entity_code(db, membership.org_id, body.name)
    clash = (
        db.query(Entity)
        .filter(Entity.org_id == membership.org_id, Entity.code == code)
        .first()
    )
    if clash:
        raise HTTPException(status_code=400, detail=f"Entity code '{code}' already in use")

    entity = Entity(
        org_id=membership.org_id,
        code=code,
        **body.model_dump(exclude={"code"}),
    )
    db.add(entity)
    db.flush()
    audit.record(
        db, entity_id=entity.id, org_id=membership.org_id, user=user,
        action="entity.created", object_type="entity", object_id=str(entity.id),
        summary=f"Added group company {entity.name}",
    )
    db.commit()
    db.refresh(entity)
    return ok(EntityOut.model_validate(entity).model_dump(mode="json"))


@router.patch("/entities/{entity_id}")
def update_entity(
    entity_id: uuid.UUID,
    body: EntityUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_org_admin),
):
    entity = db.get(Entity, entity_id)
    if entity is None or not tenancy.can_access_entity(db, user, entity):
        raise HTTPException(status_code=404, detail="Entity not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(entity, field, value)
    db.add(entity)
    audit.record(
        db, entity_id=entity.id, org_id=entity.org_id, user=user,
        action="entity.updated", object_type="entity", object_id=str(entity.id),
        summary=f"Updated group company {entity.name}",
    )
    db.commit()
    db.refresh(entity)
    return ok(EntityOut.model_validate(entity).model_dump(mode="json"))


@router.post("/entities/{entity_id}/select")
def select_entity(
    entity_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Remember this entity as the caller's default.

    Requests may always override with ``X-Entity-Id``; this is what the switcher
    calls so the choice survives a reload, and so a header-less request from
    another client of theirs still lands where they expect.
    """
    entity = db.get(Entity, entity_id)
    if entity is None or not tenancy.can_access_entity(db, user, entity):
        raise HTTPException(status_code=404, detail="Entity not found")
    tenancy.set_default_entity(db, user, entity)
    db.commit()
    return ok(EntityOut.model_validate(entity).model_dump(mode="json"))


@router.get("/members")
def list_members(db: Session = Depends(get_db), user: User = Depends(require_org_admin)):
    """
    Everyone in this organization, with the entities each can open.

    ``entity_ids`` empty means the whole organization — the same convention
    ``EntityAccess`` uses, where no rows means no restriction.
    """
    membership = tenancy.get_membership(db, user)
    if membership is None:
        return ok([])
    rows = (
        db.query(OrgMembership, User)
        .join(User, User.id == OrgMembership.user_id)
        .filter(OrgMembership.org_id == membership.org_id)
        .order_by(OrgMembership.created_at)
        .all()
    )
    return ok([
        _member_out(
            m,
            u.email,
            invitations.entity_access_for(db, membership.org_id, m.user_id),
            m.user_id == user.id,
            {str(row.entity_id): row.role for row in db.query(EntityRoleOverride).filter(
                EntityRoleOverride.org_id == membership.org_id,
                EntityRoleOverride.user_id == m.user_id,
            )},
        )
        for m, u in rows
    ])


@router.patch("")
def update_org(
    body: OrganizationUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_org_admin),
):
    membership = tenancy.get_membership(db, user)
    if membership is None:
        raise HTTPException(status_code=400, detail="No organization for this user")
    org = db.get(Organization, membership.org_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(org, field, value)
    db.add(org)
    db.commit()
    db.refresh(org)
    return ok(OrganizationOut.model_validate(org).model_dump(mode="json"))


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------
def _actor_role(db: Session, user: User) -> str:
    membership = tenancy.get_membership(db, user)
    if membership is None:
        raise HTTPException(status_code=400, detail="No organization for this user")
    return membership.role


def _guard(exc: invitations.InvitationError):
    return HTTPException(status_code=exc.status, detail=str(exc))


def _member_out(membership: OrgMembership, email: str | None, scoped: list[str], you: bool,
                entity_roles: dict[str, str]) -> dict:
    return {
        "id": str(membership.id),
        "user_id": str(membership.user_id),
        "email": email,
        "role": membership.role,
        "entity_ids": scoped,
        "entity_roles": entity_roles,
        "is_you": you,
        "joined_at": membership.created_at.isoformat() if membership.created_at else None,
    }


def _invitation_out(invitation: OrgInvitation, token: str | None = None) -> dict:
    payload = {
        "id": str(invitation.id),
        "email": invitation.email,
        "role": invitation.role,
        "state": invitations.effective_state(invitation),
        "entity_ids": [str(e) for e in (invitation.entity_ids or [])],
        "note": invitation.note,
        "invited_by": invitation.invited_by_email,
        "created_at": invitation.created_at.isoformat() if invitation.created_at else None,
        "expires_at": invitation.expires_at.isoformat() if invitation.expires_at else None,
        "accepted_at": invitation.accepted_at.isoformat() if invitation.accepted_at else None,
    }
    if token is not None:
        payload["token"] = token
    return payload


@router.patch("/members/{user_id}")
def update_member(
    user_id: uuid.UUID,
    body: MemberUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_org_admin),
):
    """
    Change a member's role, the entities they can open, or both.

    Both fields are independent. Sending ``entity_ids: []`` widens the member to
    the whole organization; omitting the field leaves their scoping alone.
    """
    membership = tenancy.get_membership(db, user)
    if membership is None:
        raise HTTPException(status_code=400, detail="No organization for this user")

    target = (
        db.query(OrgMembership)
        .filter(OrgMembership.org_id == membership.org_id, OrgMembership.user_id == user_id)
        .first()
    )
    if target is None:
        raise HTTPException(status_code=404, detail="That person is not a member of this organization")

    actor_role = membership.role
    changes: list[str] = []

    try:
        if body.role is not None and body.role != target.role:
            previous = target.role
            invitations.change_role(
                db, membership=target, actor=user, actor_role=actor_role, role=body.role
            )
            changes.append(f"role {previous} → {body.role}")
        if body.entity_ids is not None:
            scoped = invitations.set_entity_access(
                db,
                org_id=membership.org_id,
                user_id=user_id,
                entity_ids=[str(e) for e in body.entity_ids],
            )
            changes.append(
                f"access to {len(scoped)} entities" if scoped else "access to every entity"
            )
    except invitations.InvitationError as exc:
        raise _guard(exc)

    target_user = db.get(User, user_id)
    if changes:
        audit.record(
            db, entity_id=None, org_id=membership.org_id, user=user, action="member.updated",
            object_type="org_membership", object_id=str(user_id),
            summary=f"Updated {getattr(target_user, 'email', user_id)} — " + ", ".join(changes),
        )
    db.commit()
    db.refresh(target)

    scoped = invitations.entity_access_for(db, membership.org_id, user_id)
    roles = {str(row.entity_id): row.role for row in db.query(EntityRoleOverride).filter(
        EntityRoleOverride.org_id == membership.org_id,
        EntityRoleOverride.user_id == user_id,
    )}
    return ok(_member_out(target, getattr(target_user, "email", None), scoped,
                          target.user_id == user.id, roles))


@router.patch("/members/{user_id}/company-roles/{entity_id}")
def update_company_role(
    user_id: uuid.UUID,
    entity_id: uuid.UUID,
    body: EntityRoleUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_org_admin),
):
    """Set or reset one member's role in one company without changing others."""
    actor = tenancy.get_membership(db, user)
    target = db.query(OrgMembership).filter(
        OrgMembership.org_id == actor.org_id,
        OrgMembership.user_id == user_id,
    ).first()
    entity = db.get(Entity, entity_id)
    if target is None or entity is None or entity.org_id != actor.org_id or not entity.is_active:
        raise HTTPException(status_code=404, detail="Member or company not found")
    target_user = db.get(User, user_id)
    if target_user is None or not tenancy.can_access_entity(db, target_user, entity):
        raise HTTPException(status_code=404, detail="Member has no access to this company")
    if user_id == user.id:
        raise HTTPException(status_code=403, detail="You cannot change your own company role")
    previous = tenancy.effective_entity_role(db, target_user, entity)
    next_role = body.role or target.role
    if not invitations.can_grant_role(actor.role, previous) or not invitations.can_grant_role(actor.role, next_role):
        raise HTTPException(status_code=403, detail="You cannot change or grant this role")
    override = db.query(EntityRoleOverride).filter(
        EntityRoleOverride.org_id == actor.org_id,
        EntityRoleOverride.user_id == user_id,
        EntityRoleOverride.entity_id == entity_id,
    ).first()
    if body.role is None or body.role == target.role:
        if override is not None:
            db.delete(override)
    elif override is None:
        db.add(EntityRoleOverride(
            org_id=actor.org_id, user_id=user_id, entity_id=entity_id, role=body.role,
        ))
    else:
        override.role = body.role
    audit.record(
        db, entity_id=entity_id, org_id=actor.org_id, user=user,
        action="member.company_role_updated", object_type="org_membership",
        object_id=str(user_id), summary=f"Company role for {target_user.email}: {previous} → {next_role}",
    )
    db.commit()
    return ok({"user_id": str(user_id), "entity_id": str(entity_id), "role": next_role})


@router.delete("/members/{user_id}")
def remove_member(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_org_admin),
):
    """Remove someone from the organization. Their uploads and audit trail stay."""
    membership = tenancy.get_membership(db, user)
    if membership is None:
        raise HTTPException(status_code=400, detail="No organization for this user")

    target = (
        db.query(OrgMembership)
        .filter(OrgMembership.org_id == membership.org_id, OrgMembership.user_id == user_id)
        .first()
    )
    if target is None:
        raise HTTPException(status_code=404, detail="That person is not a member of this organization")

    target_user = db.get(User, user_id)
    try:
        invitations.remove_member(db, membership=target, actor=user, actor_role=membership.role)
    except invitations.InvitationError as exc:
        raise _guard(exc)

    audit.record(
        db, entity_id=None, org_id=membership.org_id, user=user, action="member.removed",
        object_type="org_membership", object_id=str(user_id),
        summary=f"Removed {getattr(target_user, 'email', user_id)} from the organization",
    )
    db.commit()
    return ok({"removed": True})


# ---------------------------------------------------------------------------
# Invitations — issuing
# ---------------------------------------------------------------------------
@router.get("/invitations")
def list_invitations(
    db: Session = Depends(get_db),
    user: User = Depends(require_org_admin),
):
    membership = tenancy.get_membership(db, user)
    if membership is None:
        return ok([])
    rows = (
        db.query(OrgInvitation)
        .filter(OrgInvitation.org_id == membership.org_id)
        .order_by(OrgInvitation.created_at.desc())
        .all()
    )
    return ok([_invitation_out(r) for r in rows])


@router.post("/invitations")
def create_invitation(
    body: InvitationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_org_admin),
):
    """
    Invite someone in.

    The response carries the token, and it is the only time it will. Only its
    hash is stored, so a database that leaks hands the reader no working
    invitations into anyone's payroll.
    """
    membership = tenancy.get_membership(db, user)
    if membership is None:
        raise HTTPException(status_code=400, detail="No organization for this user")

    try:
        issued = invitations.create(
            db,
            org_id=membership.org_id,
            actor=user,
            actor_role=membership.role,
            email=str(body.email),
            role=body.role,
            entity_ids=[str(e) for e in body.entity_ids],
            note=body.note,
            expiry_days=body.expiry_days,
        )
    except invitations.InvitationError as exc:
        raise _guard(exc)

    scope = (
        f"{len(body.entity_ids)} entities" if body.entity_ids else "every entity"
    )
    audit.record(
        db, entity_id=None, org_id=membership.org_id, user=user, action="member.invited",
        object_type="org_invitation", object_id=str(issued.invitation.id),
        summary=f"Invited {issued.invitation.email} as {body.role} with access to {scope}",
    )
    db.commit()
    db.refresh(issued.invitation)
    return ok(_invitation_out(issued.invitation, issued.token))


@router.post("/invitations/{invitation_id}/resend")
def resend_invitation(
    invitation_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_org_admin),
):
    """
    Issue a fresh token and restart the clock.

    A new token rather than the old one re-sent: the previous value may have
    gone somewhere it should not have, and there is no way to know.
    """
    membership = tenancy.get_membership(db, user)
    invitation = db.get(OrgInvitation, invitation_id)
    if invitation is None or membership is None or invitation.org_id != membership.org_id:
        raise HTTPException(status_code=404, detail="Invitation not found")

    try:
        issued = invitations.resend(db, invitation, actor=user)
    except invitations.InvitationError as exc:
        raise _guard(exc)

    audit.record(
        db, entity_id=None, org_id=invitation.org_id, user=user, action="member.invite_resent",
        object_type="org_invitation", object_id=str(invitation.id),
        summary=f"Reissued the invitation to {invitation.email} with a new token",
    )
    db.commit()
    db.refresh(invitation)
    return ok(_invitation_out(invitation, issued.token))


@router.delete("/invitations/{invitation_id}")
def revoke_invitation(
    invitation_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_org_admin),
):
    membership = tenancy.get_membership(db, user)
    invitation = db.get(OrgInvitation, invitation_id)
    if invitation is None or membership is None or invitation.org_id != membership.org_id:
        raise HTTPException(status_code=404, detail="Invitation not found")

    try:
        invitations.revoke(db, invitation, actor=user)
    except invitations.InvitationError as exc:
        raise _guard(exc)

    audit.record(
        db, entity_id=None, org_id=invitation.org_id, user=user, action="member.invite_revoked",
        object_type="org_invitation", object_id=str(invitation.id),
        summary=f"Revoked the invitation to {invitation.email}",
    )
    db.commit()
    return ok({"revoked": True})


# ---------------------------------------------------------------------------
# Invitations — accepting. Both of these are reachable without a session.
# ---------------------------------------------------------------------------
@router.get("/invitations/lookup")
def preview_invitation(token: str, db: Session = Depends(get_db)):
    """
    What an invitee sees before deciding, and nothing more.

    Every failure returns the same message. Telling apart "no such token" from
    "expired" from "already used" would let someone with a list of guesses learn
    which ones were once real.
    """
    try:
        invitation = invitations.lookup(db, token)
    except invitations.InvitationError as exc:
        raise _guard(exc)

    org = db.get(Organization, invitation.org_id)
    names: list[str] = []
    for raw in invitation.entity_ids or []:
        entity = db.get(Entity, uuid.UUID(str(raw)))
        if entity is not None:
            names.append(entity.name)

    exists = (
        db.query(User).filter(User.email == invitation.email).first() is not None
    )
    return ok({
        "organization": org.name if org else "",
        "role": invitation.role,
        "email": invitation.email,
        "invited_by": invitation.invited_by_email,
        "expires_at": invitation.expires_at.isoformat() if invitation.expires_at else None,
        "entity_names": names,
        "account_exists": exists,
    })


@router.post("/invitations/accept")
def accept_invitation(
    body: InvitationAccept,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Join, as the signed-in account. The account must be the invited address."""
    try:
        invitation = invitations.lookup(db, body.token)
        membership = invitations.accept(db, invitation, user)
    except invitations.InvitationError as exc:
        raise _guard(exc)

    audit.record(
        db, entity_id=None, org_id=membership.org_id, user=user, action="member.joined",
        object_type="org_membership", object_id=str(user.id),
        summary=f"{user.email} accepted an invitation and joined as {membership.role}",
    )
    db.commit()
    org = db.get(Organization, membership.org_id)
    return ok({
        "joined": True,
        "organization": org.name if org else "",
        "role": membership.role,
    })


@router.post("/invitations/register")
def register_from_invitation(
    body: InvitationRegister,
    db: Session = Depends(get_db),
):
    """
    Accept by creating the account the invitation was sent to.

    Deliberately does not take an email: it is read from the invitation, so a
    valid token cannot be used to create an account under some other address.
    Where the address already has an account, the holder signs in and uses
    ``/invitations/accept`` instead — this endpoint will not set a password on
    an account it did not create.
    """
    from app.routers.auth import _issue_tokens

    try:
        invitation = invitations.lookup(db, body.token)
    except invitations.InvitationError as exc:
        raise _guard(exc)

    email = invitations.normalise_email(invitation.email)
    if email == SYSTEM_USER_EMAIL:
        raise HTTPException(status_code=400, detail="Reserved email address")
    if db.query(User).filter(User.email == email).first() is not None:
        raise HTTPException(
            status_code=409,
            detail="An account already exists for this address. Sign in, then open the "
                   "invitation link again to accept it.",
        )

    # A member joining someone else's organization is never a platform admin.
    # That role is granted deliberately, never as a side effect of being invited.
    user = User(email=email, password_hash=hash_password(body.password), role="user")
    db.add(user)
    db.flush()

    try:
        membership = invitations.accept(db, invitation, user)
    except invitations.InvitationError as exc:
        raise _guard(exc)

    audit.record(
        db, entity_id=None, org_id=membership.org_id, user=user, action="member.joined",
        object_type="org_membership", object_id=str(user.id),
        summary=f"{email} created an account from an invitation and joined as {membership.role}",
    )
    db.commit()
    db.refresh(user)
    tokens = _issue_tokens(db, user)
    return ok(tokens.model_dump())


# ---------------------------------------------------------------------------
# Support access — the client's side of it
# ---------------------------------------------------------------------------
class SupportPolicyUpdate(BaseModel):
    policy: Literal["break_glass", "approval_required", "disabled"]


@router.get("/support")
def support_status(
    db: Session = Depends(get_db),
    user: User = Depends(require_org_admin),
):
    """
    Whether platform staff can read this organization's data, and who has.

    Deliberately visible to the client rather than kept in a staff log: a
    support mechanism nobody can audit is a back door.
    """
    membership = tenancy.get_membership(db, user)
    if membership is None:
        raise HTTPException(status_code=400, detail="No organization for this user")

    rows = (
        db.query(SupportAccessGrant)
        .filter(SupportAccessGrant.org_id == membership.org_id)
        .order_by(SupportAccessGrant.requested_at.desc())
        .limit(100)
        .all()
    )
    described = [support_access.describe(g) for g in rows]
    return ok({
        "policy": support_access.policy_for(db, membership.org_id),
        "policies": [
            {"key": "break_glass", "label": "Allow, and tell us",
             "hint": "An engineer can open a time-boxed, read-only session with a stated "
                     "reason. You see it immediately and can revoke it."},
            {"key": "approval_required", "label": "Ask us first",
             "hint": "Nothing opens until an owner here approves it. Safer, and slower "
                     "when you are the one waiting on a fix."},
            {"key": "disabled", "label": "Never",
             "hint": "No support session can be opened. We debug from what you can "
                     "describe and export."},
        ],
        "active": [g for g in described if g["state"] in ("active", "pending")],
        "history": described,
        "always_true": [
            "Read-only — a support session cannot change anything here.",
            "Employee identities are masked, as they are for a viewer.",
            "Every session expires on its own, and you can end one instantly.",
        ],
    })


@router.get("/support/active")
def support_active(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Any open support session, for anyone in the organization.

    Visible to every member rather than owners only: if someone outside your
    company can read your payroll right now, everyone whose payroll it is
    deserves to know, not just whoever can change the setting.
    """
    membership = tenancy.get_membership(db, user)
    if membership is None:
        return ok({"active": []})
    grants = support_access.active_grants_for_org(db, membership.org_id)
    return ok({
        "active": [
            {
                "id": str(g.id),
                "admin_email": g.admin_email,
                "reason": g.reason,
                "state": support_access.effective_state(g),
                "expires_at": g.expires_at.isoformat() if g.expires_at else None,
                "read_only": g.read_only,
                "identity_masked": g.identity_masked,
            }
            for g in grants
        ]
    })


class ApprovalPolicyUpdate(BaseModel):
    signoff_requires_independent_approver: bool | None = None
    matrix_publish_requires_independent_approver: bool | None = None
    studio_publish_requires_independent_approver: bool | None = None
    statutory_publish_requires_independent_approver: bool | None = None
    disbursement_release_requires_independent_approver: bool | None = None
    members_require_mfa: bool | None = None


@router.get("/approval-policy")
def get_approval_policy(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Maker-checker settings. Readable by every member: people should know
    whether their approval has to come from someone else."""
    from app.services import approvals

    membership = tenancy.get_membership(db, user)
    if membership is None:
        raise HTTPException(status_code=400, detail="No organization for this user")
    return ok(approvals.policy_for(db, membership.org_id))


@router.put("/approval-policy")
def set_approval_policy(
    body: ApprovalPolicyUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_org_admin),
):
    """Owners only: deciding who may approve whose work is a governance decision."""
    from app.services import approvals

    membership = tenancy.get_membership(db, user)
    if membership is None or membership.role != "owner":
        raise HTTPException(status_code=403, detail="Only an owner can change approval controls")
    org = db.get(Organization, membership.org_id)
    if body.members_require_mfa and not auth_security.mfa_enabled(user):
        # The owner turning it on must already use it, so the switch can never
        # leave the organisation with nobody able to administer it.
        raise HTTPException(status_code=409, detail="Turn on two-step sign-in for your own account first "
                                                    "(Sign-in & security), then require it of everyone.")
    before = approvals.policy_for(db, org.id)
    after = approvals.set_policy(db, org, body.model_dump(exclude_none=True))
    audit.record(
        db, entity_id=None, org_id=org.id, user=user, action="approval_policy.changed",
        object_type="organization", object_id=str(org.id),
        summary="Approval controls changed: " + ", ".join(
            f"{k.replace('_', ' ')} {'on' if after[k] else 'off'}" for k in after if after[k] != before[k]
        ) or "no change",
        detail={"before": before, "after": after},
    )
    db.commit()
    return ok(after)


@router.put("/support/policy")
def set_support_policy(
    body: SupportPolicyUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_org_admin),
):
    """Change the terms. Switching to 'disabled' closes anything already open."""
    membership = tenancy.get_membership(db, user)
    if membership is None:
        raise HTTPException(status_code=400, detail="No organization for this user")
    org = db.get(Organization, membership.org_id)
    previous = support_access.policy_for(db, membership.org_id)

    try:
        support_access.set_policy(db, org, body.policy)
    except support_access.SupportAccessError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))

    audit.record(
        db, entity_id=None, org_id=org.id, user=user, action="support.policy_changed",
        object_type="organization", object_id=str(org.id),
        summary=f"Support access policy changed from {previous} to {body.policy}",
    )
    db.commit()
    return ok({"policy": body.policy})


@router.post("/support/grants/{grant_id}/approve")
def approve_support_grant(
    grant_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_org_admin),
):
    membership = tenancy.get_membership(db, user)
    grant = db.get(SupportAccessGrant, grant_id)
    if grant is None or membership is None or grant.org_id != membership.org_id:
        raise HTTPException(status_code=404, detail="Support session not found")

    try:
        support_access.approve(db, grant, approver=user)
    except support_access.SupportAccessError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))

    audit.record(
        db, entity_id=None, org_id=grant.org_id, user=user, action="support.approved",
        object_type="support_access_grant", object_id=str(grant.id),
        summary=f"{user.email} approved read-only support access for {grant.admin_email}",
    )
    db.commit()
    db.refresh(grant)
    return ok(support_access.describe(grant))


@router.post("/support/grants/{grant_id}/revoke")
def revoke_support_grant(
    grant_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_org_admin),
):
    """End a support session now. Always available, and never needs a reason."""
    membership = tenancy.get_membership(db, user)
    grant = db.get(SupportAccessGrant, grant_id)
    if grant is None or membership is None or grant.org_id != membership.org_id:
        raise HTTPException(status_code=404, detail="Support session not found")

    support_access.end(
        db, grant, actor_email=user.email, reason="revoked by the organization", revoked=True
    )
    audit.record(
        db, entity_id=None, org_id=grant.org_id, user=user, action="support.revoked",
        object_type="support_access_grant", object_id=str(grant.id),
        summary=f"{user.email} revoked support access held by {grant.admin_email}",
    )
    db.commit()
    db.refresh(grant)
    return ok(support_access.describe(grant))
