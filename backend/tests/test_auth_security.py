"""
Sign-in protection, session revocation, two-step sign-in, and the HTTP guard.

Each test names the attack it stops. The accounts are synthetic and the codes
are computed here from the secret the enrolment step returns, exactly as an
authenticator app would.
"""
from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.config import settings
from app.database import SessionLocal
from app.models import LoginThrottle, RefreshToken, SecurityEvent, User
from app.models.user import PasswordResetToken
from app.security import token_fingerprint
from app.services import auth_security as guard

PASSWORD = "Synthetic-Passw0rd"


def _signup(client, tag: str) -> tuple[str, dict]:
    email = f"{tag}-{uuid.uuid4().hex[:6]}@example.com"
    r = client.post("/api/auth/signup", json={"email": email, "password": PASSWORD, "company_name": f"{tag} Ltd"})
    assert r.status_code == 200, r.text
    return email, r.json()["data"]


def _login(client, email, password=PASSWORD):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def _bearer(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _me(client, tokens) -> int:
    return client.get("/api/auth/me", headers=_bearer(tokens)).status_code


def _events(email: str) -> list[SecurityEvent]:
    with SessionLocal() as db:
        rows = db.query(SecurityEvent).filter(SecurityEvent.subject == email.lower()).all()
        for r in rows:
            db.expunge(r)
        return rows


def _code(secret: str, at: float | None = None) -> str:
    return guard._totp(secret).generate(int(time.time() if at is None else at)).decode()


def _enrol(client, tokens) -> tuple[str, list[str], dict]:
    setup = client.post("/api/auth/mfa/setup", headers=_bearer(tokens), json={"password": PASSWORD})
    assert setup.status_code == 200, setup.text
    secret = setup.json()["data"]["secret"]
    assert setup.json()["data"]["otpauth_uri"].startswith("otpauth://totp/")
    enabled = client.post("/api/auth/mfa/enable", headers=_bearer(tokens), json={"code": _code(secret)})
    assert enabled.status_code == 200, enabled.text
    data = enabled.json()["data"]
    return secret, data["recovery_codes"], {"access_token": data["access_token"], "refresh_token": data["refresh_token"]}


# ── guessing ────────────────────────────────────────────────────────────────

def test_guessing_locks_the_identifier_even_against_the_right_password(client):
    email, _ = _signup(client, "lock")
    for _ in range(settings.login_max_failures):
        assert _login(client, email, "wrong-guess").status_code == 401
    locked = _login(client, email)                                 # the right password, too late
    assert locked.status_code == 429
    assert int(locked.headers["Retry-After"]) > 0

    # An address with no account is refused in exactly the same words.
    ghost = f"nobody-{uuid.uuid4().hex[:6]}@example.com"
    for _ in range(settings.login_max_failures):
        assert _login(client, ghost, "wrong-guess").status_code == 401
    ghost_locked = _login(client, ghost, "anything")
    assert ghost_locked.status_code == 429
    assert ghost_locked.json()["error"]["detail"] == locked.json()["error"]["detail"]

    # A lock ends on its own.
    with SessionLocal() as db:
        row = db.get(LoginThrottle, f"login:{email}")
        row.locked_until = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    assert _login(client, email).status_code == 200

    kinds = [(e.kind, e.outcome) for e in _events(email)]
    assert ("login", "failure") in kinds and ("login", "blocked") in kinds and ("login", "success") in kinds
    # No event, anywhere, holds what was typed as a password.
    blob = json.dumps([e.detail for e in _events(email)])
    assert "wrong-guess" not in blob and PASSWORD not in blob


def test_a_wrong_address_and_a_wrong_password_read_the_same(client):
    email, _ = _signup(client, "same")
    wrong_password = _login(client, email, "not-it")
    wrong_address = _login(client, "no-" + email, "not-it")
    assert wrong_password.status_code == wrong_address.status_code == 401
    assert wrong_password.json() == wrong_address.json()


def test_a_password_reset_request_says_nothing_about_who_has_an_account(client):
    email, _ = _signup(client, "enum")
    real = client.post("/api/auth/password-reset-request", json={"email": email})
    ghost = client.post("/api/auth/password-reset-request", json={"email": "ghost-" + email})
    assert real.status_code == ghost.status_code == 200
    assert real.json() == ghost.json() == {"success": True, "data": {"requested": True}, "error": None}
    # And it is rate limited like sign-in.
    for _ in range(settings.login_max_failures):
        client.post("/api/auth/password-reset-request", json={"email": email})
    assert client.post("/api/auth/password-reset-request", json={"email": email}).status_code == 429


# ── sessions ────────────────────────────────────────────────────────────────

def test_a_password_reset_ends_every_session(client):
    email, first = _signup(client, "reset")
    second = _login(client, email).json()["data"]
    assert _me(client, first) == _me(client, second) == 200
    raw = secrets.token_urlsafe(32)
    with SessionLocal() as db:
        user = db.query(User).filter(User.email == email).one()
        db.add(PasswordResetToken(user_id=user.id, token_hash=token_fingerprint(raw),
                                  expires_at=datetime.now(UTC) + timedelta(hours=1)))
        db.commit()
    done = client.post("/api/auth/password-reset-confirm", json={"token": raw, "new_password": "An0ther-Passw0rd"})
    assert done.status_code == 200, done.text
    assert _me(client, first) == _me(client, second) == 401          # access tokens
    assert client.post("/api/auth/refresh", json={"refresh_token": second["refresh_token"]}).status_code == 401
    assert client.post("/api/auth/password-reset-confirm",
                       json={"token": raw, "new_password": "Th1rd-Passw0rd"}).status_code == 400
    assert _login(client, email, "An0ther-Passw0rd").status_code == 200


def test_sign_out_everywhere(client):
    email, first = _signup(client, "everywhere")
    second = _login(client, email).json()["data"]
    assert client.post("/api/auth/sessions/revoke-all", headers=_bearer(second)).status_code == 200
    assert _me(client, first) == _me(client, second) == 401
    assert client.post("/api/auth/refresh", json={"refresh_token": first["refresh_token"]}).status_code == 401
    assert _me(client, _login(client, email).json()["data"]) == 200


def test_a_replayed_refresh_token_ends_the_session_family(client):
    email, tokens = _signup(client, "replay")
    rotated = client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert rotated.status_code == 200
    fresh = rotated.json()["data"]

    # Inside the grace window: a second tab racing the first. Refused, nothing ended.
    assert client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401
    assert _me(client, fresh) == 200

    # After it: someone else has the old token. Everyone is signed out.
    with SessionLocal() as db:
        row = db.query(RefreshToken).filter(RefreshToken.token_hash == token_fingerprint(tokens["refresh_token"])).one()
        row.rotated_at = datetime.now(UTC) - timedelta(seconds=settings.refresh_reuse_grace_seconds + 5)
        db.commit()
    assert client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401
    assert _me(client, fresh) == 401
    assert client.post("/api/auth/refresh", json={"refresh_token": fresh["refresh_token"]}).status_code == 401
    assert any(e.kind == "refresh" and e.outcome == "detected" for e in _events(email))


def test_a_token_from_before_session_versions_still_works(client):
    """The deploy that adds session versions must not sign anyone out."""
    from app.security import create_access_token

    email, tokens = _signup(client, "legacy")
    with SessionLocal() as db:
        user = db.query(User).filter(User.email == email).one()
        legacy = create_access_token(str(user.id), extra={"portal": "client", "org_id": None})  # no "sv"
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {legacy}"}).status_code == 200


# ── two-step sign-in ────────────────────────────────────────────────────────

def test_two_step_sign_in(client):
    email, tokens = _signup(client, "mfa")
    assert client.post("/api/auth/mfa/setup", headers=_bearer(tokens), json={"password": "wrong"}).status_code == 401
    secret, recovery, current = _enrol(client, tokens)
    assert len(recovery) == 10
    assert _me(client, tokens) == 401            # sessions from before enrolment are ended
    assert _me(client, current) == 200           # the enrolling device carries on

    with SessionLocal() as db:
        user = db.query(User).filter(User.email == email).one()
        assert secret not in (user.mfa_secret_enc or "")          # stored sealed, never in clear
        assert not any(c in json.dumps(user.mfa_recovery_hashes) for c in recovery)

    challenge = _login(client, email).json()["data"]
    assert challenge["mfa_required"] is True and "access_token" not in challenge
    # The challenge opens nothing on its own.
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {challenge['mfa_token']}"}).status_code == 401

    assert client.post("/api/auth/mfa/verify", json={"mfa_token": challenge["mfa_token"],
                                                      "code": "000000"}).status_code == 401
    # The step the enrolment spent is spent; the next one is accepted.
    code = _code(secret, time.time() + 30)
    ok = client.post("/api/auth/mfa/verify", json={"mfa_token": challenge["mfa_token"], "code": code})
    assert ok.status_code == 200, ok.text
    assert _me(client, ok.json()["data"]) == 200
    # The same code, a second time, inside its window: refused.
    again = _login(client, email).json()["data"]
    assert client.post("/api/auth/mfa/verify", json={"mfa_token": again["mfa_token"], "code": code}).status_code == 401

    # A recovery code works once.
    used = client.post("/api/auth/mfa/verify", json={"mfa_token": again["mfa_token"], "code": recovery[0]})
    assert used.status_code == 200, used.text
    third = _login(client, email).json()["data"]
    assert client.post("/api/auth/mfa/verify", json={"mfa_token": third["mfa_token"],
                                                      "code": recovery[0]}).status_code == 401
    status = client.get("/api/auth/mfa", headers=_bearer(used.json()["data"])).json()["data"]
    assert status["enabled"] is True and status["recovery_codes_left"] == 9

    # Turning it off needs the password and a code.
    session = used.json()["data"]
    assert client.post("/api/auth/mfa/disable", headers=_bearer(session),
                       json={"password": PASSWORD, "code": "123456"}).status_code == 401
    off = client.post("/api/auth/mfa/disable", headers=_bearer(session), json={"password": PASSWORD, "code": recovery[1]})
    assert off.status_code == 200, off.text
    assert "access_token" in _login(client, email).json()["data"]
    kinds = {e.kind for e in _events(email)}
    assert {"mfa_enrolled", "mfa", "mfa_disabled"} <= kinds
    blob = json.dumps([e.detail for e in _events(email)])
    assert not any(c in blob for c in recovery) and code not in blob


def test_guessing_the_second_step_locks_it(client):
    email, tokens = _signup(client, "mfalock")
    secret, _, _ = _enrol(client, tokens)
    challenge = _login(client, email).json()["data"]["mfa_token"]
    for _ in range(settings.login_max_failures):
        assert client.post("/api/auth/mfa/verify", json={"mfa_token": challenge, "code": "111111"}).status_code == 401
    right = client.post("/api/auth/mfa/verify", json={"mfa_token": challenge, "code": _code(secret, time.time() + 30)})
    assert right.status_code == 429


def test_requiring_it_for_staff_locks_no_one_out(client, monkeypatch):
    """Turned on before anyone enrolled: staff sign in, and can do only one thing — enrol."""
    from app.security import hash_password

    email = f"staff-{uuid.uuid4().hex[:6]}@example.com"
    with SessionLocal() as db:
        db.add(User(email=email, password_hash=hash_password(PASSWORD), role="user", platform_role="owner"))
        db.commit()
    monkeypatch.setattr(settings, "require_mfa_for_platform_staff", True)
    signed_in = client.post("/api/auth/platform-login", json={"email": email, "password": PASSWORD})
    assert signed_in.status_code == 200, signed_in.text
    tokens = signed_in.json()["data"]
    assert client.get("/api/admin/organizations", headers=_bearer(tokens)).status_code == 403
    assert client.get("/api/auth/mfa", headers=_bearer(tokens)).json()["data"]["required"] is True
    _, _, current = _enrol(client, tokens)
    assert client.get("/api/admin/organizations", headers=_bearer(current)).status_code == 200


def test_the_recovery_tool_removes_a_lost_second_factor(client):
    from app import auth_recovery

    email, tokens = _signup(client, "lostphone")
    _, _, current = _enrol(client, tokens)
    with pytest.raises(SystemExit):
        auth_recovery.run("reset-mfa", email, None)               # a reason is required
    print(auth_recovery.run("reset-mfa", email, "lost phone, identity confirmed by call"))
    assert _me(client, current) == 401
    assert "access_token" in _login(client, email).json()["data"]
    assert any(e.kind == "mfa_disabled" and e.detail.get("by") == "operator" for e in _events(email))

    for _ in range(settings.login_max_failures):
        _login(client, email, "wrong")
    assert _login(client, email).status_code == 429
    auth_recovery.run("unlock", email, None)
    assert _login(client, email).status_code == 200


def test_a_platform_owner_reads_the_security_log_and_a_client_cannot(client):
    from app.security import hash_password

    email = f"secowner-{uuid.uuid4().hex[:6]}@example.com"
    with SessionLocal() as db:
        db.add(User(email=email, password_hash=hash_password(PASSWORD), role="admin", platform_role="owner"))
        db.commit()
    owner = client.post("/api/auth/platform-login", json={"email": email, "password": PASSWORD}).json()["data"]
    events = client.get(f"/api/admin/security/events?subject={email}", headers=_bearer(owner))
    assert events.status_code == 200 and events.json()["data"][0]["kind"] == "platform_login"
    _, customer = _signup(client, "notstaff")
    assert client.get("/api/admin/security/events", headers=_bearer(customer)).status_code == 403


# ── HTTP ────────────────────────────────────────────────────────────────────

def test_every_answer_carries_the_security_headers(client):
    for r in (client.get("/api/health"), client.get("/api/auth/me"),
              client.post("/api/auth/login", json={"email": "x@example.com", "password": "y"})):
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["x-frame-options"] == "DENY"
        assert "default-src 'none'" in r.headers["content-security-policy"]
        assert r.headers["cache-control"] == "no-store"
        assert r.headers["referrer-policy"] == "no-referrer"


def test_a_forged_request_id_is_replaced(client):
    r = client.get("/api/health", headers={"X-Request-Id": "abc\r\nFAKE log line"})
    assert r.headers["x-request-id"] != "abc\r\nFAKE log line" and "\n" not in r.headers["x-request-id"]
    assert client.get("/api/health", headers={"X-Request-Id": "trace-123"}).headers["x-request-id"] == "trace-123"


def test_an_oversized_body_is_refused_before_it_is_read(client, monkeypatch):
    monkeypatch.setattr(settings, "max_request_mb", 1)
    big = b"x" * (1024 * 1024 + 10)
    r = client.post("/api/auth/login", content=big, headers={"content-type": "application/json"})
    assert r.status_code == 413 and r.json()["error"]["code"] == "payload_too_large"


def test_production_hides_the_interactive_api_reference():
    env = {**os.environ, "ENV": "production", "JWT_SECRET": "x" * 48,
           "DATABASE_URL": "postgresql://u:p@127.0.0.1:9/none", "EXPOSE_API_DOCS": "true"}
    out = subprocess.run([sys.executable, "-c", "from app.config import settings; print(settings.expose_api_docs)"],
                         env=env, capture_output=True, text=True, cwd=os.path.dirname(os.path.dirname(__file__)))
    assert out.stdout.strip() == "False", out.stderr


# ── passwords ───────────────────────────────────────────────────────────────

def test_a_common_password_is_refused_where_one_is_set_and_not_echoed_back(client):
    email = f"common-{uuid.uuid4().hex[:6]}@example.com"
    r = client.post("/api/auth/signup", json={"email": email, "password": "password123", "company_name": "C"})
    assert r.status_code == 422
    assert "most commonly used" in r.text and "password123" not in r.text
    # 64 characters is allowed (ASVS 6.2.9); an unusual password passes.
    long = "correct horse battery staple " * 2 + "x" * 6
    assert len(long) == 64
    assert client.post("/api/auth/signup", json={"email": email, "password": long, "company_name": "C"}).status_code == 200


def test_a_password_reset_does_not_bypass_two_step_sign_in(client):
    """ASVS 6.4.3: a reset changes the password, not the second factor."""
    email, tokens = _signup(client, "resetmfa")
    _enrol(client, tokens)
    raw = secrets.token_urlsafe(32)
    with SessionLocal() as db:
        user = db.query(User).filter(User.email == email).one()
        db.add(PasswordResetToken(user_id=user.id, token_hash=token_fingerprint(raw),
                                  expires_at=datetime.now(UTC) + timedelta(hours=1)))
        db.commit()
    assert client.post("/api/auth/password-reset-confirm",
                       json={"token": raw, "new_password": "An0ther-Passw0rd"}).status_code == 200
    after = _login(client, email, "An0ther-Passw0rd").json()["data"]
    assert after.get("mfa_required") is True and "access_token" not in after


# ── session lifetime and organisation policy ────────────────────────────────

def test_a_session_ends_at_its_absolute_limit_however_often_it_is_refreshed(client, monkeypatch):
    import jwt

    email, tokens = _signup(client, "absolute")
    claims = jwt.decode(tokens["refresh_token"], options={"verify_signature": False})
    assert isinstance(claims["auth_time"], int)
    rotated = client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).json()["data"]
    # A refresh carries the original sign-in time forward; it does not restart the clock.
    assert jwt.decode(rotated["refresh_token"], options={"verify_signature": False})["auth_time"] == claims["auth_time"]
    monkeypatch.setattr(time, "time", lambda: claims["auth_time"] + settings.session_absolute_hours * 3600 + 5)
    ended = client.post("/api/auth/refresh", json={"refresh_token": rotated["refresh_token"]})
    assert ended.status_code == 401 and "time limit" in ended.text


def test_an_owner_can_require_two_step_sign_in_without_locking_anyone_out(client):
    from app.models import OrgMembership

    owner_email, owner = _signup(client, "orgmfa")
    context = client.get("/api/org/context", headers=_bearer(owner)).json()["data"]
    # Not enrolled yourself: refused, so the switch cannot strand the organisation.
    refused = client.put("/api/org/approval-policy", headers=_bearer(owner), json={"members_require_mfa": True})
    assert refused.status_code == 409 and "your own account first" in refused.text
    _, _, owner = _enrol(client, owner)
    on = client.put("/api/org/approval-policy", headers=_bearer(owner), json={"members_require_mfa": True})
    assert on.status_code == 200 and on.json()["data"]["members_require_mfa"] is True

    # A member who has not enrolled signs in, and can do only one thing: enrol.
    member_email = f"member-{uuid.uuid4().hex[:6]}@example.com"
    from app.security import hash_password

    with SessionLocal() as db:
        member = User(email=member_email, password_hash=hash_password(PASSWORD), role="user")
        db.add(member)
        db.flush()
        db.add(OrgMembership(org_id=uuid.UUID(context["organization"]["id"]), user_id=member.id, role="analyst"))
        db.commit()
    session = _login(client, member_email).json()["data"]
    assert client.get("/api/org/context", headers=_bearer(session)).status_code == 403
    assert client.get("/api/auth/mfa", headers=_bearer(session)).json()["data"]["required"] is True
    _, _, enrolled = _enrol(client, session)
    assert client.get("/api/org/context", headers=_bearer(enrolled)).status_code == 200


def test_rotating_the_secrets_key_keeps_two_step_sign_in_working(client, monkeypatch):
    """INCIDENT_RUNBOOK 2d: new,old → re-seal → new. Nobody has to re-enrol."""
    from cryptography.fernet import Fernet

    from app import rotate_secrets

    from app.services.studio import secrets as vault

    # "Old" is whatever key everything in this database is already sealed with.
    old, new = ",".join(k.decode() for k in vault._keys()), Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "studio_secret_key", old)
    email, tokens = _signup(client, "rotate")
    secret, _, _ = _enrol(client, tokens)

    monkeypatch.setattr(settings, "studio_secret_key", f"{new},{old}")
    counts = rotate_secrets.run(apply=True)
    assert counts["users.mfa_secret_enc"] >= 1
    monkeypatch.setattr(settings, "studio_secret_key", new)       # the old key is gone
    challenge = _login(client, email).json()["data"]["mfa_token"]
    ok = client.post("/api/auth/mfa/verify", json={"mfa_token": challenge, "code": _code(secret, time.time() + 30)})
    assert ok.status_code == 200, ok.text


def test_a_body_without_a_length_is_cut_off_at_the_ceiling(monkeypatch):
    """Chunked uploads carry no Content-Length; the limit counts bytes as they arrive."""
    import asyncio

    from app.http_guard import BodyLimit

    monkeypatch.setattr(settings, "max_request_mb", 1)
    read = {"bytes": 0}

    async def app(scope, receive, send):
        while True:
            message = await receive()
            read["bytes"] += len(message.get("body", b""))
            if not message.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    chunks = [{"type": "http.request", "body": b"x" * 256 * 1024, "more_body": True} for _ in range(8)]
    sent: list[dict] = []

    async def receive():
        return chunks.pop(0)

    async def send(message):
        sent.append(message)

    asyncio.run(BodyLimit(app)({"type": "http", "headers": []}, receive, send))
    assert sent[0]["status"] == 413
    assert read["bytes"] <= 1024 * 1024 + 256 * 1024         # stopped within a chunk of the ceiling


def test_a_forged_token_opens_nothing(client):
    """Wrong key, no signature (alg=none), expired: each is refused."""
    import jwt

    email, tokens = _signup(client, "forged")
    claims = jwt.decode(tokens["access_token"], options={"verify_signature": False})
    forged = [
        jwt.encode(claims, "x" * 48, algorithm="HS256"),
        jwt.encode(claims, None, algorithm="none"),
        jwt.encode({**claims, "exp": int(time.time()) - 1}, settings.jwt_secret, algorithm="HS256"),
    ]
    for token in forged:
        assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    assert _me(client, tokens) == 200


def test_a_person_sees_their_sessions_and_ends_one(client):
    """ASVS 7.5.2: view, and with the password, end any one."""
    email, laptop = _signup(client, "devices")
    phone = client.post("/api/auth/login", json={"email": email, "password": PASSWORD},
                        headers={"User-Agent": "Phone browser 1.0"}).json()["data"]
    listed = client.get("/api/auth/sessions", headers=_bearer(laptop)).json()["data"]
    assert len(listed) == 2
    assert sum(s["current"] for s in listed) == 1
    phone_row = next(s for s in listed if s["browser"] == "Phone browser 1.0")
    assert not phone_row["current"]

    # A refresh keeps the session's identity: the same row, later activity.
    phone = client.post("/api/auth/refresh", json={"refresh_token": phone["refresh_token"]}).json()["data"]
    again = client.get("/api/auth/sessions", headers=_bearer(laptop)).json()["data"]
    assert phone_row["id"] in {s["id"] for s in again} and len(again) == 2

    end = f"/api/auth/sessions/{phone_row['id']}/end"
    assert client.post(end, headers=_bearer(laptop), json={"password": "wrong"}).status_code == 401
    assert client.post(end, headers=_bearer(laptop), json={"password": PASSWORD}).status_code == 200
    assert client.post("/api/auth/refresh", json={"refresh_token": phone["refresh_token"]}).status_code == 401
    assert _me(client, laptop) == 200
    assert len(client.get("/api/auth/sessions", headers=_bearer(laptop)).json()["data"]) == 1
    assert any(e.kind == "session_ended" for e in _events(email))

    # Someone else's session is not yours to end, or to learn exists.
    _, stranger = _signup(client, "stranger")
    mine = client.get("/api/auth/sessions", headers=_bearer(laptop)).json()["data"][0]["id"]
    assert client.post(f"/api/auth/sessions/{mine}/end", headers=_bearer(stranger),
                       json={"password": PASSWORD}).status_code == 404
    assert _me(client, laptop) == 200
