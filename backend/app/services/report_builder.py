"""Controlled Report Builder dataset: BI payroll cost at period × dimension grain.

No SQL or arbitrary Python from definitions. All money is costed by the shared
analytics service; calculated fields evaluate a restricted arithmetic AST.
"""
from __future__ import annotations

import ast
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from app.services.analytics import cost_analysis
from app.services.cost_model import DERIVED_LABELS
from app.services.dimensions import DIMENSION_KEYS, DIMENSION_LABELS

MEASURE_FIELDS = ("gross", "deductions", "net", "employer_cost", "ctc")
FIELDS = ("period", "dimension", "headcount", "person_months", "cost_per_head", *MEASURE_FIELDS)
NUMERIC = set(FIELDS) - {"period", "dimension"}
LABELS = {
    "period": "Payroll period", "dimension": "Breakdown",
    "headcount": "People paid", "person_months": "Person-months",
    "cost_per_head": "Monthly cost per head",
    **{key: DERIVED_LABELS.get(key, key.replace("_", " ").title()) for key in MEASURE_FIELDS},
}
LABELS["net"] = "Net pay"
MAX_PREVIEW_ROWS = 200


def dataset_catalogue() -> list[dict]:
    return [{
        "key": "payroll_cost", "label": "Payroll cost",
        "grain": "Payroll period × one configured company dimension",
        "fields": [{"key": key, "label": LABELS[key], "numeric": key in NUMERIC} for key in FIELDS],
        "dimensions": [{"key": key, "label": DIMENSION_LABELS[key]} for key in DIMENSION_KEYS],
        "note": "Company register snapshots; missing months are absent, and Unassigned remains visible.",
    }]


def _tree(expression: str) -> ast.Expression:
    if not isinstance(expression, str) or len(expression) > 160:
        raise ValueError("A calculated field needs an expression of at most 160 characters")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError("Invalid calculation expression") from exc
    nodes = list(ast.walk(tree))
    if len(nodes) > 24:
        raise ValueError("Calculation is too complex")
    allowed = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Add, ast.Sub, ast.Mult,
               ast.Div, ast.USub, ast.UAdd, ast.Name, ast.Load, ast.Constant)
    if any(not isinstance(node, allowed) for node in nodes):
        raise ValueError("Only numbers, metric names and + - * / are allowed")
    for node in nodes:
        if isinstance(node, ast.Name) and node.id not in NUMERIC - {"cost_per_head"}:
            raise ValueError(f"Unknown calculation metric: {node.id}")
        if isinstance(node, ast.Constant) and (
            isinstance(node.value, bool) or not isinstance(node.value, (int, float))
            or abs(node.value) > 1_000_000
        ):
            raise ValueError("Calculations accept bounded numeric constants only")
    return tree


def _eval(node: ast.AST, values: dict[str, Any]) -> Decimal | None:
    if isinstance(node, ast.Expression):
        return _eval(node.body, values)
    if isinstance(node, ast.Name):
        value = values.get(node.id)
        return Decimal(str(value)) if value is not None else None
    if isinstance(node, ast.Constant):
        return Decimal(str(node.value))
    if isinstance(node, ast.UnaryOp):
        value = _eval(node.operand, values)
        return None if value is None else (-value if isinstance(node.op, ast.USub) else value)
    if isinstance(node, ast.BinOp):
        left, right = _eval(node.left, values), _eval(node.right, values)
        if left is None or right is None:
            return None
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if right == 0:
            return None
        return left / right
    raise ValueError("Unsupported calculation")


def validate(spec: dict) -> dict:
    if not isinstance(spec, dict) or spec.get("dataset") != "payroll_cost":
        raise ValueError("Choose the approved payroll cost dataset")
    dimension = spec.get("dimension", "department")
    if dimension not in DIMENSION_KEYS:
        raise ValueError("Unknown breakdown dimension")
    fields = spec.get("fields", ["period", "dimension", "headcount", "gross", "ctc"])
    if (not isinstance(fields, list) or not 1 <= len(fields) <= 14
            or any(not isinstance(field, str) for field in fields) or len(fields) != len(set(fields))):
        raise ValueError("Choose 1–14 distinct columns")
    calculations = spec.get("calculations", [])
    if not isinstance(calculations, list) or len(calculations) > 3:
        raise ValueError("At most three calculated fields are supported")
    names = []
    for calc in calculations:
        if not isinstance(calc, dict) or not isinstance(calc.get("key"), str) or not isinstance(calc.get("expression"), str):
            raise ValueError("Each calculation needs a key and expression")
        key = calc["key"]
        if not key.startswith("calc_") or not key[5:].isalnum() or len(key) > 32:
            raise ValueError("Calculation keys must start with calc_ and contain letters or numbers")
        _tree(calc["expression"])
        names.append(key)
    if len(set(names)) != len(names) or any(field not in FIELDS and field not in names for field in fields):
        raise ValueError("Unknown or repeated field")
    filters = spec.get("filters", {})
    if not isinstance(filters, dict) or len(filters) > len(DIMENSION_KEYS):
        raise ValueError("Invalid filters")
    for key, values in filters.items():
        if key not in DIMENSION_KEYS or not isinstance(values, list) or len(values) > 100 or any(
            not isinstance(value, str) or len(value) > 120 for value in values
        ):
            raise ValueError("Filters must use approved dimensions and bounded values")
    date_from, date_to = spec.get("date_from"), spec.get("date_to")
    try:
        start = date.fromisoformat(date_from) if date_from else None
        end = date.fromisoformat(date_to) if date_to else None
    except (TypeError, ValueError) as exc:
        raise ValueError("Periods must be ISO dates") from exc
    if start and end and (end < start or (end.year - start.year) * 12 + end.month - start.month > 23):
        raise ValueError("Preview range must be ordered and at most 24 months")
    if spec.get("sort", fields[0]) not in fields:
        raise ValueError("Sort must be a visible column")
    if spec.get("order", "asc") not in ("asc", "desc"):
        raise ValueError("Invalid sort order")
    return {
        "dataset": "payroll_cost", "dimension": dimension, "fields": fields,
        "filters": {key: values for key, values in filters.items() if values},
        "date_from": date_from, "date_to": date_to,
        "sort": spec.get("sort", fields[0]), "order": spec.get("order", "asc"),
        "calculations": [{"key": calc["key"], "expression": calc["expression"], "label": str(calc.get("label") or calc["key"])[:80]} for calc in calculations],
    }


def preview(db, entity_id, specification: dict, *, row_limit: int | None = MAX_PREVIEW_ROWS) -> dict:
    spec = validate(specification)
    analysis = cost_analysis(
        db, entity_id, group_by=spec["dimension"], granularity="month",
        measure="ctc", date_from=date.fromisoformat(spec["date_from"]) if spec["date_from"] else None,
        date_to=date.fromisoformat(spec["date_to"]) if spec["date_to"] else None,
        filters=spec["filters"],
    )
    if analysis["data_status"] == "no_register":
        return {"status": "missing_data", "rows": [], "record_count": 0, "control_totals": None, "grain": "period_dimension"}
    rows = []
    for group in analysis["matrix"]:
        for cell in group["series"]:
            if cell["period"] not in {p["key"] for p in analysis["periods"]}:
                continue
            # A missing group-period cell is a gap, not a zero-cost payroll row.
            if not cell["headcount"]:
                continue
            values = {"period": cell["period"], "dimension": group["group"], "headcount": cell["headcount"],
                      "person_months": cell["headcount"], **cell["measures"]}
            values["cost_per_head"] = (
                round(values["ctc"] / cell["headcount"], 2) if cell["headcount"] else None
            )
            for calc in spec["calculations"]:
                try:
                    result = _eval(_tree(calc["expression"]), values)
                    values[calc["key"]] = float(round(result, 2)) if result is not None and result.is_finite() else None
                except (InvalidOperation, OverflowError):
                    values[calc["key"]] = None
            rows.append({key: values[key] for key in spec["fields"]})
    sort_key = spec["sort"]
    rows.sort(key=lambda row: (row[sort_key] is None, row[sort_key]), reverse=spec["order"] == "desc")
    return {
        "status": "ok" if rows else "no_matching_records",
        "rows": rows[:row_limit] if row_limit is not None else rows, "record_count": len(rows),
        "truncated_preview": row_limit is not None and len(rows) > row_limit,
        "control_totals": {key: analysis["totals"][key] for key in (*MEASURE_FIELDS, "headcount", "person_months")},
        "grain": "period_dimension", "basis": analysis["basis"],
    }
