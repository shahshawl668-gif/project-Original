"""
Config-Driven PF Engine
=======================
Replaces the hardcoded `_pf_breakup()` in validation.py.

All PF behaviour flows from PFConfig (loaded via ConfigService):
  * Dynamic wage composition  — use_pf_applicable_flag OR include/exclude lists
  * Ceiling toggle            — restrict_to_ceiling
  * Voluntary PF              — voluntary.enabled + voluntary.components
  * Rate overrides            — employee_rate, eps_rate, edli_rate, admin_rate

The function compute_pf() is the single entry point.
"""
from __future__ import annotations

import math
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from app.models.component import ComponentConfig
from app.schemas.statutory_config import PFConfig
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


def compute_pf_wage(
    regular: dict[str, Decimal],
    comp_by_key: dict[str, ComponentConfig],
    pf_cfg: PFConfig,
    voluntary_amounts: dict[str, Decimal] | None = None,
) -> tuple[Decimal, Decimal]:
    """
    Compute (pf_wage, voluntary_pf_wage) from the employee's regular components.

    Parameters
    ----------
    regular          : normalised component amounts for this employee
    comp_by_key      : ComponentConfig lookup by normalised name
    pf_cfg           : PFConfig for this tenant
    voluntary_amounts: optional dict of voluntary PF component amounts

    Returns
    -------
    (statutory_pf_wage, voluntary_pf_wage)
    """
    wage_cfg = pf_cfg.wage
    pf_wage = Decimal("0")

    if wage_cfg.use_pf_applicable_flag:
        # Use ComponentConfig.pf_applicable flag directly
        exclude = {n.lower() for n in wage_cfg.exclude_components}
        for key, amt in regular.items():
            comp = comp_by_key.get(key)
            if comp and comp.pf_applicable and key.lower() not in exclude:
                pf_wage += amt
    else:
        # Use explicit include list
        include = {n.lower() for n in wage_cfg.include_components}
        exclude = {n.lower() for n in wage_cfg.exclude_components}
        for key, amt in regular.items():
            k_lower = key.lower()
            if k_lower in include and k_lower not in exclude:
                pf_wage += amt

    # Voluntary PF
    vol_wage = Decimal("0")
    if pf_cfg.voluntary.enabled and voluntary_amounts:
        vol_keys = {n.lower() for n in pf_cfg.voluntary.components}
        for key, amt in voluntary_amounts.items():
            if key.lower() in vol_keys:
                vol_wage += amt

    return pf_wage, vol_wage


def compute_pf(
    pf_wage: Decimal,
    pf_cfg: PFConfig,
    voluntary_wage: Decimal = Decimal("0"),
    employment_type: str = "employee",
) -> dict[str, Any]:
    """
    Full PF breakup computation using PFConfig.

    Returns a dict with:
        pf_type, pf_wage_capped, pf_employee, pf_employer_total,
        pf_eps, pf_epf, pf_edli, pf_admin,
        pf_voluntary_employee (if enabled)
    """
    rates    = pf_cfg.rates
    wage_cfg = pf_cfg.wage
    ceiling  = wage_cfg.wage_ceiling

    # Ceiling / voluntary logic
    if wage_cfg.restrict_to_ceiling:
        capped = min(pf_wage, ceiling)
        pf_type = "restricted" if pf_wage > ceiling else "unrestricted"
    else:
        capped = pf_wage
        pf_type = "uncapped"

    # Above-ceiling mode
    if pf_cfg.above_ceiling_mode == "employee_choice" and pf_wage > ceiling:
        # Employee voluntarily contributes on full wage
        capped = pf_wage
        pf_type = "voluntary_full"

    emp      = _q(capped * _dec(rates.employee_rate))
    emp_total = _q(capped * _dec(rates.employer_rate))

    eps_base = min(capped, ceiling)   # EPS always capped even in uncapped mode
    eps      = _q(eps_base * _dec(rates.eps_rate))
    epf      = _q(emp_total - eps)
    edli     = _q(eps_base * _dec(rates.edli_rate))
    admin    = _q(eps_base * _dec(rates.admin_rate))

    # Voluntary PF (above-ceiling employee-side)
    vol_emp = Decimal("0")
    if pf_cfg.voluntary.enabled and voluntary_wage > Decimal("0"):
        vol_emp = _q(voluntary_wage * _dec(rates.employee_rate))

    return {
        "pf_type":           pf_type,
        "pf_wage_capped":    float(capped),
        "pf_employee":       float(emp),
        "pf_employer_total": float(emp_total),
        "pf_eps":            float(eps),
        "pf_epf":            float(epf),
        "pf_edli":           float(edli),
        "pf_admin":          float(admin),
        "pf_voluntary_employee": float(vol_emp),
        # Used by rule_engine_v2 for STAT-001/002/003 checks
        "_ceiling":          float(ceiling),
        "_restrict":         wage_cfg.restrict_to_ceiling,
        "_emp_rate":         float(rates.employee_rate),
        "_er_rate":          float(rates.employer_rate),
    }
