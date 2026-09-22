"""
Inviting people into an organization, and managing them once they are in.

Every rule tested here exists because the obvious implementation without it
either hands someone access to a month of salary data they should not have, or
locks an organization out of its own account.

The two properties that matter most:

**A token is not an identity.** Acceptance requires the invited address, so a
link that leaks — forwarded, left in a mailbox, pasted into a ticket — is worth
nothing to anyone who is not that person.

**An organization can always be administered.** The last owner cannot be
demoted or removed, and nobody can change their own role, because neither
direction is recoverable from inside the product.
"""
from __future__ import annotations

import uuid

import pytest

from app.database import SessionLocal
from app.models import OrgInvitation, OrgMembership, User
from app.security import token_fingerprint
from app.services import invitations

PASSWORD = "Passw0rd!x"


def data(response):
    assert response.status_code == 200, response.text
    return response.json()["data"]


def detail(response) -> str:
    return str(response.json()["error"]["detail"])


def signup(client, email: str, company: str = "Invite Tests") -> dict:
    r = client.post("/api/auth/signup", json={
        "email": email, "password": PASSWORD, "company_name": company,
    })
    if r.status_code != 200:
        r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['data']['access_token']}"}


@pytest.fixture()
def owner(client, request):
    """An organization with one owner — what signup produces."""
    email = f"owner-{request.node.name[:34]}@invite-example.com".replace("_", "-")
    return signup(client, email, f"Org {request.node.name[:20]}"), email


def invite(client, headers, email: str, role: str = "analyst", **kw) -> dict:
    body = {"email": email, "role": role, **kw}
    return client.post("/api/org/invitations", headers=headers, json=body)


# ---------------------------------------------------------------------------
# The token
# ---------------------------------------------------------------------------
def test_the_token_is_returned_once_and_only_its_hash_is_stored(client, owner):
    headers, _ = owner
    issued = data(invite(client, headers, "new-hire@invite-example.com"))
    token = issued["token"]
    assert token and len(token) > 30

    db = SessionLocal()
    try:
        row = db.get(OrgInvitation, uuid.UUID(issued["id"]))
        # The raw value must not be recoverable from the database.
        assert token not in str(row.__dict__)
        assert row.token_hash == token_fingerprint(token)
    finally:
        db.close()

    # And no read-back endpoint hands it out again.
    listed = data(client.get("/api/org/invitations", headers=headers))
    assert all("token" not in item for item in listed)


def test_every_bad_token_gives_the_same_answer(client, owner):
    headers, _ = owner
    issued = data(invite(client, headers, "gone@invite-example.com"))
    client.delete(f"/api/org/invitations/{issued['id']}", headers=headers)

    # Revoked, and never-existed, must be indistinguishable — otherwise a list
    # of guesses reveals which ones were once real.
    revoked = client.get(f"/api/org/invitations/lookup?token={issued['token']}")
    nonsense = client.get("/api/org/invitations/lookup?token=not-a-real-token-at-all")
    assert revoked.status_code == nonsense.status_code == 404
    assert detail(revoked) == detail(nonsense)


def test_an_expired_invitation_stops_working_without_a_sweeper(client, owner):
    from datetime import UTC, datetime, timedelta

    headers, _ = owner
    issued = data(invite(client, headers, "late@invite-example.com"))

    db = SessionLocal()
    try:
        row = db.get(OrgInvitation, uuid.UUID(issued["id"]))
        row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        db.commit()
    finally:
        db.close()

    assert client.get(
        f"/api/org/invitations/lookup?token={issued['token']}"
    ).status_code == 404
    listed = data(client.get("/api/org/invitations", headers=headers))
    assert next(i for i in listed if i["id"] == issued["id"])["state"] == "expired"


def test_resending_issues_a_new_token_and_retires_the_old_one(client, owner):
    headers, _ = owner
    first = data(invite(client, headers, "resend@invite-example.com"))
    second = data(client.post(
        f"/api/org/invitations/{first['id']}/resend", headers=headers
    ))
    assert second["token"] != first["token"]
    assert client.get(f"/api/org/invitations/lookup?token={first['token']}").status_code == 404
    assert client.get(f"/api/org/invitations/lookup?token={second['token']}").status_code == 200


def test_re_inviting_the_same_address_supersedes_the_first(client, owner):
    # Two live tokens for one seat is one more than anybody intended.
    headers, _ = owner
    first = data(invite(client, headers, "twice@invite-example.com"))
    second = data(invite(client, headers, "twice@invite-example.com", role="viewer"))
    assert client.get(f"/api/org/invitations/lookup?token={first['token']}").status_code == 404
    assert client.get(f"/api/org/invitations/lookup?token={second['token']}").status_code == 200


# ---------------------------------------------------------------------------
# Who may invite whom
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "actor,target,allowed",
    [
        ("owner", "owner", True), ("owner", "viewer", True),
        ("manager", "owner", False), ("manager", "manager", True),
        ("manager", "analyst", True), ("analyst", "owner", False),
    ],
)
def test_nobody_can_grant_a_role_wider_than_their_own(actor, target, allowed):
    assert invitations.can_grant_role(actor, target) is allowed


def test_a_manager_cannot_mint_an_owner(client, owner):
    # Otherwise the ladder is decorative: anyone who can invite can promote
    # themselves by inviting a second account.
    headers, _ = owner
    manager_email = "mgr@invite-example.com"
    issued = data(invite(client, headers, manager_email, role="manager"))
    mgr_headers = accept_as_new_user(client, issued["token"])

    refused = invite(client, mgr_headers, "sneaky@invite-example.com", role="owner")
    assert refused.status_code == 403
    assert "cannot invite someone as owner" in detail(refused)


def test_an_analyst_cannot_invite_at_all(client, owner):
    headers, _ = owner
    issued = data(invite(client, headers, "analyst@invite-example.com", role="analyst"))
    analyst_headers = accept_as_new_user(client, issued["token"])
    assert invite(client, analyst_headers, "x@invite-example.com").status_code == 403


# ---------------------------------------------------------------------------
# Accepting
# ---------------------------------------------------------------------------
def accept_as_new_user(client, token: str) -> dict:
    """Create the invited account and return its auth header."""
    r = client.post("/api/org/invitations/register", json={"token": token, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['data']['access_token']}"}


def test_a_new_member_can_register_from_the_link_and_lands_in_the_org(client, owner):
    headers, owner_email = owner
    issued = data(invite(client, headers, "joiner@invite-example.com", role="analyst"))

    preview = data(client.get(f"/api/org/invitations/lookup?token={issued['token']}"))
    assert preview["email"] == "joiner@invite-example.com"
    assert preview["role"] == "analyst"
    assert preview["invited_by"] == owner_email
    assert preview["account_exists"] is False

    joiner = accept_as_new_user(client, issued["token"])
    context = data(client.get("/api/org/context", headers=joiner))
    assert context["role"] == "analyst"
    assert context["active_entity"] is not None

    members = data(client.get("/api/org/members", headers=headers))
    assert {m["email"] for m in members} == {owner_email, "joiner@invite-example.com"}


def test_the_link_cannot_be_used_by_a_different_account(client, owner):
    # The whole point: a token is not an identity. A forwarded link is worth
    # nothing to anyone who is not the invited address.
    headers, _ = owner
    issued = data(invite(client, headers, "intended@invite-example.com"))
    stranger = signup(client, "stranger@invite-example.com", "Stranger Co")

    refused = client.post(
        "/api/org/invitations/accept", headers=stranger, json={"token": issued["token"]}
    )
    assert refused.status_code == 403
    assert "different email address" in detail(refused)


def test_registering_cannot_choose_its_own_email(client, owner):
    # The address comes from the invitation, never the request body, so a valid
    # token cannot be spent creating an account under some other address.
    headers, _ = owner
    issued = data(invite(client, headers, "fixed@invite-example.com"))
    r = client.post("/api/org/invitations/register", json={
        "token": issued["token"], "password": PASSWORD,
        "email": "attacker@invite-example.com",
    })
    assert r.status_code == 200
    db = SessionLocal()
    try:
        assert db.query(User).filter(User.email == "attacker@invite-example.com").first() is None
        assert db.query(User).filter(User.email == "fixed@invite-example.com").first() is not None
    finally:
        db.close()


def test_inviting_someone_who_already_belongs_elsewhere_is_refused_upfront(client, owner):
    headers, _ = owner
    signup(client, "taken@invite-example.com", "Their Own Co")
    refused = invite(client, headers, "taken@invite-example.com")
    assert refused.status_code == 409
    assert "another organization" in detail(refused)


def test_registering_will_not_set_a_password_on_an_existing_account(client, owner):
    """
    The race the invite-time check cannot cover.

    They are invited before they have an account, sign up independently, and
    then open the link. Without this guard a valid token would set a password
    on an account it did not create — an invitation to a known address would be
    an account takeover.
    """
    headers, _ = owner
    issued = data(invite(client, headers, "racer@invite-example.com"))
    signup(client, "racer@invite-example.com", "Their Own Co")

    refused = client.post("/api/org/invitations/register", json={
        "token": issued["token"], "password": "Different-Pwd-9",
    })
    assert refused.status_code == 409
    assert "Sign in" in detail(refused)


def test_a_joiner_is_never_made_a_platform_admin(client, owner):
    headers, _ = owner
    issued = data(invite(client, headers, "notadmin@invite-example.com"))
    accept_as_new_user(client, issued["token"])
    db = SessionLocal()
    try:
        assert db.query(User).filter(
            User.email == "notadmin@invite-example.com"
        ).one().role == "user"
    finally:
        db.close()


def test_accepting_while_belonging_elsewhere_is_refused_clearly(client, owner):
    # The same race, on the accept path. Silently moving them would take their
    # existing employer's data out from under them.
    headers, _ = owner
    issued = data(invite(client, headers, "elsewhere@invite-example.com"))
    other = signup(client, "elsewhere@invite-example.com", "Elsewhere Ltd")

    refused = client.post(
        "/api/org/invitations/accept", headers=other, json={"token": issued["token"]}
    )
    assert refused.status_code == 409
    assert "one organization at a time" in detail(refused)


def test_inviting_an_existing_member_is_refused(client, owner):
    headers, _ = owner
    issued = data(invite(client, headers, "dup@invite-example.com"))
    accept_as_new_user(client, issued["token"])
    again = invite(client, headers, "dup@invite-example.com")
    assert again.status_code == 409
    assert "already a member" in detail(again)


def test_an_accepted_invitation_cannot_be_used_twice(client, owner):
    headers, _ = owner
    issued = data(invite(client, headers, "once@invite-example.com"))
    accept_as_new_user(client, issued["token"])
    assert client.get(f"/api/org/invitations/lookup?token={issued['token']}").status_code == 404


# ---------------------------------------------------------------------------
# Entity scoping
# ---------------------------------------------------------------------------
def test_an_invitation_can_narrow_a_member_to_named_entities(client, owner):
    headers, _ = owner
    second = data(client.post("/api/org/entities", headers=headers, json={"name": "Client B"}))
    third = data(client.post("/api/org/entities", headers=headers, json={"name": "Client C"}))

    issued = data(invite(
        client, headers, "scoped@invite-example.com", role="analyst",
        entity_ids=[second["id"]],
    ))
    preview = data(client.get(f"/api/org/invitations/lookup?token={issued['token']}"))
    assert preview["entity_names"] == ["Client B"]

    scoped = accept_as_new_user(client, issued["token"])
    visible = data(client.get("/api/org/entities", headers=scoped))
    assert [e["id"] for e in visible] == [second["id"]]

    # And the entity they were not given is not merely hidden — it is refused,
    # with the same answer as an entity that does not exist.
    blocked = client.get("/api/org/context", headers={**scoped, "X-Entity-Id": third["id"]})
    assert blocked.status_code == 404


def test_an_entity_from_another_organization_cannot_be_granted(client, owner):
    headers, _ = owner
    stranger = signup(client, "other-org@invite-example.com", "Other Org")
    theirs = data(client.get("/api/org/entities", headers=stranger))[0]

    refused = invite(client, headers, "x@invite-example.com", entity_ids=[theirs["id"]])
    assert refused.status_code == 404


def test_no_scoping_means_the_whole_organization(client, owner):
    headers, _ = owner
    data(client.post("/api/org/entities", headers=headers, json={"name": "Client D"}))
    issued = data(invite(client, headers, "wide@invite-example.com"))
    wide = accept_as_new_user(client, issued["token"])
    assert len(data(client.get("/api/org/entities", headers=wide))) == 2


# ---------------------------------------------------------------------------
# Managing members
# ---------------------------------------------------------------------------
def test_an_owner_can_change_a_member_s_role(client, owner):
    headers, _ = owner
    issued = data(invite(client, headers, "promote@invite-example.com", role="viewer"))
    member = accept_as_new_user(client, issued["token"])
    user_id = data(client.get("/api/org/members", headers=headers))
    target = next(m for m in user_id if m["email"] == "promote@invite-example.com")

    updated = data(client.patch(
        f"/api/org/members/{target['user_id']}", headers=headers, json={"role": "manager"}
    ))
    assert updated["role"] == "manager"
    assert data(client.get("/api/org/context", headers=member))["role"] == "manager"


def test_entity_access_can_be_changed_after_joining(client, owner):
    headers, _ = owner
    second = data(client.post("/api/org/entities", headers=headers, json={"name": "Client E"}))
    issued = data(invite(client, headers, "rescope@invite-example.com"))
    member = accept_as_new_user(client, issued["token"])
    target = next(
        m for m in data(client.get("/api/org/members", headers=headers))
        if m["email"] == "rescope@invite-example.com"
    )

    data(client.patch(f"/api/org/members/{target['user_id']}", headers=headers,
                      json={"entity_ids": [second["id"]]}))
    assert [e["id"] for e in data(client.get("/api/org/entities", headers=member))] == [second["id"]]

    # An empty list widens them again rather than meaning "no change".
    data(client.patch(f"/api/org/members/{target['user_id']}", headers=headers,
                      json={"entity_ids": []}))
    assert len(data(client.get("/api/org/entities", headers=member))) == 2


def test_a_sole_owner_cannot_be_unseated_by_anyone(client, owner):
    """
    An organization always keeps someone who can administer it.

    Three routes to an ownerless organization, all closed: a manager is refused
    by rank, the owner is refused from acting on themselves, and — the guard
    below this test covers it — an owner demoting the last owner.
    """
    headers, _ = owner
    mgr = accept_as_new_user(
        client, data(invite(client, headers, "m9@invite-example.com", role="manager"))["token"]
    )
    sole = next(m for m in data(client.get("/api/org/members", headers=headers)) if m["is_you"])

    assert client.patch(
        f"/api/org/members/{sole['user_id']}", headers=mgr, json={"role": "viewer"}
    ).status_code == 403
    assert client.delete(f"/api/org/members/{sole['user_id']}", headers=mgr).status_code == 403
    assert client.patch(
        f"/api/org/members/{sole['user_id']}", headers=headers, json={"role": "viewer"}
    ).status_code == 403

    # Still an owner, and still able to do owner-only work.
    assert data(client.get("/api/org/context", headers=headers))["role"] == "owner"


def test_the_last_owner_guard_refuses_at_the_service_level(client, owner):
    """
    The belt to the API's braces.

    No current endpoint can reach this — acting on an owner requires being an
    owner, and acting on yourself is refused first, so a second owner always
    exists by the time the count is checked. It is kept because a future caller
    that skips one of those checks must still not be able to strand an
    organization without an owner.
    """
    headers, _ = owner
    db = SessionLocal()
    try:
        me = db.query(User).filter(
            User.email == data(client.get("/api/org/members", headers=headers))[0]["email"]
        ).one()
        membership = db.query(OrgMembership).filter(OrgMembership.user_id == me.id).one()
        other = User(email="ghost@invite-example.com", password_hash="x", role="user")

        with pytest.raises(invitations.InvitationError) as demote:
            invitations.change_role(
                db, membership=membership, actor=other, actor_role="owner", role="viewer"
            )
        assert demote.value.status == 409
        assert "only owner" in str(demote.value)

        with pytest.raises(invitations.InvitationError) as remove:
            invitations.remove_member(
                db, membership=membership, actor=other, actor_role="owner"
            )
        assert remove.value.status == 409
    finally:
        db.rollback()
        db.close()


def test_a_second_owner_makes_the_first_demotable(client, owner):
    headers, _ = owner
    issued = data(invite(client, headers, "successor@invite-example.com", role="owner"))
    successor = accept_as_new_user(client, issued["token"])
    first = next(
        m for m in data(client.get("/api/org/members", headers=headers)) if m["is_you"]
    )
    updated = data(client.patch(
        f"/api/org/members/{first['user_id']}", headers=successor, json={"role": "manager"}
    ))
    assert updated["role"] == "manager"


def test_nobody_can_change_their_own_role(client, owner):
    # Upwards is self-escalation; downwards is how an organization locks itself
    # out. Both are refused.
    headers, _ = owner
    me = next(m for m in data(client.get("/api/org/members", headers=headers)) if m["is_you"])
    refused = client.patch(
        f"/api/org/members/{me['user_id']}", headers=headers, json={"role": "viewer"}
    )
    assert refused.status_code == 403
    assert "your own role" in detail(refused)


def test_nobody_can_remove_themselves(client, owner):
    headers, _ = owner
    me = next(m for m in data(client.get("/api/org/members", headers=headers)) if m["is_you"])
    assert client.delete(f"/api/org/members/{me['user_id']}", headers=headers).status_code == 403


def test_a_manager_cannot_promote_someone_to_owner(client, owner):
    headers, _ = owner
    mgr = accept_as_new_user(
        client, data(invite(client, headers, "m2@invite-example.com", role="manager"))["token"]
    )
    accept_as_new_user(
        client, data(invite(client, headers, "v2@invite-example.com", role="viewer"))["token"]
    )
    viewer = next(
        m for m in data(client.get("/api/org/members", headers=headers))
        if m["email"] == "v2@invite-example.com"
    )
    refused = client.patch(
        f"/api/org/members/{viewer['user_id']}", headers=mgr, json={"role": "owner"}
    )
    assert refused.status_code == 403


def test_a_manager_cannot_touch_an_owner(client, owner):
    headers, _ = owner
    mgr = accept_as_new_user(
        client, data(invite(client, headers, "m3@invite-example.com", role="manager"))["token"]
    )
    the_owner = next(
        m for m in data(client.get("/api/org/members", headers=headers)) if m["role"] == "owner"
    )
    assert client.patch(
        f"/api/org/members/{the_owner['user_id']}", headers=mgr, json={"role": "viewer"}
    ).status_code == 403
    assert client.delete(
        f"/api/org/members/{the_owner['user_id']}", headers=mgr
    ).status_code == 403


def test_removing_a_member_revokes_their_access_immediately(client, owner):
    headers, _ = owner
    issued = data(invite(client, headers, "leaver@invite-example.com"))
    leaver = accept_as_new_user(client, issued["token"])
    assert client.get("/api/org/context", headers=leaver).status_code == 200

    target = next(
        m for m in data(client.get("/api/org/members", headers=headers))
        if m["email"] == "leaver@invite-example.com"
    )
    data(client.delete(f"/api/org/members/{target['user_id']}", headers=headers))

    db = SessionLocal()
    try:
        assert db.query(OrgMembership).filter(
            OrgMembership.user_id == uuid.UUID(target["user_id"])
        ).first() is None
    finally:
        db.close()


def test_a_member_of_another_organization_cannot_be_managed(client, owner):
    headers, _ = owner
    stranger = signup(client, "far@invite-example.com", "Far Co")
    theirs = data(client.get("/api/org/members", headers=stranger))[0]
    assert client.patch(
        f"/api/org/members/{theirs['user_id']}", headers=headers, json={"role": "viewer"}
    ).status_code == 404


# ---------------------------------------------------------------------------
# Everything leaves a record
# ---------------------------------------------------------------------------
def test_every_membership_change_reaches_the_audit_trail(client, owner):
    headers, _ = owner
    issued = data(invite(client, headers, "audited@invite-example.com", role="viewer"))
    accept_as_new_user(client, issued["token"])
    target = next(
        m for m in data(client.get("/api/org/members", headers=headers))
        if m["email"] == "audited@invite-example.com"
    )
    data(client.patch(f"/api/org/members/{target['user_id']}", headers=headers,
                      json={"role": "analyst"}))
    data(client.delete(f"/api/org/members/{target['user_id']}", headers=headers))

    actions = {e["action"] for e in data(client.get("/api/audit?limit=100", headers=headers))["events"]}
    assert {"member.invited", "member.joined", "member.updated", "member.removed"} <= actions


def test_revoking_an_invitation_is_recorded(client, owner):
    headers, _ = owner
    issued = data(invite(client, headers, "revoked@invite-example.com"))
    data(client.delete(f"/api/org/invitations/{issued['id']}", headers=headers))
    actions = {e["action"] for e in data(client.get("/api/audit?limit=100", headers=headers))["events"]}
    assert "member.invite_revoked" in actions


# ---------------------------------------------------------------------------
# The whole journey
# ---------------------------------------------------------------------------
def test_an_owner_can_build_a_team_from_an_empty_organization(client, owner):
    """
    The thing that was impossible before this module.

    An organization could only ever have the member that signup created; adding
    a second person meant an INSERT by whoever held the database password.
    """
    headers, owner_email = owner
    client_b = data(client.post("/api/org/entities", headers=headers, json={"name": "Client B"}))

    team = [
        ("payroll.manager@invite-example.com", "manager", []),
        ("senior.analyst@invite-example.com", "analyst", []),
        ("client.b.analyst@invite-example.com", "analyst", [client_b["id"]]),
        ("finance.viewer@invite-example.com", "viewer", []),
    ]
    for email, role, scope in team:
        issued = data(invite(client, headers, email, role=role, entity_ids=scope))
        accept_as_new_user(client, issued["token"])

    members = data(client.get("/api/org/members", headers=headers))
    assert len(members) == 5
    assert {m["role"] for m in members} == {"owner", "manager", "analyst", "viewer"}

    scoped = next(m for m in members if m["email"] == "client.b.analyst@invite-example.com")
    assert scoped["entity_ids"] == [client_b["id"]]
    assert next(m for m in members if m["email"] == owner_email)["entity_ids"] == []
