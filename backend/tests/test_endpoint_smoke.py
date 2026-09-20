"""
Every endpoint answers something other than 500.

Three shipped endpoints — the PT/LWF slabs screen and both income-tax
calculators — returned a NameError on every call, for as long as they had
existed. Each was a leftover from the entity refactor: a handler that took
`user` and passed `entity`. No test called them, so nothing noticed.

Ruff catches that class now (F821), and this catches the rest: a handler that
raises for any other reason nobody wrote a test for. It walks the application's
own OpenAPI description rather than a hand-kept list, so an endpoint added
tomorrow is covered the day it is added.

A 4xx is fine — it means the handler ran and disagreed with the request. Only a
500 is a bug.
"""
from __future__ import annotations

import pytest

from app.main import app

PASSWORD = "Passw0rd!x"


def _no_arg_get_paths() -> list[str]:
    """Every GET that needs neither a path parameter nor a required query."""
    spec = app.openapi()
    paths = []
    for path, operations in spec["paths"].items():
        if path.startswith("/api/v1"):
            continue  # a versioned alias of the same handlers
        get = operations.get("get")
        if get is None or "{" in path:
            continue
        if any(p.get("required") for p in get.get("parameters", [])):
            continue
        paths.append(path)
    return sorted(paths)


@pytest.fixture(scope="module")
def headers(client):
    email = "smoke@smoke-example.com"
    r = client.post("/api/auth/signup",
                    json={"email": email, "password": PASSWORD, "company_name": "Smoke"})
    if r.status_code != 200:
        r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    return {"Authorization": f"Bearer {r.json()['data']['access_token']}"}


@pytest.mark.parametrize("path", _no_arg_get_paths())
def test_a_get_endpoint_does_not_raise(client, headers, path):
    response = client.get(path, headers=headers)
    assert response.status_code != 500, f"{path} raised: {response.text[:300]}"


def test_the_smoke_list_is_not_accidentally_empty():
    """A filter bug here would make every test above pass by covering nothing."""
    assert len(_no_arg_get_paths()) > 20


# ── the three that were dead, named explicitly ──────────────────────────────

def test_the_slabs_screen_loads(client, headers):
    """`GET /api/rule-engine/slabs` passed an `entity` its signature never took."""
    r = client.get("/api/rule-engine/slabs?state=Karnataka&rule_type=PT", headers=headers)
    assert r.status_code == 200, r.text
    assert "slabs" in r.json()["data"]


def test_income_tax_compute_answers(client, headers):
    """`_year_cfg` read `entity.id` from a scope that only had `user`."""
    r = client.post("/api/income-tax/compute",
                    json={"annual_gross": 1200000, "regime": "new"}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["total_tax_annual"] >= 0


def test_income_tax_compare_answers(client, headers):
    r = client.post("/api/income-tax/compare",
                    json={"annual_gross": 1200000}, headers=headers)
    assert r.status_code == 200, r.text
    assert {"old", "new"} <= set(r.json()["data"])


def test_compensation_answers_on_a_workspace_with_no_register(client, headers):
    """
    The empty shape omitted `employees`, which the router masks on the way out.
    Every brand-new workspace got a 500 from the Compensation view.
    """
    r = client.get("/api/bi/compensation", headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["employees"] == []
    assert data["overall"]["count"] == 0
