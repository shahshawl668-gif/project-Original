"""The employee PF and ESIC formulas a company writes in the Statutory engine.

A formula, when set, is the company's statement of what the employee's PF (or
ESIC) should be. It replaces the engine's amount for that employee, so
validation compares the payslip with the company's own rule. A formula that
cannot be evaluated for a row is reported, never skipped silently, and the
engine's amount is kept for that row.

The formulas live inside the statutory configuration (``employee_formula`` on the
PF and ESIC settings), so they are dated, audited and fingerprinted with the
rest of it.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models import ComponentConfig, Entity, Formula
from app.services.formula_eval import FormulaError, evaluate_formula
from app.services.payroll_parse import normalize_col

# Names a formula can always use. A company's own salary components are added to
# these per entity, so a formula can say ``special_allowance`` or
# ``[Special Allowance]`` once that component exists.
BUILT_IN_INPUTS: list[tuple[str, str]] = [
    ("basic", "Basic"), ("da", "DA"), ("hra", "HRA"), ("gross", "Gross"),
    ("pf_wage", "PF Wage"), ("esic_wage", "ESIC Wage"), ("ctc_monthly", "CTC (Monthly)"),
    ("paid_days", "Paid Days"), ("lop_days", "LOP Days"), ("total_days", "Total Days"),
]


def component_inputs(db: Session, entity: Entity) -> list[dict[str, str]]:
    """The entity's configured salary components, as formula variables."""
    built_in = {key for key, _ in BUILT_IN_INPUTS}
    rows = db.query(ComponentConfig).filter(ComponentConfig.entity_id == entity.id).all()
    found = {normalize_col(r.component_name): r.component_name for r in rows}
    return [{"key": key, "label": label} for key, label in sorted(found.items())
            if key and key not in built_in]


def sample_variables(db: Session | None = None, entity: Entity | None = None) -> dict[str, float]:
    """Non-zero on purpose: used to check a formula is *valid*, and one that divides by a field is valid."""
    sample = {key: 1.0 for key, _ in BUILT_IN_INPUTS}
    sample["paid_days"] = sample["total_days"] = 30.0
    if db is not None and entity is not None:
        for component in component_inputs(db, entity):
            sample[component["key"]] = 1.0
    return sample


def explain(error: Exception) -> str:
    """Tell the user where a missing component is defined."""
    text = str(error)
    if "Unknown field" in text or "Unknown variable" in text:
        text += " If it is one of your salary components, add it under Configuration → Salary components first."
    return text


def check(db: Session, entity: Entity, expression: str, label: str) -> None:
    """Raise ValueError with a message for the screen when the formula cannot be read."""
    if not expression.strip():
        return
    try:
        evaluate_formula(expression, sample_variables(db, entity))
    except FormulaError as exc:
        raise ValueError(f"The {label} formula is not valid: {explain(exc)}") from exc
    except ZeroDivisionError:
        return  # divides by something that is zero for the sample values only; judged per row


def apply(
    pf_formula: str, esic_formula: str, pf_calc: dict[str, Any], esic_calc: dict[str, Any],
    regular: dict[str, Decimal], comp_keys: list[str], pf_wage: Decimal, esic_wage: Decimal,
    paid_days: Decimal | None, lop_days: Decimal | None, total_days: int,
) -> list[str]:
    """Overwrite the employee PF / ESIC amounts from the formulas. Returns problems to report."""
    if not (pf_formula or esic_formula):
        return []
    variables: dict[str, float] = dict.fromkeys(BUILT_IN_INPUTS_KEYS, 0.0)
    variables.update(dict.fromkeys(comp_keys, 0.0))
    variables.update({key: float(amount) for key, amount in regular.items()})
    variables.update(
        gross=float(sum(regular.values(), start=Decimal("0"))), pf_wage=float(pf_wage), esic_wage=float(esic_wage),
        paid_days=float(paid_days if paid_days is not None else total_days),
        lop_days=float(lop_days or 0), total_days=float(total_days),
    )
    problems: list[str] = []
    for rule_type, expression, target, field in (
        ("PF", pf_formula, pf_calc, "pf_employee"), ("ESIC", esic_formula, esic_calc, "esic_employee"),
    ):
        if not expression:
            continue
        try:
            value = evaluate_formula(expression, variables)
        except (FormulaError, ZeroDivisionError) as exc:
            problems.append(f"The {rule_type} formula could not be applied to this row ({exc}); "
                            "the rates and ceiling were used instead.")
            continue
        target[field] = float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        target["_formula"] = rule_type
    return problems


BUILT_IN_INPUTS_KEYS = [key for key, _ in BUILT_IN_INPUTS]

_OPERATORS = {">", "<", ">=", "<=", "==", "!="}


def _with_conditions(expression: str, conditions: list[dict[str, Any]]) -> str:
    parts = [f"{c['field']} {c['operator']} {c['value']}" for c in conditions
             if c.get("field") and c.get("operator") in _OPERATORS]
    if not parts:
        return expression
    return f"IF(AND({', '.join(parts)}), {expression}, 0)"


def fold_saved_formulas(db: Session) -> int:
    """
    One-off, repeatable: move formulas saved under the old Formula builder into the
    statutory configuration of their company, where they now live. Only fills a
    blank, so running it again changes nothing. Returns how many it moved.
    """
    from app.services.config_service import ConfigService

    moved = 0
    active = db.query(Formula).filter(Formula.is_active == True).all()  # noqa: E712
    for row in active:
        service = ConfigService(db)
        entity_id = row.entity_id
        if row.rule_type == "PF":
            cfg = service.get_pf_config(entity_id)
            if cfg.employee_formula:
                continue
            cfg.employee_formula = _with_conditions(row.expression, row.conditions or [])
            service.save_pf_config(entity_id, cfg)
        elif row.rule_type == "ESIC":
            cfg = service.get_esic_config(entity_id)
            if cfg.employee_formula:
                continue
            cfg.employee_formula = _with_conditions(row.expression, row.conditions or [])
            service.save_esic_config(entity_id, cfg)
        else:
            continue
        moved += 1
    return moved
