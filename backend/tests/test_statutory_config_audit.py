"""A change to the statutory configuration leaves a record of who changed which field."""
import uuid


def _company(client) -> dict:
    email = f"statutory-audit-{uuid.uuid4().hex[:6]}@audit-example.com"
    signup = client.post("/api/auth/signup", json={
        "email": email, "password": "Passw0rd!x", "company_name": "Statutory Audit Example",
    })
    assert signup.status_code == 200, signup.text
    headers = {"Authorization": f"Bearer {signup.json()['data']['access_token']}"}
    entity = client.post("/api/org/entities", json={"name": "Audited Employer"}, headers=headers)
    assert entity.status_code == 200, entity.text
    headers["X-Entity-Id"] = entity.json()["data"]["id"]
    return headers


def _events(client, headers) -> list[dict]:
    r = client.get("/api/audit?limit=50", headers=headers)
    assert r.status_code == 200, r.text
    return [e for e in r.json()["data"]["events"] if e["action"].startswith("statutory_config.")]


def test_saving_and_resetting_the_statutory_configuration_is_audited(client):
    headers = _company(client)
    cfg = client.get("/api/config/statutory", headers=headers).json()["data"]
    body = {k: cfg[k] for k in ("pf", "esic", "component_mapping")}

    # Saving what is already there changes nothing and records nothing.
    assert client.put("/api/config/statutory", headers=headers, json=body).status_code == 200
    assert _events(client, headers) == []

    before = body["pf"]["wage"]["wage_ceiling"]
    body["pf"]["wage"]["wage_ceiling"] = "16000"
    saved = client.put("/api/config/statutory", headers=headers, json=body)
    assert saved.status_code == 200, saved.text
    [event] = _events(client, headers)
    assert event["action"] == "statutory_config.saved"
    assert "pf.wage.wage_ceiling" in event["summary"]
    change = next(c for c in event["detail"]["changes"] if c["field"] == "pf.wage.wage_ceiling")
    assert (str(change["before"]), str(change["after"])) == (str(before), "16000")

    reset = client.post("/api/config/statutory/reset", headers=headers)
    assert reset.status_code == 200, reset.text
    actions = [e["action"] for e in _events(client, headers)]
    assert "statutory_config.reset" in actions


def _config_digest(entity_id: str) -> str:
    from datetime import date

    from app.database import SessionLocal
    from app.models import Entity
    from app.services import run_inputs

    db = SessionLocal()
    try:
        entity = db.get(Entity, uuid.UUID(entity_id))
        return run_inputs.digest(run_inputs.configuration_snapshot(db, entity, date(2026, 6, 1)))
    finally:
        db.close()


def test_a_round_trip_save_does_not_make_validated_months_stale(client):
    """The browser returns 0.0050 as 0.005; that is not a change, and must not read as one."""
    headers = _company(client)
    cfg = client.get("/api/config/statutory", headers=headers).json()["data"]
    body = {k: cfg[k] for k in ("pf", "esic", "component_mapping")}
    before = _config_digest(headers["X-Entity-Id"])
    assert client.put("/api/config/statutory", headers=headers, json=body).status_code == 200
    assert _config_digest(headers["X-Entity-Id"]) == before

    # Changing one field changes the fingerprint — and leaves the others as stored.
    body["esic"]["wage"]["wage_ceiling"] = "22000"
    assert client.put("/api/config/statutory", headers=headers, json=body).status_code == 200
    assert _config_digest(headers["X-Entity-Id"]) != before
    [event] = _events(client, headers)
    assert [c["field"] for c in event["detail"]["changes"]] == ["esic.wage.wage_ceiling"]
