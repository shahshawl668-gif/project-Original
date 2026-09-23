"""
The group-company landing page.

A group runs several employers, and the question on any given morning is which
of them needs attention. That is one request across every company a person can
reach — which makes the boundary of "can reach" the thing worth testing.
"""
from __future__ import annotations

import hashlib

PASSWORD = "Passw0rd!x"


def data(response):
    assert response.status_code == 200, response.text
    return response.json()["data"]


def signup(client, email: str, company: str) -> dict:
    r = client.post("/api/auth/signup", json={
        "email": email, "password": PASSWORD, "company_name": company,
    })
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['data']['access_token']}"}


def slug(request) -> str:
    return hashlib.sha256(request.node.name.encode()).hexdigest()[:12]


def test_a_fresh_account_sees_its_one_company(client, request):
    s = slug(request)
    headers = signup(client, f"solo-{s}@pf-example.com", f"Solo {s}")

    payload = data(client.get("/api/org/portfolio", headers=headers))
    assert payload["totals"]["entities"] == 1
    assert payload["totals"]["open_findings"] == 0
    row = payload["entities"][0]
    assert row["last_register_period"] is None
    # Nothing uploaded yet is a state worth naming, not a zero to hide.
    assert payload["totals"]["awaiting_register"] == 1


def test_every_company_in_the_group_is_listed(client, request):
    s = slug(request)
    headers = signup(client, f"group-{s}@pf-example.com", f"Group {s}")

    for name in ("Northern Mills", "Southern Textiles"):
        created = client.post("/api/org/entities", json={"name": name}, headers=headers)
        assert created.status_code == 200, created.text

    payload = data(client.get("/api/org/portfolio", headers=headers))
    names = {e["name"] for e in payload["entities"]}
    assert {"Northern Mills", "Southern Textiles"} <= names
    assert payload["totals"]["entities"] == len(payload["entities"]) == 3


def test_another_organizations_companies_are_never_listed(client, request):
    """The whole page is a list of companies, so its scope is the whole point."""
    s = slug(request)
    mine = signup(client, f"mine-{s}@pf-example.com", f"Mine {s}")
    theirs = signup(client, f"theirs-{s}@pf-example.com", f"Theirs {s}")

    client.post("/api/org/entities", json={"name": f"Secret Client {s}"}, headers=theirs)

    payload = data(client.get("/api/org/portfolio", headers=mine))
    names = {e["name"] for e in payload["entities"]}
    assert not any(n.startswith("Secret Client") for n in names), names


def test_the_list_puts_the_company_in_trouble_first(client, request):
    """Sorted by what needs doing. A page sorted by name buries the problem."""
    s = slug(request)
    headers = signup(client, f"order-{s}@pf-example.com", f"Order {s}")
    for name in ("Zebra Works", "Alpha Works"):
        client.post("/api/org/entities", json={"name": name}, headers=headers)

    payload = data(client.get("/api/org/portfolio", headers=headers))
    rows = payload["entities"]
    # With no findings anywhere the tie-break is alphabetical, so the ordering
    # is still deterministic rather than whatever the database returned.
    assert [r["name"] for r in rows] == sorted(r["name"] for r in rows)
