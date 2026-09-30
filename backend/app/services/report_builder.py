"""Controlled Report Builder datasets.

No SQL or arbitrary Python from definitions. A definition names an approved
dataset, one breakdown, columns, filters, a period range, up to three
calculated columns (restricted arithmetic, each with a stated unit), and how to
lay the answer out: a table, or a pivot of one value by breakdown and month,
optionally charted.

Three datasets, each computed by the service the rest of the product uses, so a
report cannot disagree with the page it came from:

* **payroll_cost** — cost at month × one company dimension, from the shared
  costing (``analytics.cost_analysis``);
* **workforce_movement** — opening, joiners, exits, moves and closing at month ×
  one company dimension, from who was paid on each stored register;
* **validation_findings** — findings, people affected and priced exposure at
  month × severity, check or component, from each month's current run.

Every value states whether it can be totalled across months and across groups.
A pivot totals only what adds up; a headcount summed over six months, or people
affected summed over checks, would be a number nobody can use.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from app.services.cost_model import DERIVED_LABELS
from app.services.dimensions import DIMENSION_KEYS, DIMENSION_LABELS, UNASSIGNED

MAX_PREVIEW_ROWS = 200
MAX_CALCULATIONS = 3
UNITS = ("inr", "number", "pct")
LAYOUTS = ("table", "pivot")
CHARTS = ("none", "bar", "line")
#: The most groups a line chart draws; the rest are named as left out.
CHART_SERIES = 6


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    unit: str  # "inr" | "number" | "pct" | "month" | "text"
    across_periods: bool = False  # sums meaningfully over months
    across_groups: bool = False  # sums meaningfully over the breakdown's groups
    calc: bool = True  # may be named in a calculation

    @property
    def numeric(self) -> bool:
        return self.unit in UNITS


_PERIOD = Field("period", "Payroll period", "month", calc=False)
_GROUP = Field("dimension", "Breakdown", "text", calc=False)


def _money(key: str, label: str) -> Field:
    return Field(key, label, "inr", across_periods=True, across_groups=True)


PAYROLL_COST = (
    _PERIOD, _GROUP,
    Field("headcount", "People paid", "number", across_groups=True),
    Field("person_months", "Person-months", "number", across_periods=True, across_groups=True),
    Field("cost_per_head", "Monthly cost per head", "inr", calc=False),
    _money("gross", DERIVED_LABELS.get("gross", "Gross")),
    _money("deductions", DERIVED_LABELS.get("deductions", "Deductions")),
    _money("net", "Net pay"),
    _money("employer_cost", DERIVED_LABELS.get("employer_cost", "Employer cost")),
    _money("ctc", DERIVED_LABELS.get("ctc", "Total CTC")),
)

WORKFORCE_MOVEMENT = (
    _PERIOD, _GROUP,
    Field("opening", "Opening (paid last month)", "number", across_groups=True),
    Field("joiners", "Joiners", "number", across_periods=True, across_groups=True),
    Field("moved_in", "Moved in", "number", across_periods=True, across_groups=True),
    Field("exits", "Exits", "number", across_periods=True, across_groups=True),
    Field("moved_out", "Moved out", "number", across_periods=True, across_groups=True),
    Field("closing", "Closing (paid this month)", "number", across_groups=True),
    Field("attrition_pct", "Monthly attrition", "pct", calc=False),
)

VALIDATION_FINDINGS = (
    _PERIOD, _GROUP,
    Field("findings", "Findings", "number", across_periods=True, across_groups=True),
    Field("critical", "Critical findings", "number", across_periods=True, across_groups=True),
    Field("employees_affected", "People affected", "number"),
    Field("priced_exposure", "Priced exposure", "inr", across_periods=True),
    Field("unpriced", "Findings without a calculated impact", "number", across_periods=True, across_groups=True),
)

FINDING_BREAKDOWNS = {"severity": "Severity", "check": "Check", "component": "Component"}

DATASETS: dict[str, dict[str, Any]] = {
    "payroll_cost": {
        "label": "Payroll cost",
        "grain": "Payroll period × one company dimension",
        "fields": PAYROLL_COST,
        "breakdowns": {key: DIMENSION_LABELS[key] for key in DIMENSION_KEYS},
        "default_breakdown": "department",
        "filters": True,
        "note": "Company register snapshots, costed as on Cost analysis. Missing months are absent, and Unassigned remains visible.",
        "default_fields": ["period", "dimension", "headcount", "gross", "ctc"],
    },
    "workforce_movement": {
        "label": "Workforce movement",
        "grain": "Payroll period × one company dimension",
        "fields": WORKFORCE_MOVEMENT,
        "breakdowns": {key: DIMENSION_LABELS[key] for key in DIMENSION_KEYS},
        "default_breakdown": "department",
        "filters": True,
        "note": "Who was paid, register to register: a joiner was not paid anywhere last month, an exit is not paid anywhere this month, and a move changed group (or entered or left the filtered population). Opening + joiners + moved in − exits − moved out = closing. A month whose previous month has no register has no movement, not zero.",
        "default_fields": ["period", "dimension", "opening", "joiners", "exits", "closing"],
    },
    "validation_findings": {
        "label": "Validation findings",
        "grain": "Payroll period × severity, check or component",
        "fields": VALIDATION_FINDINGS,
        "breakdowns": FINDING_BREAKDOWNS,
        "default_breakdown": "severity",
        "filters": False,
        "note": "Each month's current run. Priced exposure counts each person once per group — their largest priced finding — and findings whose rule does not price its effect are counted separately, never as ₹0. A month that was never validated is absent.",
        "default_fields": ["period", "dimension", "findings", "employees_affected", "priced_exposure"],
    },
}


def _fields(dataset: str) -> dict[str, Field]:
    return {f.key: f for f in DATASETS[dataset]["fields"]}


def dataset_catalogue() -> list[dict]:
    return [{
        "key": key, "label": spec["label"], "grain": spec["grain"], "note": spec["note"],
        "fields": [{"key": f.key, "label": f.label, "numeric": f.numeric, "unit": f.unit,
                    "calc": f.calc and f.numeric, "across_periods": f.across_periods,
                    "across_groups": f.across_groups} for f in spec["fields"]],
        "dimensions": [{"key": k, "label": label} for k, label in spec["breakdowns"].items()],
        "default_breakdown": spec["default_breakdown"],
        "default_fields": spec["default_fields"],
        "filters": spec["filters"],
    } for key, spec in DATASETS.items()]


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def _tree(expression: str, allowed_names: set[str]) -> ast.Expression:
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
        if isinstance(node, ast.Name) and node.id not in allowed_names:
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


def calc_names(dataset: str) -> set[str]:
    return {f.key for f in DATASETS[dataset]["fields"] if f.calc and f.numeric}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate(spec: dict) -> dict:
    if not isinstance(spec, dict) or spec.get("dataset", "payroll_cost") not in DATASETS:
        raise ValueError("Choose one of the approved datasets")
    dataset = spec.get("dataset", "payroll_cost")
    meta = DATASETS[dataset]
    known = _fields(dataset)
    dimension = spec.get("dimension", meta["default_breakdown"])
    if dimension not in meta["breakdowns"]:
        raise ValueError("Unknown breakdown for this dataset")
    fields = spec.get("fields", meta["default_fields"])
    if (not isinstance(fields, list) or not 1 <= len(fields) <= 14
            or any(not isinstance(field, str) for field in fields) or len(fields) != len(set(fields))):
        raise ValueError("Choose 1–14 distinct columns")
    calculations = spec.get("calculations", [])
    if not isinstance(calculations, list) or len(calculations) > MAX_CALCULATIONS:
        raise ValueError("At most three calculated fields are supported")
    allowed_names = calc_names(dataset)
    calcs = []
    for calc in calculations:
        if not isinstance(calc, dict) or not isinstance(calc.get("key"), str) or not isinstance(calc.get("expression"), str):
            raise ValueError("Each calculation needs a key and expression")
        key = calc["key"]
        if not key.startswith("calc_") or not key[5:].isalnum() or len(key) > 32:
            raise ValueError("Calculation keys must start with calc_ and contain letters or numbers")
        _tree(calc["expression"], allowed_names)
        unit = calc.get("unit", "number")
        if unit not in UNITS:
            raise ValueError("A calculation's unit must be ₹, a count or a percentage")
        calcs.append({"key": key, "expression": calc["expression"],
                      "label": str(calc.get("label") or key)[:80], "unit": unit})
    names = [c["key"] for c in calcs]
    if len(set(names)) != len(names) or any(field not in known and field not in names for field in fields):
        raise ValueError("Unknown or repeated field")
    filters = spec.get("filters", {})
    if not isinstance(filters, dict) or len(filters) > len(DIMENSION_KEYS):
        raise ValueError("Invalid filters")
    if filters and any(filters.values()) and not meta["filters"]:
        raise ValueError(f"{meta['label']} has no company-dimension filters")
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

    numeric_columns = [f for f in fields if (f in known and known[f].numeric) or f in names]
    layout = spec.get("layout", "table")
    if layout not in LAYOUTS:
        raise ValueError("Layout must be a table or a pivot")
    pivot_value = spec.get("pivot_value") or (numeric_columns[0] if numeric_columns else None)
    chart = spec.get("chart", "none")
    if chart not in CHARTS:
        raise ValueError("Chart must be none, bar or line")
    if (layout == "pivot" or chart != "none"):
        if pivot_value not in numeric_columns:
            raise ValueError("A pivot or chart needs one of the report's number columns as its value")
        if "period" not in fields or "dimension" not in fields:
            raise ValueError("A pivot or chart needs both the period and the breakdown as columns")
    return {
        "dataset": dataset, "dimension": dimension, "fields": fields,
        "filters": {key: values for key, values in filters.items() if values},
        "date_from": date_from, "date_to": date_to,
        "sort": spec.get("sort", fields[0]), "order": spec.get("order", "asc"),
        "calculations": calcs,
        "layout": layout, "pivot_value": pivot_value if (layout == "pivot" or chart != "none") else None,
        "chart": chart,
    }


def column_meta(spec: dict) -> list[dict]:
    """Label, unit and additivity for each column of a validated spec."""
    known = _fields(spec["dataset"])
    calcs = {c["key"]: c for c in spec["calculations"]}
    out = []
    for key in spec["fields"]:
        if key in known:
            f = known[key]
            label = DATASETS[spec["dataset"]]["breakdowns"][spec["dimension"]] if key == "dimension" else f.label
            out.append({"key": key, "label": label, "unit": f.unit,
                        "across_periods": f.across_periods, "across_groups": f.across_groups})
        else:
            c = calcs[key]
            out.append({"key": key, "label": c["label"], "unit": c["unit"],
                        "across_periods": False, "across_groups": False})
    return out


# ---------------------------------------------------------------------------
# Datasets
# ---------------------------------------------------------------------------
def _range(spec: dict) -> tuple[date | None, date | None]:
    return (date.fromisoformat(spec["date_from"]) if spec["date_from"] else None,
            date.fromisoformat(spec["date_to"]) if spec["date_to"] else None)


def _prev(period: date) -> date:
    return date(period.year - 1, 12, 1) if period.month == 1 else date(period.year, period.month - 1, 1)


def _payroll_cost(db, entity_id, spec) -> tuple[list[dict], dict | None, dict | None]:
    from app.services.analytics import cost_analysis

    start, end = _range(spec)
    analysis = cost_analysis(db, entity_id, group_by=spec["dimension"], granularity="month",
                             measure="ctc", date_from=start, date_to=end, filters=spec["filters"])
    if analysis["data_status"] == "no_register":
        return [], None, None
    periods = {p["key"] for p in analysis["periods"]}
    rows = []
    for group in analysis["matrix"]:
        for cell in group["series"]:
            # A missing group-period cell is a gap, not a zero-cost payroll row.
            if cell["period"] not in periods or not cell["headcount"]:
                continue
            values = {"period": cell["period"], "dimension": group["group"], "headcount": cell["headcount"],
                      "person_months": cell["headcount"], **cell["measures"]}
            values["cost_per_head"] = round(values["ctc"] / cell["headcount"], 2) if cell["headcount"] else None
            rows.append(values)
    totals = {key: analysis["totals"][key] for key in ("gross", "deductions", "net", "employer_cost", "ctc",
                                                       "headcount", "person_months")}
    return rows, totals, analysis["basis"]


def _workforce_movement(db, entity_id, spec) -> tuple[list[dict], dict | None, dict | None]:
    from app.models import SalaryRegister
    from app.services.analytics import _register_rows
    from app.services.bi_basis import data_basis

    start, end = _range(spec)
    load_from = _prev(start) if start else None
    rows_all, by_register = _register_rows(db, entity_id, load_from, end)
    if not rows_all:
        return [], None, None
    dim = spec["dimension"]
    active = {k: set(v) for k, v in spec["filters"].items() if v}
    paid: dict[date, set[str]] = {}
    group_of: dict[date, dict[str, str]] = {}   # month -> employee -> group, filtered population only
    for row in rows_all:
        month = by_register[row.register_id].period_month
        paid.setdefault(month, set()).add(row.employee_id)
        dims = row.dimensions or {}
        if any(dims.get(key, UNASSIGNED) not in wanted for key, wanted in active.items()):
            continue
        group_of.setdefault(month, {})[row.employee_id] = dims.get(dim) or UNASSIGNED
    registered = {r.period_month for r in db.query(SalaryRegister.period_month)
                  .filter(SalaryRegister.entity_id == entity_id)}
    out = []
    joiners_total = exits_total = 0
    for month in sorted(paid):
        if start and month < start:
            continue
        now = group_of.get(month, {})
        prior_month = _prev(month)
        measurable = prior_month in registered
        before = group_of.get(prior_month, {}) if measurable else {}
        prior_paid = paid.get(prior_month, set())
        groups = set(now.values()) | set(before.values())
        for group in sorted(groups):
            closing = {e for e, g in now.items() if g == group}
            if not measurable:
                if closing:
                    out.append({"period": month.isoformat(), "dimension": group, "opening": None,
                                "joiners": None, "moved_in": None, "exits": None, "moved_out": None,
                                "closing": len(closing), "attrition_pct": None})
                continue
            opening = {e for e, g in before.items() if g == group}
            joiners = {e for e in closing if e not in prior_paid}
            moved_in = closing - opening - joiners
            exits = {e for e in opening if e not in paid.get(month, set())}
            moved_out = opening - closing - exits
            average = (len(opening) + len(closing)) / 2
            joiners_total += len(joiners)
            exits_total += len(exits)
            out.append({
                "period": month.isoformat(), "dimension": group, "opening": len(opening),
                "joiners": len(joiners), "moved_in": len(moved_in), "exits": len(exits),
                "moved_out": len(moved_out), "closing": len(closing),
                "attrition_pct": round(len(exits) * 100 / average, 2) if average else None,
            })
    totals = {"joiners": joiners_total, "exits": exits_total}
    return out, totals, data_basis(db, entity_id, date_from=start, date_to=end)


def _validation_findings(db, entity_id, spec) -> tuple[list[dict], dict | None, dict | None]:
    from app.models import FindingRecord, ValidationRun
    from app.services.explain import impact_known

    start, end = _range(spec)
    runs = db.query(ValidationRun.id, ValidationRun.period_month).filter(
        ValidationRun.entity_id == entity_id, ValidationRun.status == "current")
    if start:
        runs = runs.filter(ValidationRun.period_month >= start.replace(day=1))
    if end:
        runs = runs.filter(ValidationRun.period_month <= end.replace(day=1))
    run_month = dict(runs.all())
    if not run_month:
        return [], None, None
    cells: dict[tuple[str, str], dict[str, Any]] = {}
    for f in (db.query(FindingRecord.run_id, FindingRecord.employee_id, FindingRecord.rule_id,
                       FindingRecord.rule_name, FindingRecord.component, FindingRecord.severity,
                       FindingRecord.financial_impact)
              .filter(FindingRecord.run_id.in_(list(run_month)))):
        if spec["dimension"] == "severity":
            group = (f.severity or "").title() or UNASSIGNED
        elif spec["dimension"] == "check":
            group = f"{f.rule_id} · {f.rule_name}"
        else:
            group = f.component or "No component"
        key = (run_month[f.run_id].isoformat(), group)
        cell = cells.setdefault(key, {"findings": 0, "critical": 0, "people": set(), "largest": {}, "unpriced": 0})
        cell["findings"] += 1
        cell["critical"] += (f.severity or "").upper() == "CRITICAL"
        cell["people"].add(f.employee_id)
        if impact_known(f.rule_id, f.financial_impact):
            amount = abs(Decimal(str(f.financial_impact)))
            if amount > cell["largest"].get(f.employee_id, Decimal("0")):
                cell["largest"][f.employee_id] = amount
        else:
            cell["unpriced"] += 1
    rows = [{
        "period": period, "dimension": group, "findings": c["findings"], "critical": c["critical"],
        "employees_affected": len(c["people"]),
        # No priced finding in the group is "not priced", not ₹0 of exposure.
        "priced_exposure": float(sum(c["largest"].values(), Decimal("0"))) if c["largest"] else None,
        "unpriced": c["unpriced"],
    } for (period, group), c in cells.items()]
    totals = {"findings": sum(r["findings"] for r in rows), "runs": len(run_month)}
    return rows, totals, {"validated_months": sorted(m.isoformat() for m in run_month.values())}


_COMPUTE = {
    "payroll_cost": _payroll_cost,
    "workforce_movement": _workforce_movement,
    "validation_findings": _validation_findings,
}


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------
def pivot(rows: list[dict], spec: dict, meta: list[dict]) -> dict:
    """One value by breakdown (rows) and month (columns), totalled only where it adds up."""
    value = spec["pivot_value"]
    col = next(c for c in meta if c["key"] == value)
    periods = sorted({r["period"] for r in rows})
    groups: dict[str, dict[str, Any]] = {}
    for r in rows:
        groups.setdefault(r["dimension"], {})[r["period"]] = r.get(value)

    def total(values: list) -> float | None:
        present = [v for v in values if v is not None]
        return round(float(sum(present)), 2) if present else None

    out_rows = [{
        "dimension": group,
        "cells": {p: cells.get(p) for p in periods},
        "total": total(list(cells.values())) if col["across_periods"] else None,
    } for group, cells in groups.items()]
    out_rows.sort(key=lambda r: (-(r["total"] or 0) if col["across_periods"] else 0, r["dimension"]))
    column_totals = ({p: total([g.get(p) for g in groups.values()]) for p in periods}
                     if col["across_groups"] else None)
    grand = (total(list(column_totals.values())) if column_totals and col["across_periods"] else None)
    return {"value": value, "label": col["label"], "unit": col["unit"], "periods": periods,
            "rows": out_rows, "column_totals": column_totals, "grand_total": grand,
            "row_totals": col["across_periods"],
            "note": None if col["across_periods"] and col["across_groups"] else (
                f"{col['label']} is not totalled "
                + ("across months" if not col["across_periods"] else "")
                + (" or " if not col["across_periods"] and not col["across_groups"] else "")
                + ("across groups" if not col["across_groups"] else "")
                + ": the sum would count the same people more than once.")}


def chart_series(rows: list[dict], spec: dict, meta: list[dict]) -> dict | None:
    """What a chart of the pivot value draws: a bar per group for the latest
    month, or a line per group over the months (the largest few)."""
    if spec["chart"] == "none":
        return None
    value = spec["pivot_value"]
    col = next(c for c in meta if c["key"] == value)
    periods = sorted({r["period"] for r in rows})
    if not periods:
        return None
    if spec["chart"] == "bar":
        latest = periods[-1]
        bars = sorted(((r["dimension"], r.get(value)) for r in rows if r["period"] == latest),
                      key=lambda b: -(b[1] or 0))
        return {"type": "bar", "value": value, "label": col["label"], "unit": col["unit"],
                "period": latest, "bars": [{"group": g, "value": v} for g, v in bars[:20]],
                "omitted": max(0, len(bars) - 20)}
    by_group: dict[str, dict[str, Any]] = {}
    for r in rows:
        by_group.setdefault(r["dimension"], {})[r["period"]] = r.get(value)
    ranked = sorted(by_group, key=lambda g: -max((v or 0) for v in by_group[g].values()))
    shown = ranked[:CHART_SERIES]
    return {"type": "line", "value": value, "label": col["label"], "unit": col["unit"],
            "periods": periods,
            "series": [{"group": g, "points": [by_group[g].get(p) for p in periods]} for g in shown],
            "omitted": len(ranked) - len(shown)}


def preview(db, entity_id, specification: dict, *, row_limit: int | None = MAX_PREVIEW_ROWS) -> dict:
    spec = validate(specification)
    rows, totals, basis = _COMPUTE[spec["dataset"]](db, entity_id, spec)
    meta = column_meta(spec)
    if totals is None:
        return {"status": "missing_data", "rows": [], "record_count": 0, "control_totals": None,
                "grain": "period_dimension", "columns": meta, "pivot": None, "chart": None}
    tree_names = calc_names(spec["dataset"])
    for values in rows:
        for calc in spec["calculations"]:
            try:
                result = _eval(_tree(calc["expression"], tree_names), values)
                values[calc["key"]] = float(round(result, 2)) if result is not None and result.is_finite() else None
            except (InvalidOperation, OverflowError):
                values[calc["key"]] = None
    rows = [{key: values.get(key) for key in spec["fields"]} for values in rows]
    sort_key = spec["sort"]
    rows.sort(key=lambda row: (row[sort_key] is None, row[sort_key]), reverse=spec["order"] == "desc")
    laid_out = pivot(rows, spec, meta) if spec["layout"] == "pivot" else None
    return {
        "status": "ok" if rows else "no_matching_records",
        "rows": rows[:row_limit] if row_limit is not None else rows, "record_count": len(rows),
        "truncated_preview": row_limit is not None and len(rows) > row_limit,
        "control_totals": totals, "grain": "period_dimension", "basis": basis,
        "columns": meta, "pivot": laid_out, "chart": chart_series(rows, spec, meta),
    }
