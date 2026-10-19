"""
The formula builder knows the company's own salary components.

Before this, a formula could only use ten fixed names, so a company whose PF
or ESIC wage included ``special_allowance`` or any other component could not
write its rule at all: "Unknown variable".
"""
from __future__ import annotations

import pytest

PASSWORD = "Passw0rd!x"
PF_FORMULA = "IF(basic <= 25000, MIN((basic + special_allowance) * 12%, 3000), basic * 12%)"


@pytest.fixture()
def workspace(client, request):
    email = f"{request.node.name[:40]}@formula-vars.com".replace("_", "-")
    r = client.post("/api/auth/signup", json={"email": email, "password": PASSWORD, "company_name": "Formula Vars"})
    if r.status_code != 200:
        r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    headers = {"Authorization": f"Bearer {r.json()['data']['access_token']}"}
    entity_id = client.post("/api/org/entities", json={"name": f"F-{request.node.name[:26]}"},
                            headers=headers).json()["data"]["id"]
    return {**headers, "X-Entity-Id": entity_id}


def _add_component(client, workspace, name):
    r = client.post("/api/components", json={"component_name": name, "pf_applicable": True}, headers=workspace)
    assert r.status_code in (200, 201), r.text


def _test(client, workspace, expression, variables=None):
    r = client.post("/api/rule-engine/test-formula",
                    json={"expression": expression, "variables": variables or {}, "conditions": []},
                    headers=workspace)
    assert r.status_code == 200, r.text
    return r.json()["data"]


def test_the_variables_endpoint_lists_built_ins_and_the_companys_components(client, workspace):
    _add_component(client, workspace, "Special Allowance")
    _add_component(client, workspace, "Shift Allowance")
    data = client.get("/api/rule-engine/variables", headers=workspace).json()["data"]
    assert {"basic", "pf_wage", "gross"} <= {v["key"] for v in data["inputs"]}
    keys = {c["key"]: c["label"] for c in data["components"]}
    assert keys == {"shift_allowance": "Shift Allowance", "special_allowance": "Special Allowance"}


def _save_pf(client, headers, expression):
    pf = client.get("/api/config/statutory/pf", headers=headers).json()["data"]
    pf["employee_formula"] = expression
    return client.put("/api/config/statutory/pf", headers=headers, json=pf)


def test_a_component_formula_with_excel_syntax_tests_and_saves(client, workspace):
    _add_component(client, workspace, "Special Allowance")
    out = _test(client, workspace, PF_FORMULA, {"basic": 20000, "special_allowance": 10000})
    assert out["ok"] is True and out["result"] == 3000
    out = _test(client, workspace, PF_FORMULA, {"basic": 30000, "special_allowance": 10000})
    assert out["result"] == 3600  # above 25,000: basic * 12%, no cap
    assert _save_pf(client, workspace, PF_FORMULA).status_code == 200


def test_square_bracket_and_any_case_names_resolve_to_the_component(client, workspace):
    _add_component(client, workspace, "Special Allowance")
    out = _test(client, workspace, "=[Special Allowance] + BASIC", {"basic": 1, "special_allowance": 2})
    assert out["ok"] and out["result"] == 3


def test_a_component_that_is_not_configured_says_where_to_add_it(client, workspace):
    out = _test(client, workspace, "basic + travel_allowance", {"basic": 1})
    assert out["ok"] is False
    assert "travel_allowance" in out["error"] and "Salary components" in out["error"]
    saved = _save_pf(client, workspace, "basic + travel_allowance")
    assert saved.status_code == 400
    assert "Salary components" in str(saved.json()["error"])


def test_the_original_typo_is_explained_not_just_rejected(client, workspace):
    _add_component(client, workspace, "Special Allowance")
    out = _test(client, workspace, "if(basic<=25000, min((basic+special_allowance*12%, 3000), basic*12%)")
    assert out["ok"] is False and "never closed" in out["error"]


def test_the_preset_expressions_the_page_ships_all_evaluate(client, workspace):
    for expression in ("MIN(pf_wage, 25000) * 12%", "IF(gross <= 21000, ROUNDUP(gross * 0.75%, 0), 0)",
                       "min(pf_wage, 15000) * 0.12", "if(gross <= 21000, gross * 0.0075, 0)"):
        assert _test(client, workspace, expression, {"pf_wage": 20000, "gross": 20000})["ok"], expression


def test_a_formula_that_divides_by_a_field_is_valid_to_save(client, workspace):
    """Checked with sample inputs, so a field being 0 somewhere is not a syntax error."""
    out = _test(client, workspace, "basic / 30 * paid_days")
    assert out["ok"] is True
    assert _save_pf(client, workspace, "gross / basic").status_code == 200
    zero = _test(client, workspace, "100 / basic", {"basic": 0})
    assert zero["ok"] is False and "Division by zero" in zero["error"]
