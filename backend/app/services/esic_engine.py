"""
Config-Driven ESIC Engine
=========================
Replaces the hardcoded `_esic_amounts()` in validation.py.

All ESIC behaviour flows from ESICConfig (loaded via ConfigService):
  * Dynamic wage composition   — use_esic_applicable_flag OR include/exclude lists
  * Ceiling-based eligibility  — ESICEligibilityConfig.expression
  * Rounding mode              — up / down / nearest  (or custom expression)
  * Entry/exit logic flags

Entry point: compute_esic_wage() + compute_esic()
"""
from __future__ import annotations

import math
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from app.models.component import ComponentConfig
from app.schemas.statutory_config import ESICConfig
from app.services.config_service import safe_eval_expr

CENT = Decimal("0.01")


def _q(v: Decimal) -> Decimal:
    return v.quantize(CENT, rounding=ROUND_HALF_UP)


def _dec(v: Any) -> Decimal:
    if v is None:
        return Decimal("0")
    try:
        return Decimal(str(v))
    except Exception:
        return Decimal("0")


def _round_esic(amount: Decimal, mode: str) -> Decimal:
    if amount == 0:
        return amount
    f = float(amount)
    if mode == "down":
        return Decimal(str(int(math.floor(f))))
    if mode == "nearest":
        return Decimal(str(int(round(f))))
    return Decimal(str(int(math.ceil(f))))  # default "up"


def compute_esic_wage(
    regular: dict[str, Decimal],
    comp_by_key: dict[str, ComponentConfig],
    esic_cfg: ESICConfig,
) -> Decimal:
    """
    Sum the ESIC wage from regular components, using tenant config to
    decide which components are included.
    """
    wage_cfg = esic_cfg.wage
    esic_wage = Decimal("0")

    if wage_cfg.use_esic_applicable_flag:
        exclude = {n.lower() for n in wage_cfg.exclude_components}
        for key, amt in regular.items():
            comp = comp_by_key.get(key)
            if comp and comp.esic_applicable and key.lower() not in exclude:
                esic_wage += amt
    else:
        include = {n.lower() for n in wage_cfg.include_components}
        exclude = {n.lower() for n in wage_cfg.exclude_components}
        for key, amt in regular.items():
            k_lower = key.lower()
            if k_lower in include and k_lower not in exclude:
                esic_wage += amt

    return esic_wage


def compute_esic(
    esic_wage: Decimal,
    esic_cfg: ESICConfig,
    employment_type: str = "employee",
) -> dict[str, Any]:
    """
    Compute ESIC employee + employer contributions using ESICConfig.

    Returns:
        esic_eligible, esic_employee, esic_employer
    """
    rates    = esic_cfg.rates
    wage_cfg = esic_cfg.wage
    rounding = esic_cfg.rounding
    elig_cfg = esic_cfg.eligibility
    ceiling  = wage_cfg.wage_ceiling

    # Evaluate eligibility expression
    if employment_type.lower() in [e.lower() for e in elig_cfg.exempt_employment_types]:
        eligible = False
    else:
        ctx: dict[str, Any] = {
            "esic_wage":    float(esic_wage),
            "esic_ceiling": float(ceiling),
            "employee_type": employment_type,
        }
        try:
            eligible = bool(safe_eval_expr(elig_cfg.expression, ctx))
        except Exception:
            eligible = 0 < float(esic_wage) <= float(ceiling)

    if not eligible:
        return {"esic_eligible": False, "esic_employee": 0.0, "esic_employer": 0.0,
                "_ceiling": float(ceiling), "_emp_rate": float(rates.employee_rate),
                "_er_rate": float(rates.employer_rate)}

    # Custom expression override for contribution amount
    if rounding.expression and rounding.expression.strip():
        ctx = {
            "esic_wage": float(esic_wage),
            "rate_emp": float(rates.employee_rate),
            "rate_er":  float(rates.employer_rate),
            "ceil": math.ceil, "floor": math.floor, "round": round,
        }
        try:
            emp_val = float(safe_eval_expr(rounding.expression, ctx))
            emp = Decimal(str(emp_val))
            # Employer still computed by standard rate
            emr = _round_esic(esic_wage * _dec(rates.employer_rate), rounding.mode)
        except Exception:
            emp = _round_esic(esic_wage * _dec(rates.employee_rate), rounding.mode)
            emr = _round_esic(esic_wage * _dec(rates.employer_rate), rounding.mode)
    else:
        emp = _round_esic(esic_wage * _dec(rates.employee_rate), rounding.mode)
        emr = _round_esic(esic_wage * _dec(rates.employer_rate), rounding.mode)

    return {
        "esic_eligible": True,
        "esic_employee": float(emp),
        "esic_employer": float(emr),
        "_ceiling":      float(ceiling),
        "_emp_rate":     float(rates.employee_rate),
        "_er_rate":      float(rates.employer_rate),
    }
