"""
Break-glass support access.

A platform administrator deliberately cannot read a client's payroll. This is
the documented way in when a client reports something they cannot reproduce —
and the tests that matter here are the ones proving it stays a support
mechanism rather than becoming a back door.

Four properties, in order of how much damage their absence would do:

**Nothing is implicit.** A platform admin with no grant reads nothing, exactly
as before. Being an admin is not access.

**A session can never write.** Not by a role check — a platform engineer is
usually an owner of their *own* organization, so a role check says yes. Writing
requires a seat in the entity's own organization.

**A session never unmasks.** Identities are masked as they are for a viewer.

**A session is never silent, and never permanent.** It expires on its own, the
client can revoke it instantly, and every open, use and close is written to the
client's own audit trail.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.database import SessionLocal
from app.models import Organization, SupportAccessGrant, User
from app.services import support_access

PASSWORD = "Passw0rd!x"
REASON = "Investigating ticket 412 — cost dashboard shows no June data"


def data(response):
    assert response.status_code == 200, response.text
    return response.json()["data"]


def detail(response) -> str:
    return str(response.json()["error"]["detail"])


def signup(client, email: str, company: str) -> dict:
    r = client.post("/api/auth/signup", json={
        "email": email, "password": PASSWORD, "company_name": company,
    })
    if r.status_code != 200:
        r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['data']['access_token']}"}


def make_platform_admin(email: str) -> None:
    """Promote someone to platform admin, which signup only does for the first user."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).one()
        user.role = "admin"
        db.commit()
    finally:
        db.close()


@pytest.fixture()
def world(client, request):
    """A client organization, and a platform engineer with no access to it."""
    # A hash, not a truncation: several tests here share a long name prefix, and
    # truncating made them collide onto one account — so the second test found a
    # session the first had already opened.
    import hashlib

    slug = hashlib.sha256(request.node.name.encode()).hexdigest()[:12]
    client_headers = signup(client, f"client-{slug}@sup-example.com", f"Client {slug}")
    ctx = data(client.get("/api/org/context", headers=client_headers))

    admin_email = f"engineer-{slug}@sup-example.com"
    admin_headers = signup(client, admin_email, f"Vendor {slug}")
    make_platform_admin(admin_email)
    # Re-issue the token so it carries the new role.
    admin_headers = signup(client, admin_email, "")

    return {
        "client": client_headers,
        "admin": admin_headers,
        "admin_email": admin_email,
        "org_id": ctx["organization"]["id"],
        "entity_id": ctx["active_entity"]["id"],
    }


def open_session(client, world, minutes: int = 60, reason: str = REASON):
    return client.post("/api/admin/support/grants", headers=world["admin"], json={
        "org_id": world["org_id"], "reason": reason, "minutes": minutes,
    })


def as_support(world) -> dict:
    return {**world["admin"], "X-Entity-Id": world["entity_id"]}


# ---------------------------------------------------------------------------
# Nothing is implicit
# ---------------------------------------------------------------------------
def test_a_platform_admin_without_a_grant_reads_nothing(client, world):
    # Being an admin is not access. This is the default the whole feature is
    # built to preserve.
    blocked = client.get("/api/org/context", headers=as_support(world))
    assert blocked.status_code == 404


def test_a_platform_admin_sees_organization_names_but_never_their_data(client, world):
    orgs = data(client.get("/api/admin/support/organizations", headers=world["admin"]))
    assert any(o["id"] == world["org_id"] for o in orgs)
    # Names and policies only — reaching data still needs a grant.
    assert all(set(o) == {"id", "name", "org_type", "support_access_policy"} for o in orgs)


def test_an_ordinary_user_cannot_open_a_session(client, world):
    refused = client.post("/api/admin/support/grants", headers=world["client"], json={
        "org_id": world["org_id"], "reason": REASON,
    })
    assert refused.status_code == 403


# ---------------------------------------------------------------------------
# Opening
# ---------------------------------------------------------------------------
def test_a_reason_is_required_and_a_shrug_is_not_one(client, world):
    refused = open_session(client, world, reason="debug")
    assert refused.status_code == 422 or refused.status_code == 400


def test_a_session_cannot_outlast_its_cap(client, world):
    assert open_session(client, world, minutes=10_000).status_code == 422


def test_opening_a_session_grants_read_access_to_that_organization(client, world):
    grant = data(open_session(client, world))
    assert grant["state"] == "active"
    assert grant["read_only"] is True and grant["identity_masked"] is True

    ctx = data(client.get("/api/org/context", headers=as_support(world)))
    assert ctx["active_entity"]["id"] == world["entity_id"]


def test_a_second_session_on_the_same_organization_is_refused(client, world):
    data(open_session(client, world))
    again = open_session(client, world)
    assert again.status_code == 409


def test_the_grant_reaches_only_the_organization_it_names(client, world):
    # One grant is not a key to the estate.
    other = signup(client, "third-party@sup-example.com", "Third Party Ltd")
    other_entity = data(client.get("/api/org/context", headers=other))["active_entity"]["id"]
    data(open_session(client, world))

    blocked = client.get(
        "/api/org/context", headers={**world["admin"], "X-Entity-Id": other_entity}
    )
    assert blocked.status_code == 404


# ---------------------------------------------------------------------------
# A session can never write
# ---------------------------------------------------------------------------
def test_a_support_session_cannot_upload(client, world):
    import io

    data(open_session(client, world))
    refused = client.post(
        "/api/payroll/upload", headers=as_support(world),
        files={"file": ("r.csv", io.BytesIO(b"employee_id\nE1\n"), "text/csv")},
        data={"meta": "{}"},
    )
    assert refused.status_code == 403
    assert "read-only" in detail(refused).lower()


def test_a_support_session_cannot_approve_even_though_it_owns_its_own_org(client, world):
    """
    The check a role test would get wrong.

    The engineer is an owner of their *own* organization, so ``role_at_least``
    says yes. Writing has to require a seat in the entity's own organization,
    or a support session could approve a JV mapping in someone else's ledger.
    """
    data(open_session(client, world))
    created = client.post("/api/reconciliation/jv/templates", headers=as_support(world), json={
        "name": "Sneaky", "from_preset": "standard_accrual",
    })
    assert created.status_code == 403
    assert "read-only" in detail(created).lower()


def test_a_support_session_cannot_change_the_support_policy(client, world):
    data(open_session(client, world))
    # require_org_admin reads their own organization, so this edits nothing of
    # the client's — but it must not appear to succeed against theirs either.
    changed = client.put(
        "/api/org/support/policy", headers=as_support(world), json={"policy": "disabled"}
    )
    if changed.status_code == 200:
        assert data(client.get("/api/org/support", headers=world["client"]))["policy"] != "disabled"


def test_a_support_session_cannot_invite_itself_deeper(client, world):
    data(open_session(client, world))
    refused = client.post("/api/org/invitations", headers=as_support(world), json={
        "email": "backdoor@sup-example.com", "role": "owner",
    })
    # Either refused outright, or landed in their own organization — never the
    # client's.
    if refused.status_code == 200:
        theirs = data(client.get("/api/org/invitations", headers=world["client"]))
        assert all(i["email"] != "backdoor@sup-example.com" for i in theirs)


# ---------------------------------------------------------------------------
# A session never unmasks
# ---------------------------------------------------------------------------
def test_identities_are_masked_for_a_support_session(client, world):
    data(open_session(client, world))
    db = SessionLocal()
    try:
        from app.deps import get_identity
        from app.models import Entity

        entity = db.get(Entity, uuid.UUID(world["entity_id"]))
        admin = db.query(User).filter(User.email == world["admin_email"]).one()
        identity = get_identity(None, db, admin, entity)
        assert identity.masked is True
        assert "support" in identity.reason.lower()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Never silent, never permanent
# ---------------------------------------------------------------------------
def test_an_expired_session_stops_working_without_a_sweeper(client, world):
    grant = data(open_session(client, world))
    assert client.get("/api/org/context", headers=as_support(world)).status_code == 200

    db = SessionLocal()
    try:
        row = db.get(SupportAccessGrant, uuid.UUID(grant["id"]))
        row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        db.commit()
    finally:
        db.close()

    assert client.get("/api/org/context", headers=as_support(world)).status_code == 404


def test_the_client_can_revoke_instantly(client, world):
    grant = data(open_session(client, world))
    assert client.get("/api/org/context", headers=as_support(world)).status_code == 200

    revoked = data(client.post(
        f"/api/org/support/grants/{grant['id']}/revoke", headers=world["client"]
    ))
    assert revoked["state"] == "revoked"
    assert client.get("/api/org/context", headers=as_support(world)).status_code == 404


def test_the_engineer_can_end_their_own_session(client, world):
    grant = data(open_session(client, world))
    ended = data(client.post(
        f"/api/admin/support/grants/{grant['id']}/end", headers=world["admin"],
        json={"reason": "fixed, ticket closed"},
    ))
    assert ended["state"] == "ended"
    assert client.get("/api/org/context", headers=as_support(world)).status_code == 404


def test_use_is_counted_so_an_unused_session_is_distinguishable(client, world):
    # "Opened and never used" and "read the whole book" are different facts,
    # and the client is entitled to tell them apart.
    grant = data(open_session(client, world))
    status = data(client.get("/api/org/support", headers=world["client"]))
    assert status["active"][0]["use_count"] == 0

    client.get("/api/org/context", headers=as_support(world))
    client.get("/api/org/context", headers=as_support(world))

    status = data(client.get("/api/org/support", headers=world["client"]))
    assert status["active"][0]["use_count"] >= 2
    assert status["active"][0]["last_used_at"] is not None
    del grant


def test_the_client_sees_the_session_in_their_own_audit_trail(client, world):
    data(open_session(client, world))
    events = data(client.get("/api/audit?limit=50", headers=world["client"]))["events"]
    opened = next(e for e in events if e["action"] == "support.opened")
    assert world["admin_email"] in opened["summary"]
    assert "Investigating ticket 412" in opened["summary"]


def test_ending_and_revoking_are_recorded_as_different_things(client, world):
    grant = data(open_session(client, world))
    client.post(f"/api/org/support/grants/{grant['id']}/revoke", headers=world["client"])
    actions = {
        e["action"] for e in data(client.get("/api/audit?limit=50", headers=world["client"]))["events"]
    }
    assert "support.revoked" in actions and "support.ended" not in actions


# ---------------------------------------------------------------------------
# The client owns the terms
# ---------------------------------------------------------------------------
def test_the_default_policy_is_break_glass_and_is_stated(client, world):
    status = data(client.get("/api/org/support", headers=world["client"]))
    assert status["policy"] == "break_glass"
    assert len(status["policies"]) == 3
    assert all(p["hint"] for p in status["policies"])
    assert len(status["always_true"]) == 3


def test_a_client_can_refuse_support_access_entirely(client, world):
    data(client.put("/api/org/support/policy", headers=world["client"],
                    json={"policy": "disabled"}))
    refused = open_session(client, world)
    assert refused.status_code == 403
    assert "turned support access off" in detail(refused)


def test_disabling_closes_a_session_that_is_already_open(client, world):
    # A policy that only applied to future sessions would not be the switch it
    # appears to be.
    data(open_session(client, world))
    assert client.get("/api/org/context", headers=as_support(world)).status_code == 200

    data(client.put("/api/org/support/policy", headers=world["client"],
                    json={"policy": "disabled"}))
    assert client.get("/api/org/context", headers=as_support(world)).status_code == 404


def test_approval_required_holds_the_session_until_the_client_says_yes(client, world):
    data(client.put("/api/org/support/policy", headers=world["client"],
                    json={"policy": "approval_required"}))

    grant = data(open_session(client, world))
    assert grant["state"] == "pending"
    assert client.get("/api/org/context", headers=as_support(world)).status_code == 404

    approved = data(client.post(
        f"/api/org/support/grants/{grant['id']}/approve", headers=world["client"]
    ))
    assert approved["state"] == "active"
    assert approved["approved_by"] is not None
    assert client.get("/api/org/context", headers=as_support(world)).status_code == 200


def test_the_policy_in_force_is_copied_onto_the_grant(client, world):
    # A client who switches policy next month has not changed what this grant
    # was, so the record keeps its own copy.
    grant = data(open_session(client, world))
    assert grant["policy_at_grant"] == "break_glass"
    data(client.put("/api/org/support/policy", headers=world["client"],
                    json={"policy": "approval_required"}))
    history = data(client.get("/api/org/support", headers=world["client"]))["history"]
    assert next(g for g in history if g["id"] == grant["id"])["policy_at_grant"] == "break_glass"


def test_losing_the_platform_role_ends_access_without_anyone_revoking(client, world):
    # A grant held by someone who is no longer staff must stop working the
    # moment their role changes.
    data(open_session(client, world))
    assert client.get("/api/org/context", headers=as_support(world)).status_code == 200

    db = SessionLocal()
    try:
        db.query(User).filter(User.email == world["admin_email"]).one().role = "user"
        db.commit()
    finally:
        db.close()

    assert client.get("/api/org/context", headers=as_support(world)).status_code == 404


def test_one_organization_never_sees_another_s_support_history(client, world):
    data(open_session(client, world))
    other = signup(client, "nosy@sup-example.com", "Nosy Ltd")
    assert data(client.get("/api/org/support", headers=other))["history"] == []


# ---------------------------------------------------------------------------
# The service's own guards
# ---------------------------------------------------------------------------
def test_expiry_is_derived_rather_than_stored():
    grant = SupportAccessGrant(
        org_id=uuid.uuid4(), admin_user_id=uuid.uuid4(), reason=REASON,
        state="active", expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    assert support_access.is_expired(grant) is True
    assert support_access.effective_state(grant) == "expired"
    assert grant.state == "active"  # the stored value is untouched


def test_a_short_reason_is_refused_at_the_service_level():
    db = SessionLocal()
    try:
        org = db.query(Organization).first()
        user = User(id=uuid.uuid4(), email="x@sup-example.com", role="admin")
        with pytest.raises(support_access.SupportAccessError) as exc:
            support_access.open_grant(db, org_id=org.id, admin=user, reason="hmm")
        assert "at least" in str(exc.value)
    finally:
        db.rollback()
        db.close()


# ---------------------------------------------------------------------------
# The account list obeys the same boundary as everything else
# ---------------------------------------------------------------------------
def test_the_account_list_does_not_hand_over_every_clients_people(client, world):
    """
    A platform admin with no grant sees their own organization's accounts only.

    This endpoint used to return every user on the installation. It is the same
    standing visibility break-glass exists to prevent — a staff list is who a
    client employs, and enumerating it needed no grant, left no audit row and
    never expired.
    """
    rows = data(client.get("/api/admin/users", headers=world["admin"]))
    emails = {r["email"] for r in rows}

    assert world["admin_email"] in emails, "an admin should still see their own organization"
    assert not any(e.startswith("client-") for e in emails), (
        "the client's accounts were listed to a platform admin holding no grant"
    )


def test_a_grant_opens_the_account_list_and_says_so_in_the_clients_trail(client, world):
    assert open_session(client, world).status_code == 200

    rows = data(client.get("/api/admin/users", headers=world["admin"]))
    emails = {r["email"] for r in rows}
    assert any(e.startswith("client-") for e in emails), (
        "a live grant should bring the client's accounts into view"
    )

    # And the client can see that it happened, in their own audit trail.
    trail = data(client.get("/api/audit", headers=world["client"]))
    events = trail["events"] if isinstance(trail, dict) else trail
    assert any(
        e.get("action") == "support.read" and e.get("object_type") == "org_members"
        for e in events
    ), "the read was not recorded where the client would look for it"


def test_support_access_cannot_promote_a_clients_user(client, world):
    """A grant is read-only. Roles are not in reach through it."""
    assert open_session(client, world).status_code == 200

    rows = data(client.get("/api/admin/users", headers=world["admin"]))
    target = next(r for r in rows if r["email"].startswith("client-"))

    refused = client.patch(
        f"/api/admin/users/{target['id']}/role",
        headers=world["admin"],
        json={"role": "admin"},
    )
    assert refused.status_code == 404, refused.text
