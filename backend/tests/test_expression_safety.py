"""
The two expression sandboxes.

Both evaluate strings a tenant can edit, and one of them is reachable from an
endpoint that only requires being logged in. That makes them the highest-value
attack surface in the product, so this suite is mostly about what they must
refuse.

The denial-of-service tests assert on **wall clock**, not on which exception
comes back. An evaluator that eventually raises after eating four gigabytes has
not been fixed, and only a clock can tell the difference.
"""
from __future__ import annotations

import time
import uuid

import pytest

from app.database import SessionLocal
from app.models import Entity, User
from app.services.config_service import safe_eval_expr
from app.services.formula_eval import (
    MAX_EXPRESSION_LENGTH,
    FormulaError,
    evaluate_formula,
    safe_power,
)

PASSWORD = "Passw0rd!x"

# Anything the sandbox rejects should be rejected in about the time it takes to
# walk the tree. A second is three orders of magnitude of headroom.
BUDGET_SECONDS = 1.0

CTX = {"esic_wage": 1000, "esic_ceiling": 21000, "employee_type": "permanent"}
VARS = {"pf_wage": 20000, "gross": 50000, "basic": 25000}


def _timed(fn, *args):
    """Run it, return (raised, seconds)."""
    started = time.monotonic()
    try:
        fn(*args)
        raised = None
    except Exception as exc:  # noqa: BLE001 — the type is the thing under test
        raised = exc
    return raised, time.monotonic() - started


# ── denial of service ───────────────────────────────────────────────────────

BOMBS = [
    "9**9**9**9",
    "2**10000000",
    "10**10**10",
    "(2**64)**64",
]


@pytest.mark.parametrize("expression", BOMBS)
def test_an_exponent_bomb_fails_immediately_in_the_formula_evaluator(expression):
    raised, seconds = _timed(evaluate_formula, expression, VARS)
    assert isinstance(raised, FormulaError), f"{expression} was evaluated, not refused"
    assert seconds < BUDGET_SECONDS, f"{expression} took {seconds:.2f}s"


@pytest.mark.parametrize("expression", BOMBS)
def test_an_exponent_bomb_fails_immediately_in_the_config_evaluator(expression):
    raised, seconds = _timed(safe_eval_expr, expression, CTX)
    assert isinstance(raised, ValueError), f"{expression} was evaluated, not refused"
    assert seconds < BUDGET_SECONDS, f"{expression} took {seconds:.2f}s"


@pytest.mark.parametrize("expression", [
    "'a' * 100000000",
    "str('a' * 100000000)",
    "'ab' * 50000000",
])
def test_a_string_cannot_be_multiplied_into_a_memory_bomb(expression):
    """
    Strings stay legal as values — an eligibility expression compares
    ``employee_type != 'contractor'`` — but never as arithmetic operands.
    """
    raised, seconds = _timed(safe_eval_expr, expression, CTX)
    assert isinstance(raised, ValueError)
    assert "needs a number" in str(raised)
    assert seconds < BUDGET_SECONDS


def test_a_long_expression_is_refused_before_it_is_parsed():
    long_one = "1+" * MAX_EXPRESSION_LENGTH + "1"
    for evaluate, error in ((evaluate_formula, FormulaError), (safe_eval_expr, ValueError)):
        raised, seconds = _timed(evaluate, long_one, VARS)
        assert isinstance(raised, error)
        assert "too long" in str(raised)
        assert seconds < BUDGET_SECONDS


def test_deep_nesting_is_a_bad_request_not_a_stack_overflow():
    nested = "(" * 400 + "1" + ")" * 400
    for evaluate, error in ((evaluate_formula, FormulaError), (safe_eval_expr, ValueError)):
        raised, _ = _timed(evaluate, nested, VARS)
        # Either it parses and evaluates to 1, or it is refused cleanly. What it
        # must never do is escape as a RecursionError.
        assert raised is None or isinstance(raised, error), repr(raised)


# ── escaping the sandbox ────────────────────────────────────────────────────

ESCAPES = [
    "__import__('os').system('id')",
    "().__class__",
    "(1).__class__.__bases__",
    "gross.__class__",
    "[x for x in (1, 2)]",
    "(lambda: 1)()",
    "open('/etc/passwd')",
    "gross[0]",
    "{'a': 1}",
    "f'{gross}'",
    "exec('1')",
    "eval('1')",
    "globals()",
    "print(1)",
]


@pytest.mark.parametrize("expression", ESCAPES)
def test_the_formula_evaluator_refuses_every_escape(expression):
    raised, _ = _timed(evaluate_formula, expression, VARS)
    assert raised is not None, f"{expression} evaluated"
    assert isinstance(raised, FormulaError), f"{expression} raised {type(raised).__name__}"


@pytest.mark.parametrize("expression", ESCAPES)
def test_the_config_evaluator_refuses_every_escape(expression):
    raised, _ = _timed(safe_eval_expr, expression.replace("gross", "esic_wage"), CTX)
    assert raised is not None, f"{expression} evaluated"
    assert isinstance(raised, ValueError), f"{expression} raised {type(raised).__name__}"


def test_a_callable_smuggled_through_the_context_is_still_refused():
    """
    The allow-list is a property of the evaluator, not of every caller.

    Today no caller puts a callable in the context. This asserts that the day
    one does, it is still not a way to call anything.
    """
    raised, _ = _timed(safe_eval_expr, "danger()", {**CTX, "danger": lambda: "escaped"})
    assert isinstance(raised, ValueError)
    assert "Function not allowed" in str(raised)


def test_keyword_arguments_are_refused():
    for evaluate, error in ((evaluate_formula, FormulaError), (safe_eval_expr, ValueError)):
        raised, _ = _timed(evaluate, "round(1.5, ndigits=1)", VARS)
        assert isinstance(raised, error)


def test_an_unknown_name_is_refused_rather_than_resolved():
    for evaluate, error in ((evaluate_formula, FormulaError), (safe_eval_expr, ValueError)):
        raised, _ = _timed(evaluate, "secret_key", VARS)
        assert isinstance(raised, error)


# ── the arithmetic that must keep working ───────────────────────────────────

@pytest.mark.parametrize("expression,expected", [
    ("min(pf_wage, 15000) * 0.12", 1800.0),
    ("gross * 0.0075 if gross <= 21000 else 0", 0.0),
    ("iff(gross <= 21000, gross * 0.0075, 0)", 0.0),
    ("iff(gross > 21000, 1, 2)", 1.0),
    ("max(basic, 10000)", 25000.0),
    ("round(gross / 3)", 16667.0),
    ("ceil(gross * 0.0075)", 375.0),
    ("floor(basic / 7)", 3571.0),
    ("2 ** 10", 1024.0),
    ("-basic", -25000.0),
    ("gross - basic", 25000.0),
])
def test_real_payroll_formulas_still_evaluate(expression, expected):
    assert evaluate_formula(expression, VARS) == pytest.approx(expected)


@pytest.mark.parametrize("expression,expected", [
    ("esic_wage > 0 and esic_wage <= esic_ceiling", True),
    ("employee_type != 'contractor'", True),
    ("employee_type == 'permanent'", True),
    ("ceil(esic_wage * 0.0075)", 8),
    ("min(esic_wage, esic_ceiling)", 1000),
    ("esic_wage if esic_wage < esic_ceiling else esic_ceiling", 1000),
    ("2 ** 10", 1024.0),
])
def test_the_shipped_statutory_expressions_still_evaluate(expression, expected):
    assert safe_eval_expr(expression, CTX) == expected


def test_the_conditional_the_docstring_advertises_actually_parses():
    """`if(...)` was a syntax error before the map was ever consulted."""
    with pytest.raises(FormulaError):
        evaluate_formula("if(gross > 1, 1, 0)", VARS)
    assert evaluate_formula("iff(gross > 1, 1, 0)", VARS) == 1.0


def test_not_works_now_that_it_is_wired_to_an_operator():
    """It was mapped to None, so every `not` was an "unsupported unary op"."""
    assert safe_eval_expr("not (esic_wage > 999999)", CTX) is True
    assert safe_eval_expr("not (esic_wage > 0)", CTX) is False


@pytest.mark.parametrize("base,exponent,expected", [
    (2, 10, 1024.0),
    (10, -2, 0.01),
    (1.05, 12, 1.7958563260221301),
])
def test_ordinary_powers_are_unaffected(base, exponent, expected):
    assert safe_power(base, exponent) == pytest.approx(expected)


@pytest.mark.parametrize("base,exponent", [(-8, 0.5), (0, -1)])
def test_a_power_with_no_real_answer_is_refused(base, exponent):
    with pytest.raises(FormulaError):
        safe_power(base, exponent)


# ── through the endpoints that anyone logged in can reach ───────────────────

@pytest.fixture()
def workspace(client, request):
    email = f"{request.node.name[:40]}@expr-example.com".replace("_", "-")
    r = client.post("/api/auth/signup",
                    json={"email": email, "password": PASSWORD, "company_name": "Expression Tests"})
    if r.status_code != 200:
        r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    headers = {"Authorization": f"Bearer {r.json()['data']['access_token']}"}
    entity_id = client.post("/api/org/entities", json={"name": f"E-{request.node.name[:26]}"},
                            headers=headers).json()["data"]["id"]
    return {**headers, "X-Entity-Id": entity_id}


def test_the_formula_test_endpoint_refuses_a_bomb_quickly(client, workspace):
    started = time.monotonic()
    r = client.post("/api/rule-engine/test-formula",
                    json={"expression": "9**9**9**9", "variables": {}, "conditions": []},
                    headers=workspace)
    elapsed = time.monotonic() - started
    assert r.status_code == 200
    assert r.json()["data"]["ok"] is False
    assert elapsed < BUDGET_SECONDS * 5, f"took {elapsed:.2f}s"


def test_the_expression_test_endpoint_refuses_a_bomb_quickly(client, workspace):
    started = time.monotonic()
    r = client.post("/api/config/statutory/test-expression",
                    json={"expression": "9**9**9**9", "context": {}},
                    headers=workspace)
    elapsed = time.monotonic() - started
    assert r.status_code == 200
    assert r.json()["data"]["eval_ok"] is False
    assert elapsed < BUDGET_SECONDS * 5, f"took {elapsed:.2f}s"


def test_the_endpoints_still_evaluate_a_real_formula(client, workspace):
    r = client.post("/api/rule-engine/test-formula",
                    json={"expression": "min(pf_wage, 15000) * 0.12",
                          "variables": {"pf_wage": 20000}, "conditions": []},
                    headers=workspace)
    assert r.json()["data"]["result"] == pytest.approx(1800.0)

    r = client.post("/api/config/statutory/test-expression",
                    json={"expression": "esic_wage * 0.0075", "context": {"esic_wage": 1000}},
                    headers=workspace)
    assert r.json()["data"]["result"] == pytest.approx(7.5)
