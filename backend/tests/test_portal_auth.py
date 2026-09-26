"""Platform and client sessions must remain separate even for a dual-role user."""
from app.config import settings


def test_workspace_binding_and_platform_session(client, monkeypatch):
    from app.database import SessionLocal
    from app.models import User
    created = client.post("/api/auth/signup", json={
        "email": "platform.owner@example.test", "password": "Passw0rd!x", "company_name": "Alpha Payroll"})
    assert created.status_code == 200, created.text
    with SessionLocal() as db:
        owner = db.query(User).filter(User.email == "platform.owner@example.test").one()
        owner.platform_role = "owner"
        db.commit()
    context = client.get("/api/org/context", headers={"Authorization": f"Bearer {created.json()['data']['access_token']}"}).json()["data"]
    slug = context["organization"]["slug"]
    monkeypatch.setattr(settings, "env", "production")
    monkeypatch.setattr(settings, "allow_public_signup", False)
    credentials = {"email": "platform.owner@example.test", "password": "Passw0rd!x"}
    assert client.post("/api/auth/signup", json={**credentials, "company_name": "Wrong"}).status_code == 404
    assert client.post("/api/auth/login", json=credentials).status_code == 400
    assert client.post("/api/auth/login", json={**credentials, "workspace_slug": "wrong"}).status_code == 401

    client_login = client.post("/api/auth/login", json={**credentials, "workspace_slug": slug})
    assert client_login.status_code == 200, client_login.text
    client_tokens = client_login.json()["data"]
    client_header = {"Authorization": f"Bearer {client_tokens['access_token']}"}
    assert client.get("/api/org/context", headers=client_header).status_code == 200
    assert client.get("/api/admin/organizations", headers=client_header).status_code == 403

    platform_login = client.post("/api/auth/platform-login", json=credentials)
    assert platform_login.status_code == 200, platform_login.text
    platform_header = {"Authorization": f"Bearer {platform_login.json()['data']['access_token']}"}
    assert client.get("/api/admin/organizations", headers=platform_header).status_code == 200
    assert client.get("/api/org/context", headers=platform_header).status_code == 403
    rotated = client.post("/api/auth/refresh", json={"refresh_token": client_tokens["refresh_token"]})
    assert rotated.status_code == 200
    assert client.get("/api/org/context", headers={"Authorization": f"Bearer {rotated.json()['data']['access_token']}"}).status_code == 200


def test_platform_provisions_invitation_only_workspace(client, monkeypatch):
    from app.database import SessionLocal
    from app.models import User
    from app.security import hash_password

    with SessionLocal() as db:
        owner = User(email="provisioner@example.test", password_hash=hash_password("Passw0rd!x"), role="user", platform_role="owner")
        db.add(owner)
        db.commit()
    monkeypatch.setattr(settings, "env", "production")
    auth = client.post("/api/auth/platform-login", json={"email": "provisioner@example.test", "password": "Passw0rd!x"})
    header = {"Authorization": f"Bearer {auth.json()['data']['access_token']}"}
    created = client.post("/api/admin/organizations", headers=header, json={"name": "Bravo Corp", "owner_email": "bravo@example.test"})
    assert created.status_code == 201, created.text
    data = created.json()["data"]
    assert data["login_path"] == "/w/bravo-corp/login"
    token = data["invitation_path"].split("token=")[1]
    accepted = client.post("/api/org/invitations/register", json={"token": token, "password": "Passw0rd!x"})
    assert accepted.status_code == 200, accepted.text
    headers = {"Authorization": f"Bearer {accepted.json()['data']['access_token']}"}
    assert client.get("/api/org/context", headers=headers).json()["data"]["organization"]["slug"] == "bravo-corp"
    assert client.post("/api/auth/platform-login", json={"email": "bravo@example.test", "password": "Passw0rd!x"}).status_code == 401
