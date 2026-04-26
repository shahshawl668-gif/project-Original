"""Safe formula evaluator for the Rule Engine.

Supports a small expression language so users can write things like:

    min(pf_wage, 15000) * 0.12
    if(gross <= 21000, gross * 0.0075, 0)

Only a fixed set of operators and pure functions is allowed; no
attribute access, no imports, no name lookups outside the supplied
variables.
"""
from __future__ import annotations

import ast
import operator
from typing import Any, Callable

ALLOWED_FUNCS: dict[str, Callable[..., Any]] = {
    "min": min,
    "max": max,
    "abs": abs,
    "round": round,
    "floor": lambda x: int(x // 1) if x >= 0 else -int((-x) // 1) - (1 if (-x) % 1 else 0),
    "ceil": lambda x: int(x // 1) + (1 if x % 1 else 0),
    "if": lambda cond, a, b: a if cond else b,
}

BIN_OPS: dict[type, Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
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


class FormulaError(ValueError):
    pass


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
        raise FormulaError(f"Unknown variable: {node.id}")
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
        for op_node, comparator in zip(node.ops, node.comparators):
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
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as e:
        raise FormulaError(f"Syntax error: {e.msg}") from e
    result = _eval(tree, variables)
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
