"""The denials, not the approvals.

`test_portal_auth.py` proves the portal split works when everyone behaves. This
proves it holds when they do not, which is the half that protects a client's
payroll from another client and from platform staff.

Every check here lives behind `settings.is_production` in `app/deps.py`, so the
rest of the suite — which runs with `env=dev` — never reaches it. Coverage of
`deps.py` put six of these denials at zero: the raises existed and nothing had
ever made one fire. A security control nobody has watched fail is a control
nobody knows works.
"""
from __future__ import annotations

import uuid

import pytest

from app.config import settings
from app.database import SessionLocal
from app.models import Entity, Organization, User
from app.security import create_access_token, hash_password

PASSWORD = "Passw0rd!x"


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def production(monkeypatch):
    """Run as the deployed API does: production, and no anonymous fallback."""
    monkeypatch.setattr(settings, "env", "production")
    monkeypatch.setattr(settings, "allow_anonymous_api", False)
    monkeypatch.setattr(settings, "allow_public_signup", False)


@pytest.fixture()
def workspace(client, request):
    """A signed-up client organisation, created before production is switched on."""
    email = f"pd-{abs(hash(request.node.name)) % 10**8}@denials-example.com"
    created = client.post("/api/auth/signup", json={
        "email": email, "password": PASSWORD, "company_name": "Denials Ltd"})
    assert created.status_code == 200, created.text
    token = created.json()["data"]["access_token"]
    context = client.get("/api/org/context", headers=bearer(token)).json()["data"]
    with SessionLocal() as db:
        user = db.query(User).filter(User.email == email).one()
        return {
            "email": email,
            "user_id": user.id,
            "org_id": uuid.UUID(context["organization"]["id"]),
            "slug": context["organization"]["slug"],
        }


# ---------------------------------------------------------------------------
def test_a_token_minted_before_the_portal_split_is_refused(client, workspace, production):
    """deps.py line 64. A token with no `portal` claim predates the split.

    It has no workspace bound to it, so honouring it would be honouring a
    session from before the rules existed. The user is asked to sign in again.
    """
    legacy = create_access_token(str(workspace["user_id"]))  # no portal, no org_id
    response = client.get("/api/org/context", headers=bearer(legacy))
    assert response.status_code == 401, response.text
    assert "sign in again" in response.json()["error"]["detail"].lower()


def test_a_client_token_stops_working_when_the_membership_is_gone(client, workspace, production):
    """deps.py line 68. Removing someone from an organisation must end their session.

    Otherwise a revoked user keeps reading payroll until their token expires.
    """
    token = create_access_token(
        str(workspace["user_id"]),
        {"portal": "client", "org_id": str(workspace["org_id"])},
    )
    assert client.get("/api/org/context", headers=bearer(token)).status_code == 200

    from app.models import OrgMembership
    with SessionLocal() as db:
        db.query(OrgMembership).filter(
            OrgMembership.user_id == workspace["user_id"]).delete()
        db.commit()

    response = client.get("/api/org/context", headers=bearer(token))
    assert response.status_code == 401, response.text
    assert "revoked" in response.json()["error"]["detail"].lower()


def test_a_client_token_naming_another_organisation_is_refused(client, workspace, production):
    """deps.py line 68 again, from the other direction: the claim must match reality."""
    token = create_access_token(
        str(workspace["user_id"]),
        {"portal": "client", "org_id": str(uuid.uuid4())},
    )
    assert client.get("/api/org/context", headers=bearer(token)).status_code == 401


def test_a_support_token_with_an_unreadable_org_is_refused(client, workspace, production):
    """deps.py line 74. A malformed claim is rejected, not coerced into something."""
    token = create_access_token(
        str(workspace["user_id"]), {"portal": "support", "org_id": "not-a-uuid"})
    response = client.get("/api/org/context", headers=bearer(token))
    assert response.status_code == 401, response.text
    assert "support session" in response.json()["error"]["detail"].lower()


def test_a_support_token_without_a_live_grant_is_refused(client, workspace, production):
    """deps.py line 76. The grant is the authority; the token alone is not.

    This is what makes a support session expire on time rather than lasting as
    long as its token.
    """
    token = create_access_token(
        str(workspace["user_id"]),
        {"portal": "support", "org_id": str(workspace["org_id"])},
    )
    response = client.get("/api/org/context", headers=bearer(token))
    assert response.status_code == 401, response.text
    assert "support access ended" in response.json()["error"]["detail"].lower()


def test_a_client_token_cannot_reach_another_organisations_entity(client, workspace, production):
    """An entity belonging to someone else reads as absent, not as forbidden.

    Confirming an id exists is itself a disclosure, so the answer is 404 either
    way. This is stopped by ``tenancy.can_access_entity`` before the scoping
    check below ever sees it — two independent refusals, which is the point.
    """
    with SessionLocal() as db:
        other_org = Organization(name="Somebody Else Ltd")
        db.add(other_org)
        db.flush()
        other_entity = Entity(org_id=other_org.id, name="Their Company", code="THEIRS")
        db.add(other_entity)
        db.commit()
        other_entity_id = other_entity.id

    token = create_access_token(
        str(workspace["user_id"]),
        {"portal": "client", "org_id": str(workspace["org_id"])},
    )
    response = client.get(
        "/api/payroll/runs",
        headers={**bearer(token), "X-Entity-Id": str(other_entity_id)},
    )
    assert response.status_code == 404, response.text
    assert "not found" in response.json()["error"]["detail"].lower()


def test_a_support_session_is_confined_to_the_organisation_it_was_opened_for(
    client, workspace, production
):
    """deps.py line 138, reached for real.

    A staff member may hold grants on two clients at once. Each support session
    is opened against one of them, and the token says which. Holding a grant on
    the other must not let this session read it — otherwise "I opened a session
    for Acme" quietly means "and for everyone else I support".

    The entity is reachable (the grant makes ``can_access_entity`` true), so the
    earlier refusal does not fire and the scoping check is what stops it.
    """
    from app.models import SupportAccessGrant
    from datetime import UTC, datetime, timedelta

    with SessionLocal() as db:
        staff = User(
            email="two-grants@denials-example.com",
            password_hash=hash_password(PASSWORD),
            role="user",
            platform_role="support",
        )
        db.add(staff)

        other_org = Organization(name="Second Client Ltd")
        db.add(other_org)
        db.flush()
        other_entity = Entity(org_id=other_org.id, name="Second Client", code="SECOND")
        db.add(other_entity)
        db.flush()

        # Live grants on both organisations.
        for org_id in (workspace["org_id"], other_org.id):
            db.add(SupportAccessGrant(
                org_id=org_id,
                admin_user_id=staff.id,
                admin_email=staff.email,
                reason="investigating a reported discrepancy",
                expires_at=datetime.now(UTC) + timedelta(minutes=30),
            ))
        db.commit()
        staff_id, other_entity_id = staff.id, other_entity.id

    # A session opened for the *first* organisation.
    token = create_access_token(
        str(staff_id), {"portal": "support", "org_id": str(workspace["org_id"])})

    response = client.get(
        "/api/payroll/runs",
        headers={**bearer(token), "X-Entity-Id": str(other_entity_id)},
    )
    assert response.status_code == 404, (
        "a support session scoped to one organisation reached another it also "
        f"holds a grant on: {response.text}")


def test_a_member_of_an_organisation_with_no_company_is_refused_not_provisioned(
    client, production
):
    """deps.py line 163. Development invents a workspace on the spot; production must not.

    The member is real and their token is honest — their organisation simply
    has no company in it yet. Development provisions one to keep old accounts
    working; doing that in production would create a tenant nobody asked for,
    inside a product whose whole job is keeping tenants apart.
    """
    from app.models import OrgMembership

    with SessionLocal() as db:
        empty_org = Organization(name="Empty Org Ltd")
        db.add(empty_org)
        db.flush()
        member = User(
            email="no-company@denials-example.com",
            password_hash=hash_password(PASSWORD),
            role="user",
        )
        db.add(member)
        db.flush()
        db.add(OrgMembership(org_id=empty_org.id, user_id=member.id, role="owner"))
        db.commit()
        member_id, empty_org_id = member.id, empty_org.id

    token = create_access_token(
        str(member_id), {"portal": "client", "org_id": str(empty_org_id)})
    response = client.get("/api/payroll/runs", headers=bearer(token))
    assert response.status_code == 403, response.text
    assert "workspace membership" in response.json()["error"]["detail"].lower()


def test_a_platform_session_cannot_open_a_client_company(client, workspace, production):
    """deps.py line 135. Platform staff sign in to run the platform, not to read payroll.

    ``/api/admin/*`` is theirs; anything that resolves a company is not. Without
    this a platform token would fall through to whatever entity the user happens
    to belong to, which is precisely the separation the two front doors exist for.
    """
    with SessionLocal() as db:
        staff = User(
            email="platform-only@denials-example.com",
            password_hash=hash_password(PASSWORD),
            role="user",
            platform_role="admin",
        )
        db.add(staff)
        db.commit()
        staff_id = staff.id

    token = create_access_token(str(staff_id), {"portal": "platform", "org_id": None})
    response = client.get("/api/payroll/runs", headers=bearer(token))
    assert response.status_code == 403, response.text
    assert "client workspace session" in response.json()["error"]["detail"].lower()


def test_a_client_token_with_no_workspace_claim_is_refused(client, workspace, production):
    """A client session must say which workspace it is for.

    A token carrying ``portal: client`` but no ``org_id`` is unscoped, and an
    unscoped session in a multi-tenant product is the one shape that must never
    be honoured — it would resolve to whichever company happened to come first.

    The membership check catches it first, because a real membership can never
    equal a missing claim, so the message speaks of revoked access rather than
    a missing workspace. The later scoping check would refuse it too; both are
    kept, and this asserts the refusal rather than which line produces it.
    """
    token = create_access_token(
        str(workspace["user_id"]), {"portal": "client", "org_id": None})
    response = client.get("/api/payroll/runs", headers=bearer(token))
    assert response.status_code == 401, response.text
    assert "revoked" in response.json()["error"]["detail"].lower()
