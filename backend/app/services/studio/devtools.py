"""
The developer workspace: test the low-code pieces before they go into a
mapping, a rule or a workflow.

Everything here runs the same code the product runs — the whitelisted formula
evaluator (``formula_eval``), the mapping's number reading and lookups, the
workflow's condition test — against sample rows someone types or pastes. None
of it stores anything, and none of it can do more than those evaluators can:
arithmetic, comparisons and a handful of pure functions over the values given.

**Scripting is not here, on purpose.** See :data:`SCRIPTING`.
"""
from __future__ import annotations

import ast
from typing import Any

from app.services.formula_eval import ALLOWED_FUNCS, MAX_EXPRESSION_LENGTH, FormulaError, evaluate_formula
from app.services.studio import mapping as mapping_engine
from app.services.studio import workflows

MAX_SAMPLES = 200

#: Why arbitrary scripts cannot run, and what would have to be true first.
SCRIPTING: dict[str, Any] = {
    "enabled": False,
    "reason": (
        "Running someone's code safely needs genuine isolation: a separate, unprivileged process or micro-VM with "
        "no network, no database connection, no filesystem, no environment variables, and hard limits on CPU, "
        "memory, time and output. The production host is a single web service with no such sandbox; a script "
        "run there could read the database credentials and every company's payroll. Restricted Python "
        "(eval/exec with a trimmed namespace) is not isolation and is not offered."
    ),
    "requires": [
        "An isolated execution service (for example gVisor, Firecracker or a per-run container) outside the API process",
        "No network or database access from the sandbox; inputs passed in, outputs passed back, both size-capped",
        "CPU, memory and wall-clock limits enforced by the sandbox, not by the script",
        "Scripts versioned and released like mappings, with independent approval",
    ],
    "instead": "Formulas, conditions, lookups and mappings cover transformation without code, and are tested here.",
}

_FUNC_HELP = {
    "min": "the smallest of its arguments",
    "max": "the largest of its arguments",
    "abs": "the value without its sign",
    "round": "rounded (round(x) to a whole number, round(x, 2) to paise)",
    "floor": "rounded down to a whole number",
    "ceil": "rounded up to a whole number",
    "iff": "iff(condition, a, b): a when the condition holds, otherwise b",
}
_OPS = {ast.Add: "plus", ast.Sub: "minus", ast.Mult: "times", ast.Div: "divided by", ast.FloorDiv: "divided by (whole part)",
        ast.Mod: "remainder after dividing by", ast.Pow: "to the power of"}
_CMPS = {ast.Eq: "equals", ast.NotEq: "is not", ast.Lt: "is less than", ast.LtE: "is at most",
         ast.Gt: "is more than", ast.GtE: "is at least"}


def reference() -> dict[str, Any]:
    return {
        "functions": _FUNC_HELP,
        "operators": ["+", "-", "*", "/", "//", "%", "**", "==", "!=", "<", "<=", ">", ">=", "and", "or", "not",
                      "a if condition else b"],
        "not_allowed": ["attribute access (a.b)", "imports", "strings and lists", "calling anything but the functions "
                        "listed", "keyword arguments", "assignments, loops and lambdas"],
        "max_length": MAX_EXPRESSION_LENGTH,
        "variables": "Any numeric field of the sample row, by name. Nested fields are joined with _ "
                     "(job.salary becomes job_salary). A blank or missing field is absent — using it is an error, "
                     "never a zero.",
        "scripting": SCRIPTING,
    }


def _describe(node: ast.AST) -> str:
    if isinstance(node, ast.Expression):
        return _describe(node.body)
    if isinstance(node, ast.Constant):
        return repr(node.value)
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return f"({_describe(node.left)} {_OPS[type(node.op)]} {_describe(node.right)})"
    if isinstance(node, ast.UnaryOp):
        return ("minus " if isinstance(node.op, ast.USub) else "not " if isinstance(node.op, ast.Not) else "") \
            + _describe(node.operand)
    if isinstance(node, ast.Compare):
        parts = [_describe(node.left)]
        for op, right in zip(node.ops, node.comparators, strict=False):
            parts.append(f"{_CMPS.get(type(op), '?')} {_describe(right)}")
        return " ".join(parts)
    if isinstance(node, ast.BoolOp):
        joiner = " and " if isinstance(node.op, ast.And) else " or "
        return "(" + joiner.join(_describe(v) for v in node.values) + ")"
    if isinstance(node, ast.IfExp):
        return f"{_describe(node.body)} if {_describe(node.test)}, otherwise {_describe(node.orelse)}"
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        args = ", ".join(_describe(a) for a in node.args)
        name = node.func.id
        if name == "iff" and len(node.args) == 3:
            return f"{_describe(node.args[1])} if {_describe(node.args[0])}, otherwise {_describe(node.args[2])}"
        words = {"min": "the smaller of", "max": "the larger of", "abs": "the size of", "round": "rounded",
                 "floor": "rounded down", "ceil": "rounded up"}.get(name, name)
        return f"{words} ({args})"
    return "?"


def explain(expression: str) -> dict[str, Any]:
    """What an expression reads, what it calls, and what it means in words — or why it is refused."""
    expression = (expression or "").strip()
    out: dict[str, Any] = {"expression": expression, "ok": False}
    if not expression:
        out["error"] = "Type an expression."
        return out
    if len(expression) > MAX_EXPRESSION_LENGTH:
        out["error"] = f"Too long: {len(expression)} characters; the limit is {MAX_EXPRESSION_LENGTH}."
        return out
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        out["error"] = f"Not a valid expression: {exc.msg}."
        return out
    names, funcs = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            funcs.add(node.func.id)
        elif isinstance(node, ast.Name):
            names.add(node.id)
    variables = sorted(n for n in names if n not in funcs)
    # The evaluator is the judge of what is allowed: try it with every name set to 1.
    try:
        evaluate_formula(expression, dict.fromkeys(variables, 1.0))
    except FormulaError as exc:
        if "division" not in str(exc).lower():
            out["error"] = str(exc)
            out["variables"] = variables
            return out
    except ZeroDivisionError:
        pass  # dividing by a variable that happens to be 1 - 1: allowed syntax, a data question
    unknown = sorted(f for f in funcs if f not in ALLOWED_FUNCS)
    if unknown:
        out["error"] = f"Not an allowed function: {', '.join(unknown)}."
        return out
    out.update({"ok": True, "variables": variables, "functions": sorted(funcs), "in_words": _describe(tree)})
    return out


def test_formula(expression: str, samples: list[Any]) -> dict[str, Any]:
    """Evaluate against each sample row, exactly as a mapping formula would read it."""
    info = explain(expression)
    if not info["ok"]:
        return {**info, "results": []}
    results = []
    for i, row in enumerate(samples[:MAX_SAMPLES], start=1):
        if not isinstance(row, dict):
            results.append({"row": i, "error": "A sample row must be an object."})
            continue
        variables = mapping_engine._formula_vars(row)  # noqa: SLF001 — the same reading the mapping uses
        missing = [v for v in info["variables"] if v not in variables]
        if missing:
            results.append({"row": i, "error": f"{', '.join(missing)} is blank, missing or not a number in this row. "
                                                "Absent is not zero: the formula does not run.", "missing": missing})
            continue
        try:
            value = evaluate_formula(expression, variables)
            results.append({"row": i, "value": round(value, 6), "inputs": {v: variables[v] for v in info["variables"]}})
        except (FormulaError, ZeroDivisionError) as exc:
            results.append({"row": i, "error": str(exc) or "Division by zero."})
    return {**info, "results": results, "truncated": len(samples) > MAX_SAMPLES}


def test_conditions(conditions: list[dict[str, Any]], samples: list[Any]) -> dict[str, Any]:
    """Workflow-style conditions against sample events: which hold, and what each read."""
    for i, c in enumerate(conditions, start=1):
        if not isinstance(c, dict) or not c.get("field"):
            return {"ok": False, "error": f"Condition {i} needs a field."}
        if c.get("op", "eq") not in workflows.OPS:
            return {"ok": False, "error": f"Condition {i}: operator is one of {', '.join(workflows.OPS)}."}
    results = []
    for i, event in enumerate(samples[:MAX_SAMPLES], start=1):
        subject = event if isinstance(event, dict) else {}
        each = [{"field": c["field"], "op": c.get("op", "eq"), "value": c.get("value"),
                 "actual": workflows.dig(subject, c["field"]), "holds": workflows.condition_holds(c, subject)}
                for c in conditions]
        results.append({"row": i, "holds": all(e["holds"] for e in each), "conditions": each})
    return {"ok": True, "results": results}


def test_lookup(table: dict[str, Any], values: list[Any], on_unmatched: str = "reject") -> dict[str, Any]:
    """A lookup table against sample values, with the mapping's own matching and unmatched policy."""
    if on_unmatched not in ("reject", "keep", "blank"):
        return {"ok": False, "error": "If unmatched is reject, keep or blank."}
    spec = {"fields": [{"target": "extra.value", "source": "v", "lookup": {str(k): v for k, v in (table or {}).items()},
                        "on_unmatched": on_unmatched}]}
    try:
        spec = mapping_engine.check_spec({"fields": [
            {"target": "employee_id", "source": "id", "type": "id"}, *spec["fields"]]}, "employee_master")
    except mapping_engine.SpecError as exc:
        return {"ok": False, "error": str(exc)}
    out = []
    for i, value in enumerate(values[:MAX_SAMPLES], start=1):
        m = mapping_engine.apply_one(spec, {"id": "x", "v": value}, i)
        if m.errors:
            out.append({"row": i, "value": value, "error": m.errors[0]["message"]})
        else:
            got = ((m.output or {}).get("_extra") or {}).get("value")
            keys = {str(k).strip() for k in (table or {})}
            out.append({"row": i, "value": value, "result": got, "matched": str(value).strip() in keys})
    return {"ok": True, "results": out}
