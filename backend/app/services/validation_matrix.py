"""Safe, deterministic validation matrix evaluation. No user-supplied Python or SQL."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.orm import Session

from app.models import ValidationRuleVersion
from app.services.payroll_parse import normalize_col

FIELDS = {
    "employee_id", "location_state", "work_state", "state", "department",
    "designation", "total_days", "paid_days", "lop_days", "net_pay",
    "gross", "pf_employee", "esic_employee", "pt", "lwf_employee", "tds",
    "pan", "uan", "ifsc", "bank_account", "location", "skill_category",
    "employment_type", "business_unit", "cost_center", "tax_regime", "doj", "dol",
}
DEDUCTIONS = {"pf_employee", "pf_employer", "esic_employee", "esic_employer", "pt", "lwf_employee", "lwf_employer", "tds"}
NUMERIC_FIELDS = {"total_days", "paid_days", "lop_days", "net_pay", "gross", *DEDUCTIONS}
OPS = {"eq", "ne", "gt", "gte", "lt", "lte", "present", "in", "not_in"}


def validate_comparison(comparison: dict, configured_components: set[str]) -> None:
    for operand in (comparison["left"], comparison["right"]):
        source, key = operand["source"], operand.get("key")
        if source == "field" and key not in FIELDS:
            raise ValueError(f"Unknown field: {key}")
        if source == "deduction" and key not in DEDUCTIONS:
            raise ValueError(f"Unknown deduction: {key}")
        if source == "component" and normalize_col(key or "") not in configured_components:
            raise ValueError(f"Salary component is not configured: {key}")
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


def published_for(db: Session, entity_id, period: date) -> list[ValidationRuleVersion]:
    rows = db.query(ValidationRuleVersion).filter(
        ValidationRuleVersion.entity_id == entity_id,
        ValidationRuleVersion.status == "published",
        ValidationRuleVersion.effective_from <= period,
    ).all()
    chosen: dict[str, ValidationRuleVersion] = {}
    for row in rows:
        if row.effective_to and row.effective_to < period:
            continue
        prior = chosen.get(row.rule_key)
        if prior is None or (row.effective_from, row.version) > (prior.effective_from, prior.version):
            chosen[row.rule_key] = row
    return list(chosen.values())


def _resolve(operand: dict, row: dict[str, Any]) -> Any:
    source = operand["source"]
    if source == "literal":
        return operand.get("value")
    key = operand["key"]
    if source == "component":
        return (row.get("components") or {}).get(normalize_col(key))
    if source == "deduction":
        deductions = row.get("deductions") or {}
        return deductions.get(key, row.get(key))
    return row.get(key)


def _compare(comparison: dict, row: dict[str, Any]) -> tuple[bool | None, Any, Any]:
    left, right = _resolve(comparison["left"], row), _resolve(comparison["right"], row)
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


def evaluate(rule: ValidationRuleVersion, row: dict[str, Any]) -> dict[str, Any] | None:
    employee_id = str(row.get("employee_id") or "")
    state = str(row.get("location_state") or row.get("work_state") or row.get("state") or "").strip()
    if rule.state and state.casefold() != rule.state.casefold():
        if state:
            return None
        problem = "Cannot validate: work state is missing"
        actual, expected = "", rule.state
    else:
        if rule.condition:
            group = rule.condition
            items = group.get("items", [group])
            results = [_compare(item, row)[0] for item in items]
            mode = group.get("mode", "all")
            if (mode == "all" and False in results) or (mode == "any" and True not in results and None not in results):
                return None
            if None in results and (mode == "all" or True not in results):
                problem, actual, expected = "Cannot validate: condition input is missing or invalid", "", ""
            else:
                problem = ""
        else:
            problem = ""
        if not problem:
            passed, actual, expected = _compare(rule.assertion, row)
            if passed is True:
                return None
            problem = (
                "Cannot validate: required mapped input is missing or invalid"
                if passed is None else "Value does not satisfy the approved rule"
            )
    is_missing = problem.startswith("Cannot validate")
    return {
        "employee_id": employee_id,
        "employee_name": row.get("employee_name") or "",
        "rule_id": rule.rule_key,
        "rule_name": rule.name,
        "component": rule.assertion["left"].get("key") or "value",
        "expected_value": str(expected) if expected is not None else "",
        "actual_value": str(actual) if actual is not None else "",
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
        **(row.dimensions or {}),
        **deductions,
    }
