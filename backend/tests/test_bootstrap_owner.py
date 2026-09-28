"""The way into an installation that has no platform owner.

Production closes signup and staff arrive by invitation from an existing owner,
so a fresh database has no way in at all without this. The tests that matter
are the refusals: a command that creates an owner is only safe if it can do
nothing else.
"""
from __future__ import annotations

import pytest

from app.config import settings
from app.database import SessionLocal
from app.models import User
from app.security import hash_password

PASSWORD = "Passw0rd!x"


@pytest.fixture()
def no_platform_staff(client):
    """An installation with no platform owner or admin, restored afterwards.

    The suite shares one database and other tests create platform staff, so
    the state this command exists for has to be made on purpose.

    Legacy ``role='admin'`` accounts are demoted too: the one-time migration the
    command runs first promotes them to owner whenever no staff exist, and the
    command then correctly refuses. That path has its own test below.
    """
    db = SessionLocal()
    try:
        affected = db.query(User).filter(
            (User.platform_role.isnot(None)) | (User.role == "admin")
        ).all()
        saved = {user.id: (user.platform_role, user.role) for user in affected}
        for user in affected:
            user.platform_role = None
            if user.email != "system@payrollcheck.local":
                user.role = "user"
        db.commit()
    finally:
        db.close()

    yield

    db = SessionLocal()
    try:
        # Anything this test promoted or created as staff goes back to nothing,
        # so later tests see the installation as they left it.
        for user in db.query(User).filter(User.platform_role.isnot(None)).all():
            if user.id not in saved:
                user.platform_role = None
        for user_id, (platform_role, role) in saved.items():
            user = db.get(User, user_id)
            if user is not None:
                user.platform_role = platform_role
                user.role = role
        db.commit()
    finally:
        db.close()


def test_the_first_owner_is_invited_and_can_sign_in(client, no_platform_staff, monkeypatch):
    """The whole path: issue, accept by setting a password, sign in as platform staff."""
    from app.bootstrap_owner import issue

    token = issue("first.owner@bootstrap-example.com")

    joined = client.post("/api/auth/platform-invitations/register",
                         json={"token": token, "password": PASSWORD})
    assert joined.status_code == 200, joined.text

    with SessionLocal() as db:
        owner = db.query(User).filter(User.email == "first.owner@bootstrap-example.com").one()
        assert owner.platform_role == "owner"
        # Never a client-side admin as a side effect.
        assert owner.role == "user"

    monkeypatch.setattr(settings, "env", "production")
    signed_in = client.post("/api/auth/platform-login",
                            json={"email": "first.owner@bootstrap-example.com",
                                  "password": PASSWORD})
    assert signed_in.status_code == 200, signed_in.text


def test_the_invitation_works_once(client, no_platform_staff):
    from app.bootstrap_owner import issue

    token = issue("once.only@bootstrap-example.com")
    first = client.post("/api/auth/platform-invitations/register",
                        json={"token": token, "password": PASSWORD})
    assert first.status_code == 200, first.text
    second = client.post("/api/auth/platform-invitations/register",
                         json={"token": token, "password": "Another1!pass"})
    assert second.status_code in (400, 409), second.text


def test_it_refuses_once_any_platform_staff_exist(client, no_platform_staff):
    """The property that makes it safe: it can only ever create the first.

    Otherwise anyone with shell access could quietly add themselves as owner of
    a platform someone else runs, with no record in the console.
    """
    from app.bootstrap_owner import RefuseToBootstrap, issue

    with SessionLocal() as db:
        db.add(User(email="existing.admin@bootstrap-example.com",
                    password_hash=hash_password(PASSWORD), role="user",
                    platform_role="admin"))
        db.commit()

    with pytest.raises(RefuseToBootstrap, match="already has platform staff"):
        issue("second.owner@bootstrap-example.com")

    with SessionLocal() as db:
        assert db.query(User).filter(
            User.email == "second.owner@bootstrap-example.com").first() is None


def test_a_legacy_admin_is_promoted_by_the_migration_so_it_refuses(client, no_platform_staff):
    """An installation upgraded from before platform roles already has its owner.

    The one-time migration names the legacy admin as owner; the command sees
    that and refuses, rather than inviting a second, competing owner.
    """
    from app.bootstrap_owner import RefuseToBootstrap, issue

    with SessionLocal() as db:
        db.add(User(email="legacy.admin@bootstrap-example.com",
                    password_hash=hash_password(PASSWORD), role="admin"))
        db.commit()

    with pytest.raises(RefuseToBootstrap, match="legacy.admin@bootstrap-example.com, owner"):
        issue("newcomer@bootstrap-example.com")


def test_it_will_not_promote_an_existing_account(client, no_platform_staff):
    """A client's login must not be quietly turned into platform access."""
    from app.bootstrap_owner import RefuseToBootstrap, issue

    with SessionLocal() as db:
        db.add(User(email="a.client@bootstrap-example.com",
                    password_hash=hash_password(PASSWORD), role="user"))
        db.commit()

    with pytest.raises(RefuseToBootstrap, match="already has an account"):
        issue("a.client@bootstrap-example.com")


@pytest.mark.parametrize("address", ["not-an-address", "system@payrollcheck.local"])
def test_it_refuses_an_unusable_address(client, no_platform_staff, address):
    from app.bootstrap_owner import RefuseToBootstrap, issue

    with pytest.raises(RefuseToBootstrap):
        issue(address)


def test_the_command_prints_a_link_and_reports_refusal_by_exit_code(
    client, no_platform_staff, capsys
):
    """Scripts running this need to tell success from refusal without parsing prose."""
    from app.bootstrap_owner import main

    assert main(["cli.owner@bootstrap-example.com", "--site", "https://example.test"]) == 0
    printed = capsys.readouterr().out
    assert "https://example.test/platform/join?token=" in printed

    # Now there is an owner-to-be with an account pending — but no staff yet, so
    # accept it to make the refusal real, then run again.
    token = printed.split("token=", 1)[1].split()[0]
    client.post("/api/auth/platform-invitations/register",
                json={"token": token, "password": PASSWORD})
    assert main(["another@bootstrap-example.com"]) == 2
