"""
Safe, deterministic validation matrix evaluation. No user-supplied Python or SQL.

A company rule is data, evaluated here:

* **Operands** read a register field, a salary component, a deduction, a fixed
  value, the same employee's value **last month** (``previous``), a field of the
  **employee master** (``master``), or an arithmetic **expression** over those
  (``expr``) — evaluated by ``formula_eval``, which walks a whitelisted AST: no
  names but the offered variables, no attributes, no calls but ``min``/``max``/
  ``abs``/``round``/``floor``/``ceil``/``iff``, bounded length and depth.
* **Conditions** nest: groups of comparisons or groups, joined by *all* / *any*,
  optionally negated, at most ``MAX_DEPTH`` deep and ``MAX_LEAVES`` comparisons.
* **Logic is three-valued.** A comparison whose input is missing is *unknown*,
  never false: ``all`` is false if any part is false, else unknown if any part
  is unknown; ``any`` is true if any part is true, else unknown if any part is.
  An unknown rule does what its ``on_missing`` says — report "cannot validate"
  (the default), skip the employee, or fail — and never passes silently.
* **Applicability** narrows a rule to work states and to values of named
  dimensions (department, employment type, …). An employee whose dimension is
  not recorded is unknown for that rule, not out of scope.
"""
from __future__ import annotations

import ast
import json
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.orm import Session

from app.models import ValidationRuleVersion
from app.services.formula_eval import ALLOWED_FUNCS, FormulaError, evaluate_formula
from app.services.dimensions import UNASSIGNED
from app.services.payroll_parse import normalize_col

FIELDS = {
    "employee_id", "location_state", "work_state", "state", "department",
    "designation", "total_days", "paid_days", "lop_days", "net_pay",
    "gross", "pf_employee", "esic_employee", "pt", "lwf_employee", "tds",
    "pan", "uan", "ifsc", "bank_account", "location", "skill_category",
    "employment_type", "business_unit", "cost_center", "tax_regime", "doj", "dol",
    "payment_mode",
}
DEDUCTIONS = {"pf_employee", "pf_employer", "esic_employee", "esic_employer", "pt", "lwf_employee", "lwf_employer", "tds"}
NUMERIC_FIELDS = {"total_days", "paid_days", "lop_days", "net_pay", "gross", *DEDUCTIONS}
MASTER_FIELDS = {
    "employee_name", "date_of_joining", "date_of_exit", "date_of_birth", "gender", "work_state",
    "work_location", "department", "designation", "grade", "business_unit", "cost_center",
    "employment_type", "skill_category", "pan", "aadhaar", "uan", "pf_number", "esic_ip_number",
    "bank_account", "ifsc",
}
#: Dimensions a rule can be narrowed to. Read from the register row, then the master.
APPLICABILITY_DIMENSIONS = {
    "department", "designation", "employment_type", "business_unit", "cost_center",
    "location", "grade", "skill_category",
}
OPS = {"eq", "ne", "gt", "gte", "lt", "lte", "present", "in", "not_in"}
SOURCES = {"field", "component", "deduction", "literal", "previous", "master", "expr"}
ON_MISSING = ("cannot_validate", "skip", "fail")
MAX_DEPTH = 3
MAX_LEAVES = 20


# ---------------------------------------------------------------------------
# Validation of a rule's definition
# ---------------------------------------------------------------------------
def expression_names(expression: str) -> set[str]:
    """Variable names an expression reads; a syntax error is a ValueError."""
    try:
        tree = ast.parse(expression or "", mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Expression is not valid: {exc.msg}") from exc
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id not in ALLOWED_FUNCS}


def expression_variables(configured_components: set[str]) -> set[str]:
    """Every name an expression may use: numeric fields, deductions, components, and prev_ of each."""
    now = set(NUMERIC_FIELDS) | set(DEDUCTIONS) | set(configured_components)
    return now | {f"prev_{name}" for name in now}


def _validate_operand(operand: dict, configured_components: set[str]) -> None:
    source, key = operand["source"], operand.get("key")
    if source not in SOURCES:
        raise ValueError(f"Unknown source: {source}")
    if source == "field" and key not in FIELDS:
        raise ValueError(f"Unknown field: {key}")
    if source == "deduction" and key not in DEDUCTIONS:
        raise ValueError(f"Unknown deduction: {key}")
    if source == "component" and normalize_col(key or "") not in configured_components:
        raise ValueError(f"Salary component is not configured: {key}")
    if source == "master" and key not in MASTER_FIELDS:
        raise ValueError(f"Unknown employee master field: {key}")
    if source == "previous":
        of = operand.get("of") or "field"
        if of == "component":
            if normalize_col(key or "") not in configured_components:
                raise ValueError(f"Salary component is not configured: {key}")
        elif of == "deduction":
            if key not in DEDUCTIONS:
                raise ValueError(f"Unknown deduction: {key}")
        elif key not in FIELDS:
            raise ValueError(f"Unknown field: {key}")
    if source == "expr":
        expression = operand.get("value") or ""
        unknown = expression_names(expression) - expression_variables(configured_components)
        if unknown:
            raise ValueError(f"Expression uses unknown names: {', '.join(sorted(unknown))}")
        # Parse and bound it now, with every variable present, so a rule that
        # cannot be evaluated is refused at drafting rather than at run time.
        try:
            evaluate_formula(expression, dict.fromkeys(expression_variables(configured_components), 1))
        except FormulaError as exc:
            raise ValueError(f"Expression is not valid: {exc}") from exc
        except (ZeroDivisionError, OverflowError, TypeError, ValueError):
            pass  # data-dependent; handled as "cannot validate" when it happens


def validate_comparison(comparison: dict, configured_components: set[str]) -> None:
    for operand in (comparison["left"], comparison["right"]):
        _validate_operand(operand, configured_components)
    if comparison["operator"] not in OPS:
        raise ValueError(f"Unknown operator: {comparison['operator']}")
    if comparison["operator"] in {"in", "not_in"}:
        right = comparison["right"]
        if right["source"] != "literal" or not any(part.strip() for part in (right.get("value") or "").split("|")):
            raise ValueError("List checks need a fixed value separated by |")
    try:
        tolerance = Decimal(str(comparison.get("tolerance", "0")))
    except InvalidOperation as exc:
        raise ValueError("Tolerance must be a number") from exc
    if not tolerance.is_finite() or tolerance < 0:
        raise ValueError("Tolerance must be a non-negative finite number")


def is_group(node: dict | None) -> bool:
    return isinstance(node, dict) and "items" in node


def validate_condition(node: dict, configured_components: set[str]) -> None:
    """A comparison or a group, within the depth and size limits."""
    leaves = 0

    def walk(n: dict, depth: int) -> None:
        nonlocal leaves
        if is_group(n):
            if depth > MAX_DEPTH:
                raise ValueError(f"Conditions can nest at most {MAX_DEPTH} groups deep")
            if n.get("mode", "all") not in ("all", "any"):
                raise ValueError("A group joins its parts with all or any")
            if not n.get("items"):
                raise ValueError("A condition group cannot be empty")
            for item in n["items"]:
                walk(item, depth + 1)
        else:
            leaves += 1
            validate_comparison(n, configured_components)

    walk(node, 1)
    if leaves > MAX_LEAVES:
        raise ValueError(f"A rule can test at most {MAX_LEAVES} conditions")


def validate_applies_to(applies_to: dict | None) -> None:
    for dim, values in (applies_to or {}).items():
        if dim not in APPLICABILITY_DIMENSIONS:
            raise ValueError(f"Rules cannot be narrowed by {dim}")
        if not isinstance(values, list) or not any(str(v).strip() for v in values):
            raise ValueError(f"List at least one {dim.replace('_', ' ')}")


def references(rule: ValidationRuleVersion) -> set[tuple[str, str]]:
    """Every (source, key) a rule reads — used to detect broken references."""
    found: set[tuple[str, str]] = set()

    def operand(o: dict) -> None:
        if o.get("source") == "expr":
            for name in expression_names(o.get("value") or ""):
                found.add(("expr", name.removeprefix("prev_")))
        elif o.get("source") != "literal":
            src = o.get("of") if o.get("source") == "previous" else o.get("source")
            found.add((src or "field", o.get("key") or ""))

    def walk(n: dict | None) -> None:
        if not n:
            return
        if is_group(n):
            for i in n["items"]:
                walk(i)
        else:
            operand(n["left"])
            operand(n["right"])

    walk(rule.condition)
    walk(rule.assertion)
    return found


# ---------------------------------------------------------------------------
# Which versions apply
# ---------------------------------------------------------------------------
def published_for(db: Session, entity_id, period: date) -> list[ValidationRuleVersion]:
    """The version of each rule in force for ``period``.

    A retired version still governs the months before its end date, so a
    re-run of an old month uses the rule that applied then.
    """
    rows = db.query(ValidationRuleVersion).filter(
        ValidationRuleVersion.entity_id == entity_id,
        ValidationRuleVersion.status.in_(("published", "retired")),
        ValidationRuleVersion.effective_from <= period,
    ).all()
    chosen: dict[str, ValidationRuleVersion] = {}
    for row in rows:
        prior = chosen.get(row.rule_key)
        if prior is None or (row.effective_from, row.version) > (prior.effective_from, prior.version):
            chosen[row.rule_key] = row
    return [row for row in chosen.values() if not (row.effective_to and row.effective_to < period)]


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------
def _num(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        d = Decimal(str(value).replace(",", ""))
    except InvalidOperation:
        return None
    return d if d.is_finite() else None


def _variables(row: dict[str, Any]) -> dict[str, Any]:
    """Numeric variables for expressions: this month, and prev_ for last month."""
    out: dict[str, Any] = {}

    def add(prefix: str, source: dict[str, Any] | None) -> None:
        if not source:
            return
        for name in NUMERIC_FIELDS:
            v = _num((source.get("deductions") or {}).get(name, source.get(name)))
            if v is not None:
                out[prefix + name] = float(v)
        for name, value in (source.get("components") or {}).items():
            v = _num(value)
            if v is not None:
                out[prefix + normalize_col(name)] = float(v)

    add("", row)
    add("prev_", row.get("_previous"))
    return out


def _resolve(operand: dict, row: dict[str, Any], cache: dict[str, Any]) -> Any:
    source = operand["source"]
    if source == "literal":
        return operand.get("value")
    key = operand.get("key")
    if source == "component":
        return (row.get("components") or {}).get(normalize_col(key))
    if source == "deduction":
        deductions = row.get("deductions") or {}
        return deductions.get(key, row.get(key))
    if source == "previous":
        prev = row.get("_previous")
        if not prev:
            return None
        return _resolve({"source": operand.get("of") or "field", "key": key}, prev, cache)
    if source == "master":
        master = row.get("_master")
        return master.get(key) if master else None
    if source == "expr":
        if "vars" not in cache:
            cache["vars"] = _variables(row)
        try:
            return evaluate_formula(operand.get("value") or "", cache["vars"])
        except (FormulaError, ZeroDivisionError, OverflowError, TypeError, ValueError):
            return None  # a missing variable or a division by zero: unknown, not false
    return row.get(key)


def _display(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.2f}"
    return "" if value is None else str(value)


def _compare(comparison: dict, row: dict[str, Any], cache: dict[str, Any]) -> tuple[bool | None, Any, Any]:
    left = _resolve(comparison["left"], row, cache)
    right = _resolve(comparison["right"], row, cache)
    op = comparison["operator"]
    if op == "present":
        return (None if left in (None, "") else True), left, "a value"
    if left in (None, "") or right in (None, ""):
        return None, left, right
    if op in ("in", "not_in"):
        allowed = {part.strip().casefold() for part in str(right).split("|") if part.strip()}
        matched = str(left).strip().casefold() in allowed
        return (matched if op == "in" else not matched), left, right
    try:
        a, b = Decimal(str(left)), Decimal(str(right))
        if not a.is_finite() or not b.is_finite():
            return None, left, right
        tolerance = Decimal(str(comparison.get("tolerance", "0")))
        difference = a - b
        result = {
            "eq": abs(difference) <= tolerance,
            "ne": abs(difference) > tolerance,
            "gt": difference > tolerance,
            "gte": difference >= -tolerance,
            "lt": difference < -tolerance,
            "lte": difference <= tolerance,
        }[op]
        return result, left, right
    except InvalidOperation:
        if op not in ("eq", "ne"):
            return None, left, right
        same = str(left).strip().casefold() == str(right).strip().casefold()
        return (same if op == "eq" else not same), left, right


def condition_result(node: dict | None, row: dict[str, Any], cache: dict[str, Any] | None = None) -> bool | None:
    """Three-valued: True, False, or None (an input was missing)."""
    if not node:
        return True
    cache = cache if cache is not None else {}
    if not is_group(node):
        return _compare(node, row, cache)[0]
    parts = [condition_result(item, row, cache) for item in node["items"]]
    if node.get("mode", "all") == "any":
        result = True if True in parts else (None if None in parts else False)
    else:
        result = False if False in parts else (None if None in parts else True)
    if node.get("negate") and result is not None:
        result = not result
    return result


def _recorded(value: Any) -> str:
    """A dimension value, or "" when none is recorded — including the
    "Unassigned" placeholder the cost snapshot writes for a missing one."""
    text = str(value or "").strip()
    return "" if text == UNASSIGNED else text


def _dimension(row: dict[str, Any], dim: str) -> str:
    value = _recorded(row.get(dim))
    if not value and row.get("_master"):
        value = _recorded(row["_master"].get("work_location" if dim == "location" else dim))
    return value


def applicability(rule: ValidationRuleVersion, row: dict[str, Any]) -> tuple[bool | None, str]:
    """Whether the rule applies to this employee: True, False, or None (not recorded)."""
    if rule.state:
        state = str(row.get("location_state") or row.get("work_state") or row.get("state")
                    or (row.get("_master") or {}).get("work_state") or "").strip()
        if not state:
            return None, "work state is missing"
        if state.casefold() != rule.state.casefold():
            return False, ""
    for dim, values in (getattr(rule, "applies_to", None) or {}).items():
        have = _dimension(row, dim)
        if not have:
            return None, f"{dim.replace('_', ' ')} is not recorded"
        if have.casefold() not in {str(v).strip().casefold() for v in values}:
            return False, ""
    return True, ""


def evaluate(rule: ValidationRuleVersion, row: dict[str, Any]) -> dict[str, Any] | None:
    """A finding when the rule fails or cannot be evaluated; None when it passes or does not apply."""
    return outcome(rule, row)[1]


def outcome(rule: ValidationRuleVersion, row: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    """
    What the rule concluded for one employee, and the finding if there is one.

    ``passed``, ``out_of_scope`` (applicability or condition says no), ``failed``,
    ``cannot_validate``, or ``skipped`` — an input was missing and the rule says
    to skip. Kept distinct so a preview never reports skipped employees as if
    they had passed.
    """
    employee_id = str(row.get("employee_id") or "")
    on_missing = getattr(rule, "on_missing", None) or "cannot_validate"
    cache: dict[str, Any] = {}
    actual: Any = ""
    expected: Any = ""

    applies, why = applicability(rule, row)
    if applies is False:
        return "out_of_scope", None
    if applies is None:
        missing = f"Cannot validate: {why}"
        expected = rule.state or ""
    else:
        when = condition_result(rule.condition, row, cache)
        if when is False:
            return "out_of_scope", None
        if when is None:
            missing = "Cannot validate: condition input is missing or invalid"
        else:
            passed, actual, expected = _compare(rule.assertion, row, cache)
            if passed is True:
                return "passed", None
            missing = "" if passed is False else "Cannot validate: required mapped input is missing or invalid"

    if missing:
        if on_missing == "skip":
            return "skipped", None
        problem = (missing.replace("Cannot validate: ", "Treated as a failure because ")
                   if on_missing == "fail" else missing)
    else:
        problem = "Value does not satisfy the approved rule"
    is_missing = bool(missing) and on_missing == "cannot_validate"
    return ("cannot_validate" if is_missing else "failed"), {
        "employee_id": employee_id,
        "employee_name": row.get("employee_name") or "",
        "rule_id": rule.rule_key,
        "rule_name": rule.name,
        "component": rule.assertion["left"].get("key") or "value",
        "expected_value": _display(expected),
        "actual_value": _display(actual),
        "difference": "",
        "severity": "CRITICAL" if rule.blocks_signoff else rule.severity,
        "status": "FAIL",
        "reason": f"{problem}. Rule {rule.rule_key} v{rule.version}; source: {rule.source_reference or 'company policy'}.",
        "suggested_fix": rule.suggested_fix or "Review the register and the rule mapping.",
        "financial_impact": 0,
        "rule_version_id": str(rule.id),
        "evidence": {
            "version": rule.version, "source_reference": rule.source_reference,
            "condition": rule.condition, "assertion": rule.assertion,
            "applies_to": getattr(rule, "applies_to", None), "on_missing": on_missing,
            "responsible_team": rule.responsible_team, "blocks_signoff": rule.blocks_signoff,
            "unverifiable": is_missing,
        },
    }


def stored_row(row) -> dict[str, Any]:
    components = {normalize_col(k): v for k, v in (row.components or {}).items()}
    deductions = row.deductions or {}
    return {
        "employee_id": row.employee_id, "employee_name": row.employee_name,
        "components": components, "deductions": deductions,
        "paid_days": row.paid_days, "lop_days": row.lop_days,
        "net_pay": row.net_pay, "gross": sum((Decimal(str(v or 0)) for v in components.values()), Decimal("0")),
        # The snapshot's "Unassigned" means nothing was recorded; say so.
        **{k: v for k, v in (row.dimensions or {}).items() if _recorded(v)},
        **deductions,
    }


def master_dict(record) -> dict[str, Any] | None:
    if record is None:
        return None
    return {f: getattr(record, f, None) for f in MASTER_FIELDS}


# ---------------------------------------------------------------------------
# Conflicts
# ---------------------------------------------------------------------------
def _canonical(node: Any) -> str:
    return json.dumps(node, sort_keys=True, default=str)


def _dates_overlap(a: ValidationRuleVersion, b: ValidationRuleVersion) -> bool:
    a_end = a.effective_to or date.max
    b_end = b.effective_to or date.max
    return a.effective_from <= b_end and b.effective_from <= a_end


def _scope_overlaps(a: ValidationRuleVersion, b: ValidationRuleVersion) -> bool:
    if a.state and b.state and a.state.casefold() != b.state.casefold():
        return False
    da, dbb = a.applies_to or {}, b.applies_to or {}
    for dim in set(da) & set(dbb):
        if not {str(v).casefold() for v in da[dim]} & {str(v).casefold() for v in dbb[dim]}:
            return False
    return True


def _interval(assertion: dict) -> tuple[Decimal, Decimal] | None:
    """The values of the left operand an assertion allows, when the right side is a number."""
    right = assertion.get("right") or {}
    if right.get("source") != "literal":
        return None
    value = _num(right.get("value"))
    if value is None:
        return None
    tol = _num(assertion.get("tolerance")) or Decimal("0")
    inf = Decimal("1e30")
    return {
        "eq": (value - tol, value + tol), "gt": (value + tol, inf), "gte": (value - tol, inf),
        "lt": (-inf, value - tol), "lte": (-inf, value + tol),
    }.get(assertion.get("operator"))


def conflicts(rules: list[ValidationRuleVersion], configured_components: set[str]) -> list[dict[str, Any]]:
    """
    Problems between rules that could be in force together.

    * ``contradiction`` — same scope, dates and condition, the same input, and
      no value can satisfy both assertions: every employee in scope fails one.
    * ``duplicate`` — two rules that test exactly the same thing: every failure
      is reported twice.
    * ``broken_reference`` — a rule reads a salary component that is no longer
      configured, so it can never be evaluated.
    """
    out: list[dict[str, Any]] = []
    for rule in rules:
        for source, key in references(rule):
            if source in ("component",) and normalize_col(key) not in configured_components:
                out.append({"kind": "broken_reference", "rules": [_ref(rule)],
                            "message": f"{rule.rule_key} v{rule.version} reads the component “{key}”, which is not configured."})
    for i, a in enumerate(rules):
        for b in rules[i + 1:]:
            if a.rule_key == b.rule_key or not _dates_overlap(a, b) or not _scope_overlaps(a, b):
                continue
            if _canonical(a.condition) != _canonical(b.condition):
                continue
            if (_canonical(a.assertion) == _canonical(b.assertion)
                    and _canonical(a.applies_to or {}) == _canonical(b.applies_to or {})
                    and (a.state or "").casefold() == (b.state or "").casefold()):
                out.append({"kind": "duplicate", "rules": [_ref(a), _ref(b)],
                            "message": f"{a.rule_key} and {b.rule_key} test the same thing; every failure would be reported twice."})
                continue
            if _canonical(a.assertion.get("left")) != _canonical(b.assertion.get("left")):
                continue
            ia, ib = _interval(a.assertion), _interval(b.assertion)
            if ia and ib and (ia[1] < ib[0] or ib[1] < ia[0]):
                out.append({"kind": "contradiction", "rules": [_ref(a), _ref(b)],
                            "message": f"{a.rule_key} and {b.rule_key} cannot both be satisfied: no value of "
                                       f"{a.assertion['left'].get('key') or 'the input'} passes both."})
    return out


def _ref(rule: ValidationRuleVersion) -> dict[str, Any]:
    return {"id": str(rule.id), "rule_key": rule.rule_key, "version": rule.version, "status": rule.status}
