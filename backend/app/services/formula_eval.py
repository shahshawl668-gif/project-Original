"""Safe formula evaluator for the Rule Engine.

Supports a small expression language so users can write things like:

    min(pf_wage, 15000) * 0.12
    IF(gross <= 21000, gross * 0.0075, 0)            # Excel style
    IF(basic <= 25000, MIN((basic + special_allowance) * 12%, 3000), basic * 12%)
    gross * 0.0075 if gross <= 21000 else 0          # Python style still works

Spreadsheet spellings (``IF``, ``12%``, ``=``, ``AND(...)``, any-case names,
``[Field Name]``) are rewritten to the Python subset by ``excel_syntax`` before
parsing; that module only rewrites text. Only a fixed set of operators and pure
functions is allowed; no attribute access, no imports, no name lookups outside
the supplied variables.
"""
from __future__ import annotations

import ast
import difflib
import operator
from decimal import ROUND_DOWN, ROUND_HALF_UP, ROUND_UP, Decimal
from typing import Any
from collections.abc import Callable

from app.services.excel_syntax import ExpressionSyntaxError, translate

class FormulaError(ValueError):
    pass


# An expression is stored by a tenant and evaluated once per employee per run,
# so its cost has to be bounded before it is parsed. The cap also bounds every
# derived size — nesting depth, the number of nodes, the length of any string
# literal — because none of them can exceed the source they came from.
MAX_EXPRESSION_LENGTH = 2000


def safe_power(base: Any, exponent: Any) -> float:
    """
    Exponentiation in floating point, always.

    ``9 ** 9 ** 9 ** 9`` evaluated over integers is an allocation large enough
    to take the process down, and it is three keystrokes in an expression box a
    tenant can edit. Floats overflow in constant time instead, so the same
    expression fails immediately rather than consuming the machine.

    The cost is exactness above 2^53, which no payroll formula needs.
    """
    try:
        result = float(base) ** float(exponent)
    except OverflowError as exc:
        raise FormulaError("Result of ** is too large") from exc
    except ZeroDivisionError as exc:
        raise FormulaError("Cannot raise zero to a negative power") from exc
    except (TypeError, ValueError) as exc:
        raise FormulaError("** needs numbers on both sides") from exc
    # A negative base with a fractional exponent gives a complex number, which
    # is not a payroll figure.
    if isinstance(result, complex):
        raise FormulaError("** produced a complex number")
    return result


def _quantise(value: Any, digits: Any, mode: str) -> float:
    """Round like a spreadsheet: ROUNDUP / ROUNDDOWN / half-away-from-zero.

    Goes through Decimal on a value trimmed to 9 places, so ``0.1 + 0.2``
    rounds up to ``0.3`` rather than ``0.31`` — the float noise is not payroll.
    """
    try:
        n = int(digits)
        x = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise FormulaError("Rounding needs numbers") from exc
    if not -9 <= n <= 9:
        raise FormulaError("Rounding supports between -9 and 9 decimal places")
    return float(Decimal(repr(round(x, 9))).quantize(Decimal(1).scaleb(-n), rounding=mode))


def _roundup(value: Any, digits: Any = 0) -> float:
    return _quantise(value, digits, ROUND_UP)


def _rounddown(value: Any, digits: Any = 0) -> float:
    return _quantise(value, digits, ROUND_DOWN)


def _round_half_up(value: Any, digits: Any = 0) -> float:
    return _quantise(value, digits, ROUND_HALF_UP)


ALLOWED_FUNCS: dict[str, Callable[..., Any]] = {
    "min": min,
    "max": max,
    "abs": abs,
    "round": round,
    "floor": lambda x: int(x // 1) if x >= 0 else -int((-x) // 1) - (1 if (-x) % 1 else 0),
    "ceil": lambda x: int(x // 1) + (1 if x % 1 else 0),
    # Named `iff`, not `if`: `if(...)` is a syntax error before this map is ever
    # consulted, because `if` is a Python keyword. The entry that used to be
    # here was unreachable, and the example in the docstring above — which used
    # it — had never worked.
    "iff": lambda cond, a, b: a if cond else b,
    # Spreadsheet functions. ``round`` above keeps Python's round-half-to-even
    # so existing formulas give the same numbers; ``round_half_up`` is Excel's ROUND.
    "roundup": _roundup,
    "rounddown": _rounddown,
    "round_half_up": _round_half_up,
    "mod": operator.mod,
    "and_": lambda *args: all(args),
    "or_": lambda *args: any(args),
}

BIN_OPS: dict[type, Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: safe_power,
}

UNARY_OPS: dict[type, Callable[[Any], Any]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
    ast.Not: operator.not_,
}

CMP_OPS: dict[type, Callable[[Any, Any], bool]] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}

BOOL_OPS = {ast.And: all, ast.Or: any}


def _eval(node: ast.AST, vars: dict[str, Any]) -> Any:
    if isinstance(node, ast.Expression):
        return _eval(node.body, vars)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float, bool)):
            return node.value
        raise FormulaError(f"Unsupported literal: {type(node.value).__name__}")
    if isinstance(node, ast.Name):
        if node.id in vars:
            return vars[node.id]
        if node.id in ALLOWED_FUNCS:
            return ALLOWED_FUNCS[node.id]
        near = difflib.get_close_matches(node.id, list(vars), n=3, cutoff=0.6)
        raise FormulaError(f"Unknown variable: {node.id}" + (f". Did you mean: {', '.join(near)}?" if near else ""))
    if isinstance(node, ast.BinOp):
        op = BIN_OPS.get(type(node.op))
        if op is None:
            raise FormulaError(f"Operator not allowed: {type(node.op).__name__}")
        return op(_eval(node.left, vars), _eval(node.right, vars))
    if isinstance(node, ast.UnaryOp):
        op = UNARY_OPS.get(type(node.op))
        if op is None:
            raise FormulaError(f"Operator not allowed: {type(node.op).__name__}")
        return op(_eval(node.operand, vars))
    if isinstance(node, ast.Compare):
        left = _eval(node.left, vars)
        for op_node, comparator in zip(node.ops, node.comparators, strict=False):
            op = CMP_OPS.get(type(op_node))
            if op is None:
                raise FormulaError(f"Comparison not allowed: {type(op_node).__name__}")
            right = _eval(comparator, vars)
            if not op(left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.BoolOp):
        agg = BOOL_OPS.get(type(node.op))
        if agg is None:
            raise FormulaError("Boolean op not allowed")
        return agg(_eval(v, vars) for v in node.values)
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id == "iff":
            # Lazy, like a spreadsheet IF: only the branch that is taken is
            # evaluated, so IF(x = 0, 0, 100 / x) does not divide by zero.
            if node.keywords or len(node.args) != 3:
                raise FormulaError("IF needs three parts: IF(condition, value_if_true, value_if_false)")
            return _eval(node.args[1], vars) if _eval(node.args[0], vars) else _eval(node.args[2], vars)
        if isinstance(node.func, ast.Name) and node.func.id not in vars and node.func.id not in ALLOWED_FUNCS:
            near = difflib.get_close_matches(node.func.id, list(ALLOWED_FUNCS), n=2, cutoff=0.6)
            raise FormulaError(
                f"Unknown function '{node.func.id}'."
                + (f" Did you mean {' or '.join(near)}?" if near else "")
                + f" Available: {', '.join(sorted(ALLOWED_FUNCS))}."
            )
        func = _eval(node.func, vars)
        if not callable(func) or func not in ALLOWED_FUNCS.values():
            raise FormulaError("Function not allowed")
        args = [_eval(a, vars) for a in node.args]
        if node.keywords:
            raise FormulaError("Keyword arguments not allowed")
        return func(*args)
    if isinstance(node, ast.IfExp):
        return _eval(node.body, vars) if _eval(node.test, vars) else _eval(node.orelse, vars)
    raise FormulaError(f"Syntax not allowed: {type(node).__name__}")


def evaluate_formula(expression: str, variables: dict[str, Any]) -> float:
    if not expression or not expression.strip():
        raise FormulaError("Empty expression")
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise FormulaError(
            f"Expression is too long ({len(expression)} characters; "
            f"the limit is {MAX_EXPRESSION_LENGTH})"
        )
    try:
        source = translate(expression, variables.keys())
    except ExpressionSyntaxError as e:
        raise FormulaError(str(e)) from e
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError as e:
        raise FormulaError(
            f"Syntax error: {e.msg}. Check the brackets, the commas between the parts of a "
            "function, and that every + - * / has a value on both sides."
        ) from e
    except (MemoryError, RecursionError) as e:
        raise FormulaError("Expression is nested too deeply") from e
    try:
        result = _eval(tree, variables)
    except RecursionError as e:
        # The walk is recursive, so depth is bounded by the interpreter rather
        # than by us. Surfacing it as a 400 beats a 500 on a stack overflow.
        raise FormulaError("Expression is nested too deeply") from e
    except FormulaError:
        raise
    except (TypeError, ValueError, OverflowError) as e:
        raise FormulaError(f"The formula could not be calculated: {e}") from e
    if isinstance(result, bool):
        return float(int(result))
    if isinstance(result, (int, float)):
        return float(result)
    raise FormulaError("Formula must return a number")


def evaluate_conditions(conditions: list[dict[str, Any]], variables: dict[str, Any]) -> bool:
    """All conditions must pass (AND). Each: {field, operator, value}."""
    if not conditions:
        return True
    for c in conditions:
        field = c.get("field")
        op = c.get("operator")
        val = c.get("value")
        if field not in variables:
            raise FormulaError(f"Condition uses unknown field: {field}")
        try:
            lhs = float(variables[field])
            rhs = float(val)
        except (TypeError, ValueError) as e:
            raise FormulaError(f"Condition value not numeric: {field} {op} {val}") from e
        cmp = CMP_OPS.get(
            {
                ">": ast.Gt,
                "<": ast.Lt,
                ">=": ast.GtE,
                "<=": ast.LtE,
                "==": ast.Eq,
                "!=": ast.NotEq,
            }.get(op, type(None))
        )
        if cmp is None:
            raise FormulaError(f"Unsupported operator: {op}")
        if not cmp(lhs, rhs):
            return False
    return True
