"""The PF and ESIC formulas a company saved in the Formula builder, applied to a register.

A saved, active formula is the company's statement of what the employee's PF (or
ESIC) should be. When one exists it replaces the engine's amount for that
employee, so validation compares the payslip with the company's own rule. A
formula that cannot be evaluated for a row is reported, never skipped silently,
and the engine's amount is kept for that row.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models import Formula
from app.services.formula_eval import FormulaError, evaluate_conditions, evaluate_formula

BUILT_INS = ("basic", "da", "hra", "gross", "pf_wage", "esic_wage", "ctc_monthly",
             "paid_days", "lop_days", "total_days")


def load_active(db: Session, entity_id) -> dict[str, Formula]:
    rows = db.query(Formula).filter(Formula.entity_id == entity_id, Formula.is_active == True).all()  # noqa: E712
    return {row.rule_type.upper(): row for row in rows}


def apply(
    formulas: dict[str, Formula], pf_calc: dict[str, Any], esic_calc: dict[str, Any],
    regular: dict[str, Decimal], comp_keys: list[str], pf_wage: Decimal, esic_wage: Decimal,
    paid_days: Decimal | None, lop_days: Decimal | None, total_days: int,
) -> list[str]:
    """Overwrite the employee PF / ESIC amounts from the saved formulas. Returns problems to report."""
    if not formulas:
        return []
    variables: dict[str, float] = {name: 0.0 for name in BUILT_INS}
    variables.update({key: 0.0 for key in comp_keys})
    variables.update({key: float(amount) for key, amount in regular.items()})
    variables.update(
        gross=float(sum(regular.values(), start=Decimal("0"))), pf_wage=float(pf_wage), esic_wage=float(esic_wage),
        paid_days=float(paid_days if paid_days is not None else total_days),
        lop_days=float(lop_days or 0), total_days=float(total_days),
    )
    problems: list[str] = []
    for rule_type, target, field in (("PF", pf_calc, "pf_employee"), ("ESIC", esic_calc, "esic_employee")):
        formula = formulas.get(rule_type)
        if formula is None:
            continue
        try:
            if formula.conditions and not evaluate_conditions(formula.conditions, variables):
                continue
            value = evaluate_formula(formula.expression, variables)
        except (FormulaError, ZeroDivisionError) as exc:
            problems.append(f"The saved {rule_type} formula could not be applied to this row ({exc}); "
                            "the Statutory engine amount was used instead.")
            continue
        target[field] = float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        target["_formula"] = f"{rule_type} v{formula.version}"
    return problems
