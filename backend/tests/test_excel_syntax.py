"""
Excel-style formulas in the expression boxes.

The sandboxes are unchanged; ``excel_syntax`` only rewrites text into the Python
subset they already evaluate. These tests pin what people type in a spreadsheet
and what they are told when they get it wrong. The hostile-input cases live in
``test_expression_safety.py`` and still pass, which is the point.
"""
from __future__ import annotations

import pytest

from app.services.config_service import safe_eval_expr
from app.services.excel_syntax import ExpressionSyntaxError, normalise_name, translate
from app.services.formula_eval import FormulaError, evaluate_formula

V = {"basic": 20000, "special_allowance": 10000, "other_allowance": 1000,
     "gross": 25000, "pf_wage": 20000, "esic_wage": 18000, "x": 0}


@pytest.mark.parametrize("expression,expected", [
    # the formula from a real support request, and its variants
    ("if(basic<=25000, min((basic+special_allowance)*12%, 3000), basic*12%)", 3000),
    ("IF(basic<=25000, MIN((basic+special_allowance)*12%, 3000), basic*12%)", 3000),
    ("=IF(Basic <= 25000, MIN(([Basic] + [Special Allowance]) * 12%, 3000), basic * 12%)", 3000),
    ("IF(basic<=25000, MIN((basic+special_allowance+other_allowance)*12%, 3000), basic*12%)", 3000),
    ("IF(basic>25000, 1, basic*12%)", 2400),
    ("MIN(basic, 25000) * 12%", 2400),
    # percent, remainder, power
    ("12%", 0.12), ("200 * 12%", 24), ("(basic + other_allowance)%", 210), ("min(1, 2)%", 0.01),
    ("10 % 3", 1), ("10 %3", 1), ("2 ^ 10", 1024), ("2 ** 10", 1024),
    # comparison and logic
    ("IF(basic = 20000, 1, 0)", 1), ("IF(basic <> 20000, 1, 0)", 0),
    ("IF(AND(basic > 1, gross > 1), 1, 0)", 1), ("IF(OR(basic > 99999, gross > 1), 1, 0)", 1),
    ("IF(NOT(basic > 99999), 1, 0)", 1), ("IF(basic > 1 AND gross > 1, 1, 0)", 1),
    ("IF(TRUE, 5, 6)", 5),
    # rounding
    ("ROUNDUP(gross * 0.75%, 0)", 188), ("ROUNDDOWN(gross * 0.75%, 0)", 187),
    ("ROUND_HALF_UP(2.5)", 3), ("ROUNDUP(0.1 + 0.2, 1)", 0.3), ("ROUNDUP(-1.2, 0)", -2),
    ("MOD(10, 3)", 1),
    # Python spellings that always worked
    ("gross * 0.0075 if gross <= 21000 else 0", 0), ("iff(gross <= 21000, gross * 0.0075, 0)", 0),
    ("esic_wage > 0 and esic_wage <= 21000", 1),
])
def test_what_payroll_people_type_in_a_spreadsheet_works(expression, expected):
    assert evaluate_formula(expression, V) == pytest.approx(expected)


def test_field_names_ignore_case_spaces_and_underscores():
    for ref in ("special_allowance", "SPECIAL_ALLOWANCE", "Special_Allowance", "[Special Allowance]", "[special allowance]"):
        assert evaluate_formula(ref, V) == 10000
    assert normalise_name("Special Allowance") == normalise_name("special_allowance")


def test_if_only_evaluates_the_branch_it_takes():
    assert evaluate_formula("IF(x = 0, 0, 100 / x)", V) == 0


@pytest.mark.parametrize("expression,fragment", [
    ("if(basic<=25000, min((basic+special_allowance*12%, 3000), basic*12%)", "never closed"),
    ("basic + (2", "never closed"),
    ("basic + 2)", "no matching"),
    ("min(basicc, 3)", "Did you mean: basic"),
    ("SUMM(basic)", "Unknown function"),
    ("basic +", "Syntax error"),
    ("basic special_allowance", "Syntax error"),
    ("gross.real", "Unexpected character '.'"),
    ("IF(basic > 1, 2)", "three parts"),
])
def test_a_mistake_says_what_is_wrong(expression, fragment):
    with pytest.raises(FormulaError) as err:
        evaluate_formula(expression, V)
    assert fragment in str(err.value)


def test_the_unclosed_bracket_error_points_at_it():
    with pytest.raises(ExpressionSyntaxError) as err:
        translate("if(basic<=25000, min((basic+special_allowance*12%, 3000), basic*12%)")
    assert err.value.position == 3  # the "(" of the if(


def test_the_statutory_expression_box_gets_the_same_spellings():
    ctx = {"esic_wage": 18000, "esic_ceiling": 21000, "employee_type": "permanent"}
    assert safe_eval_expr("AND(esic_wage > 0, esic_wage <= esic_ceiling)", ctx) is True
    assert safe_eval_expr("IF(esic_wage <= esic_ceiling, 1, 0)", ctx) == 1
    assert safe_eval_expr("esic_wage = 18000", ctx) is True
    assert safe_eval_expr("employee_type <> 'contractor'", ctx) is True
    assert safe_eval_expr("employee_type != 'contractor'", ctx) is True
    assert safe_eval_expr("CEIL(esic_wage * 0.75%)", ctx) == 135


def test_translation_leaves_existing_python_expressions_alone():
    for e in ("min(pf_wage, 15000) * 0.12", "gross * 0.0075 if gross <= 21000 else 0",
              "esic_wage > 0 and esic_wage <= esic_ceiling", "not (a > 1)"):
        names = {"pf_wage", "gross", "esic_wage", "esic_ceiling", "a"}
        assert translate(e, names).replace(" ", "") == e.replace(" ", "")


def test_dividing_by_zero_is_left_to_the_caller():
    # Dashboards and the matrix treat it as "unknown", so it must keep propagating.
    with pytest.raises(ZeroDivisionError):
        evaluate_formula("100 / 0", V)
