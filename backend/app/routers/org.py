"""
Organization and entity management.

``GET /api/org/context`` is the endpoint the frontend calls on boot: it returns
the organization, the caller's role, and the entities they may open, so the
entity switcher can render without a second round trip.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import (
    SYSTEM_USER_EMAIL,
    get_current_entity,
    get_current_user,
    require_org_admin,
)
from app.envelope import ok
from app.models import Entity, OrgInvitation, OrgMembership, Organization, User
from app.schemas.org import (
    ContextOut,
    EntityCreate,
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
from app.services import audit, invitations, tenancy

router = APIRouter()


@router.get("/context")
def get_context(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    membership = tenancy.get_membership(db, user)
    org = db.get(Organization, membership.org_id) if membership else None
    entities = tenancy.accessible_entities(db, user)
    payload = ContextOut(
        organization=OrganizationOut.model_validate(org) if org else None,
        role=membership.role if membership else None,
        active_entity=EntityOut.model_validate(entity),
        entities=[EntityOut.model_validate(e) for e in entities],
    )
    return ok(payload.model_dump(mode="json"))


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


def _member_out(membership: OrgMembership, email: str | None, scoped: list[str], you: bool) -> dict:
    return {
        "id": str(membership.id),
        "user_id": str(membership.user_id),
        "email": email,
        "role": membership.role,
        "entity_ids": scoped,
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
    return ok(_member_out(target, getattr(target_user, "email", None), scoped,
                          target.user_id == user.id))


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
