"""
When the secrets key cannot open what is stored — STUDIO_SECRET_KEY changed
without the old key kept alongside — nothing answers a bare 500.

The month's integration picture needs no secret at all, so it keeps working.
Anything that does need one answers 503 with the reason and the remedy, in the
usual envelope, even on a route that forgot to catch it.
"""
from __future__ import annotations

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from tests.test_studio_sync import _connection, company, hrms  # noqa: F401 — fixtures


def test_a_lost_secrets_key_never_answers_500(client, company, hrms, monkeypatch):  # noqa: F811
    conn = _connection(client, company, hrms)
    monkeypatch.setattr(settings, "studio_secret_key", Fernet.generate_key().decode())   # the old key is gone
    probe = TestClient(app, raise_server_exceptions=False)

    # Month close and Validations read this; it shows stored health, decrypting nothing.
    month = probe.get("/api/studio/period/2026-06", headers=company)
    assert month.status_code == 200, month.text
    listed = {c["id"]: c for c in month.json()["data"]["connections"]}
    assert listed[conn["id"]]["health"] == conn["health"]

    # A rename commits and then describes the connection, which needs the secret:
    # the answer names the problem instead of a generic server error.
    renamed = probe.patch(f"/api/studio/connections/{conn['id']}", headers=company, json={"name": "Renamed feed"})
    assert renamed.status_code == 503, renamed.text
    body = renamed.json()
    assert body["success"] is False and "STUDIO_SECRET_KEY" in body["error"]["detail"]

    assert probe.get("/api/studio/connections", headers=company).status_code == 503
