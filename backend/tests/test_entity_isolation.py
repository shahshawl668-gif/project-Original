"""
The entity boundary is the product's access-control guarantee: a practice runs
several clients' payroll through one login, and nothing may leak between them.
These tests exercise that boundary through the HTTP surface.
"""
from __future__ import annotations

import uuid

from app.database import SessionLocal
from app.models import OrgMembership, User


def _signup(client, email: str, company: str) -> dict:
    r = client.post(
        "/api/auth/signup",
        json={"email": email, "password": "Passw0rd!x", "company_name": company},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['data']['access_token']}"}


def _context(client, headers) -> dict:
    return client.get("/api/org/context", headers=headers).json()["data"]


def _component_payload(name: str) -> dict:
    return {"component_name": name, "pf_applicable": True, "taxable": True}


def test_signup_provisions_an_org_with_one_entity(client):
    h = _signup(client, "hr@acme-example.com", "Acme Manufacturing")
    ctx = _context(client, h)

    assert ctx["organization"]["name"] == "Acme Manufacturing"
    assert ctx["organization"]["org_type"] == "enterprise"
    assert ctx["role"] == "owner"
    assert len(ctx["entities"]) == 1
    assert ctx["active_entity"]["name"] == "Acme Manufacturing"


def test_data_written_under_one_entity_is_invisible_to_another(client):
    h = _signup(client, "ops@bureau-example.com", "Bureau Payroll")
    first = _context(client, h)["active_entity"]["id"]

    r = client.post("/api/org/entities", json={"name": "Beta Logistics"}, headers=h)
    assert r.status_code == 200, r.text
    second = r.json()["data"]["id"]

    r = client.post(
        "/api/components",
        json=_component_payload("Basic"),
        headers={**h, "X-Entity-Id": first},
    )
    assert r.status_code == 201, r.text

    seen_first = client.get("/api/components", headers={**h, "X-Entity-Id": first}).json()["data"]
    seen_second = client.get("/api/components", headers={**h, "X-Entity-Id": second}).json()["data"]

    assert [c["component_name"] for c in seen_first] == ["Basic"]
    assert seen_second == []


def test_same_component_name_may_exist_in_two_entities(client):
    """The old unique constraint was per user and would have rejected this."""
    h = _signup(client, "ops2@bureau-example.com", "Bureau Two")
    first = _context(client, h)["active_entity"]["id"]
    second = client.post("/api/org/entities", json={"name": "Gamma Foods"}, headers=h).json()["data"]["id"]

    for entity_id in (first, second):
        r = client.post(
            "/api/components",
            json=_component_payload("Basic"),
            headers={**h, "X-Entity-Id": entity_id},
        )
        assert r.status_code == 201, f"entity {entity_id}: {r.text}"


def test_entity_from_another_organization_is_not_reachable(client):
    h_one = _signup(client, "one@first-example.com", "First Corp")
    h_two = _signup(client, "two@second-example.com", "Second Corp")

    foreign = _context(client, h_one)["active_entity"]["id"]

    r = client.get("/api/components", headers={**h_two, "X-Entity-Id": foreign})
    assert r.status_code == 404
    # Indistinguishable from an id that does not exist, so the header cannot be
    # used to enumerate other organizations' entities.
    assert r.json()["error"]["detail"] == "Entity not found"

    r = client.get("/api/components", headers={**h_two, "X-Entity-Id": str(uuid.uuid4())})
    assert r.status_code == 404
    assert r.json()["error"]["detail"] == "Entity not found"


def test_malformed_entity_header_is_rejected(client):
    h = _signup(client, "three@third-example.com", "Third Corp")
    r = client.get("/api/components", headers={**h, "X-Entity-Id": "not-a-uuid"})
    assert r.status_code == 400


def test_omitting_the_header_falls_back_to_the_first_entity(client):
    """Single-entity enterprises never have to send the header."""
    h = _signup(client, "four@fourth-example.com", "Fourth Corp")
    entity_id = _context(client, h)["active_entity"]["id"]

    r = client.post("/api/components", json=_component_payload("HRA"), headers=h)
    assert r.status_code == 201

    scoped = client.get("/api/components", headers={**h, "X-Entity-Id": entity_id}).json()["data"]
    assert [c["component_name"] for c in scoped] == ["HRA"]


def test_viewer_role_may_read_but_not_write(client):
    h = _signup(client, "five@fifth-example.com", "Fifth Corp")

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "five@fifth-example.com").one()
        membership = db.query(OrgMembership).filter(OrgMembership.user_id == user.id).one()
        membership.role = "viewer"
        db.add(membership)
        db.commit()
    finally:
        db.close()

    assert client.get("/api/components", headers=h).status_code == 200
    r = client.post("/api/components", json=_component_payload("Basic"), headers=h)
    assert r.status_code == 403


def test_creating_entities_requires_manager_or_owner(client):
    h = _signup(client, "six@sixth-example.com", "Sixth Corp")

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "six@sixth-example.com").one()
        membership = db.query(OrgMembership).filter(OrgMembership.user_id == user.id).one()
        membership.role = "analyst"
        db.add(membership)
        db.commit()
    finally:
        db.close()

    # An analyst still does the day-to-day work...
    assert client.post("/api/components", json=_component_payload("Basic"), headers=h).status_code == 201
    # ...but does not get to add clients to the practice.
    assert client.post("/api/org/entities", json={"name": "Nope Ltd"}, headers=h).status_code == 403
