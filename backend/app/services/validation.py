from __future__ import annotations

import calendar
import math
import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models import (
    ComponentConfig,
    CtcRecord,
    LwfRate,
    PtSlab,
    SalaryRegister,
    SalaryRegisterRow,
    SlabRule,
    StatutorySettings,
    User,
)
from app.services.config_service import ConfigService
from app.services.esic_engine import compute_esic, compute_esic_wage
from app.services.payroll_parse import normalize_col
from app.services.pf_engine import compute_pf, compute_pf_wage
from app.services.risk_scoring import compute_risk, risk_distribution
from app.services.rule_engine_v2 import (
    ValidationFinding,
    batch_findings,
    build_findings,
    summarise_findings,
)


CENT = Decimal("0.01")
LOP_TOLERANCE = Decimal("1.00")
ARREAR_TOLERANCE = Decimal("1.00")


def _dec(v: Any) -> Decimal:
    if v is None or v == "":
        return Decimal("0")
    try:
        return Decimal(str(v))
    except Exception:
        return Decimal("0")


def _q(v: Decimal) -> Decimal:
    return v.quantize(CENT, rounding=ROUND_HALF_UP)


def _round_esic(amount: Decimal, mode: str) -> Decimal:
    if amount == 0:
        return amount
    f = float(amount)
    if mode == "down":
        return Decimal(str(int(math.floor(f))))
    if mode == "nearest":
        return Decimal(str(int(round(f))))
    return Decimal(str(int(math.ceil(f))))


def month_iter(d_from: date | None, d_to: date | None) -> list[str]:
    if not d_from or not d_to:
        return []
    y, m = d_from.year, d_from.month
    labels: list[str] = []
    while (y, m) <= (d_to.year, d_to.month):
        labels.append(f"{calendar.month_abbr[m]}-{y}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return labels


def num_months(d_from: date | None, d_to: date | None) -> int:
    n = len(month_iter(d_from, d_to))
    return n if n > 0 else 1


def _months_between_inclusive(d_from: date, d_to: date) -> int:
    """Inclusive month count (e.g. Apr->Jun = 3)."""
    if d_to < d_from:
        return 0
    return (d_to.year - d_from.year) * 12 + (d_to.month - d_from.month) + 1


def _prev_month(d: date) -> date:
    if d.month == 1:
        return date(d.year - 1, 12, 1)
    return date(d.year, d.month - 1, 1)


_FREQ_MULTIPLIER: dict[str, int] = {
    "monthly": 1,
    "quarterly": 3,
    "half-yearly": 6,
    "yearly": 12,
}


def _annualize_factor(frequency: str) -> int:
    """How many *months* of wage one slab period represents.

    Tenant slab brackets compare against a wage scaled to the same period
    (monthly wage * factor) and the resulting deduction is divided by the
    same factor to get the per-month equivalent reported in the run.
    """
    return _FREQ_MULTIPLIER.get(frequency, 1)


def _normalize_gender(g: Any) -> str:
    """Coerce free-text gender values into MALE / FEMALE / ALL."""
    if g is None:
        return "ALL"
    s = str(g).strip().upper()
    if s in ("M", "MALE"):
        return "MALE"
    if s in ("F", "FEMALE"):
        return "FEMALE"
    return "ALL"


def lookup_pt(
    db: Session,
    state: str | None,
    wage: Decimal,
    as_of: date,
    user_id: Any | None = None,
    gender: str | None = None,
    run_month: int | None = None,
) -> tuple[Decimal, str | None]:
    """Return *monthly-equivalent* PT deduction and a slab label.

    Lookup order:
      1. Tenant `slab_rules` (rule_type='PT') — supports frequency, gender
         (MALE / FEMALE / ALL), and `applicable_months` for Feb-only top-ups.
      2. Seeded `PtSlab` reference (always treated as monthly, gender-blind).

    Among tenant rows that match the wage band we pick the **most specific**
    one, in this priority order:
      • month-specific row beats month-agnostic row (Feb top-up wins in Feb)
      • gender-specific row beats `ALL` row (employee's gender wins)
    """
    if not state:
        return Decimal("0"), None

    g_norm = _normalize_gender(gender)
    month = run_month if run_month is not None else as_of.month

    if user_id is not None:
        tenant_rows = (
            db.query(SlabRule)
            .filter(
                SlabRule.user_id == user_id,
                SlabRule.state == state,
                SlabRule.rule_type == "PT",
            )
            .order_by(SlabRule.sort_order, SlabRule.min_salary)
            .all()
        )
        if tenant_rows:
            best: tuple[int, int, SlabRule, Decimal, str] | None = None
            for r in tenant_rows:
                factor = _annualize_factor(r.frequency)
                w_period = float(wage) * factor
                lo, hi = float(r.min_salary), float(r.max_salary)
                if not (lo <= w_period <= hi):
                    continue
                row_gender = (r.gender or "ALL").upper()
                if row_gender not in ("ALL", g_norm):
                    continue
                months = r.applicable_months
                if months and month not in months:
                    continue
                month_score = 1 if months else 0
                gender_score = 1 if row_gender == g_norm and row_gender != "ALL" else 0
                monthly = Decimal(str(r.deduction_amount)) / Decimal(str(factor))
                label = f"{r.min_salary:g}-{r.max_salary:g} ({r.frequency}"
                if row_gender != "ALL":
                    label += f", {row_gender.lower()}"
                if months:
                    label += f", months={list(months)}"
                label += ")"
                candidate = (month_score, gender_score, r, _q(monthly), label)
                if best is None or candidate[:2] > best[:2]:
                    best = candidate
            if best is not None:
                return best[3], best[4]
            # Tenant has slabs but none matched — explicitly zero, do not fall
            # through to seed reference (would be misleading).
            return Decimal("0"), None

    slabs = (
        db.query(PtSlab)
        .filter(PtSlab.state == state)
        .filter(PtSlab.effective_from <= as_of)
        .filter((PtSlab.effective_to.is_(None)) | (PtSlab.effective_to >= as_of))
        .order_by(PtSlab.slab_min)
        .all()
    )
    w = float(wage)
    for s in slabs:
        smin, smax = float(s.slab_min), float(s.slab_max)
        if smin <= w <= smax:
            slab_label = f"{s.slab_min:g}-{s.slab_max:g}"
            return Decimal(str(s.amount)), slab_label
    return Decimal("0"), None


def lookup_lwf(
    db: Session,
    state: str | None,
    wage: Decimal,
    as_of: date,
    user_id: Any | None = None,
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    """Return (employee_per_period, employer_per_period, employee_monthly, employer_monthly).

    Tenant `slab_rules` (rule_type='LWF') override the seeded `LwfRate` rows.
    Each tenant row stores the per-period employee contribution in
    `deduction_amount` and the per-period employer contribution in
    `employer_amount`. The validator converts both to a monthly equivalent
    by dividing by the slab's frequency factor (1 for monthly, 6 for
    half-yearly, 12 for yearly).
    """
    if not state:
        return Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")

    if user_id is not None:
        tenant_rows = (
            db.query(SlabRule)
            .filter(
                SlabRule.user_id == user_id,
                SlabRule.state == state,
                SlabRule.rule_type == "LWF",
            )
            .order_by(SlabRule.sort_order, SlabRule.min_salary)
            .all()
        )
        if tenant_rows:
            for r in tenant_rows:
                factor = _annualize_factor(r.frequency)
                w_period = float(wage) * factor
                lo, hi = float(r.min_salary), float(r.max_salary)
                if lo <= w_period <= hi:
                    emp_period = Decimal(str(r.deduction_amount))
                    er_period = Decimal(str(r.employer_amount or 0))
                    emp_monthly = _q(emp_period / Decimal(str(factor)))
                    er_monthly = _q(er_period / Decimal(str(factor)))
                    return emp_period, er_period, emp_monthly, er_monthly
            return Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")

    bands = (
        db.query(LwfRate)
        .filter(LwfRate.state == state)
        .filter(LwfRate.effective_from <= as_of)
        .filter((LwfRate.effective_to.is_(None)) | (LwfRate.effective_to >= as_of))
        .all()
    )
    w = float(wage)
    for b in bands:
        if float(b.wage_band_min) <= w <= float(b.wage_band_max):
            return (
                Decimal(str(b.employee_rate)),
                Decimal(str(b.employer_rate)),
                Decimal(str(b.employee_rate)),
                Decimal(str(b.employer_rate)),
            )
    return Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")


def _component_key_map(components: list[ComponentConfig]) -> dict[str, ComponentConfig]:
    return {normalize_col(c.component_name): c for c in components}


def normalize_row_key(name: str) -> str:
    return normalize_col(name)


SPECIAL_NUMERIC_KEYS = {
    "paid_days",
    "lop_days",
    "lop",
    "total_days",
    "month_days",
    "days_in_month",
    "pf_employee",
    "pf_employer",
    "pf_emp",
    "esic_employee",
    "esic_employer",
    "pt",
    "pt_amount",
    "lwf_employee",
    "lwf_employer",
}


def split_row_amounts(
    row: dict[str, Any],
    comp_by_key: dict[str, ComponentConfig],
) -> tuple[dict[str, Decimal], dict[str, Decimal], Decimal]:
    """Returns (regular_by_component_key, arrear_by_base_key, increment_arrear_total)."""
    regular: dict[str, Decimal] = {}
    arrear: dict[str, Decimal] = {}
    inc_total = Decimal("0")

    reserved = {
        "employee_id",
        "emp_id",
        "employee_code",
        "employee_name",
        "name",
        "location",
        "location_state",
        "state",
        "state_pt",
        "state_lwf",
        "work_state",
        "employment_type",
        "department",
        "designation",
        "gender",
        "sex",
    } | SPECIAL_NUMERIC_KEYS

    for raw_key, raw_val in row.items():
        if raw_key is None:
            continue
        k = normalize_col(str(raw_key))
        if k in reserved or k.startswith("_"):
            continue

        val = _dec(raw_val)

        lk = k.lower()
        if "increment" in lk and "arrear" in lk:
            inc_total += val
            continue

        m = re.match(r"^(.+)_arrear$", k)
        if m:
            base = normalize_col(m.group(1))
            if base in comp_by_key:
                arrear[base] = arrear.get(base, Decimal("0")) + val
            continue

        if k in comp_by_key:
            regular[k] = regular.get(k, Decimal("0")) + val

    return regular, arrear, inc_total


def sum_flagged(
    amounts: dict[str, Decimal],
    comp_by_key: dict[str, ComponentConfig],
    flag: str,
) -> Decimal:
    total = Decimal("0")
    for key, amt in amounts.items():
        c = comp_by_key.get(key)
        if c and getattr(c, flag):
            total += amt
    return total


def taxable_exposure(components: list[ComponentConfig], regular: dict[str, Decimal]) -> Decimal:
    t = Decimal("0")
    comp_by_key = _component_key_map(components)
    for k, amt in regular.items():
        c = comp_by_key.get(k)
        if c and c.taxable:
            t += amt
    return t


def _get_or_default_settings(db: Session, user: User) -> StatutorySettings:
    row = db.query(StatutorySettings).filter(StatutorySettings.user_id == user.id).first()
    if row:
        return row
    row = StatutorySettings(user_id=user.id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _latest_ctcs(db: Session, user_id, employee_id: str, as_of: date) -> list[CtcRecord]:
    return (
        db.query(CtcRecord)
        .filter(CtcRecord.user_id == user_id, CtcRecord.employee_id == employee_id)
        .filter(CtcRecord.effective_from <= as_of)
        .order_by(CtcRecord.effective_from.desc())
        .limit(2)
        .all()
    )


def _prior_register_rows(db: Session, user_id, period_month: date) -> dict[str, SalaryRegisterRow]:
    prev = _prev_month(period_month)
    register = (
        db.query(SalaryRegister)
        .filter(SalaryRegister.user_id == user_id, SalaryRegister.period_month == prev)
        .first()
    )
    if not register:
        return {}
    rows = db.query(SalaryRegisterRow).filter(SalaryRegisterRow.register_id == register.id).all()
    return {r.employee_id: r for r in rows}


# _pf_breakup and _esic_amounts have been replaced by pf_engine.compute_pf()
# and esic_engine.compute_esic() respectively.
# These thin wrappers remain for any legacy callers during transition.

def _pf_breakup_legacy(pf_wage: Decimal, settings: StatutorySettings) -> dict[str, Any]:
    """Legacy adapter — routes through the new config-driven engine using StatutorySettings."""
    from app.schemas.statutory_config import (
        PFConfig, PFRateConfig, PFWageConfig,
    )
    from decimal import Decimal as D

    pf_cfg = PFConfig(
        rates=PFRateConfig(
            employee_rate=D(str(settings.pf_employee_rate)),
            employer_rate=D(str(settings.pf_employer_rate)),
            eps_rate=D(str(settings.pf_eps_rate)),
            edli_rate=D(str(settings.pf_edli_rate)),
            admin_rate=D(str(settings.pf_admin_rate)),
        ),
        wage=PFWageConfig(
            wage_ceiling=D(str(settings.pf_wage_ceiling)),
            restrict_to_ceiling=settings.pf_restrict_to_ceiling,
        ),
    )
    return compute_pf(pf_wage, pf_cfg)


def _esic_amounts_legacy(esic_wage: Decimal, settings: StatutorySettings) -> dict[str, Any]:
    """Legacy adapter — routes through the new config-driven engine."""
    from app.schemas.statutory_config import (
        ESICConfig, ESICRateConfig, ESICWageConfig, ESICRoundingConfig,
    )
    from decimal import Decimal as D

    esic_cfg = ESICConfig(
        rates=ESICRateConfig(
            employee_rate=D(str(settings.esic_employee_rate)),
            employer_rate=D(str(settings.esic_employer_rate)),
        ),
        wage=ESICWageConfig(wage_ceiling=D(str(settings.esic_wage_ceiling))),
        rounding=ESICRoundingConfig(mode=settings.esic_round_mode),
    )
    return compute_esic(esic_wage, esic_cfg)


def _lop_proration_check(
    row: dict[str, Any],
    regular: dict[str, Decimal],
    paid_days: Decimal | None,
    lop_days: Decimal | None,
    days_in_month: int,
    ctc_monthly: dict[str, Decimal],
    comp_by_key: dict[str, ComponentConfig],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Validate prorated component values against monthly_rate * paid_days / total_days."""
    diffs: list[dict[str, Any]] = []
    errors: list[str] = []

    if paid_days is None and lop_days is None:
        return diffs, errors

    if paid_days is not None and lop_days is not None:
        total = paid_days + lop_days
        if abs(total - Decimal(days_in_month)) > Decimal("0.01"):
            errors.append(
                f"paid_days ({paid_days}) + lop_days ({lop_days}) != days_in_month ({days_in_month})."
            )

    if paid_days is None and lop_days is not None:
        paid_days = Decimal(days_in_month) - lop_days
    if paid_days is None:
        return diffs, errors

    if not ctc_monthly:
        return diffs, errors

    factor = paid_days / Decimal(days_in_month)

    for key, monthly in ctc_monthly.items():
        comp = comp_by_key.get(key)
        if not comp or not comp.included_in_wages:
            continue
        actual = regular.get(key, Decimal("0"))
        expected = _q(monthly * factor)
        delta = (actual - expected).copy_abs()
        if delta > LOP_TOLERANCE:
            diffs.append(
                {
                    "component": key,
                    "expected": float(expected),
                    "actual": float(actual),
                    "diff": float(actual - expected),
                }
            )
            errors.append(
                f"{key} LOP-prorated mismatch: expected {expected}, got {actual} "
                f"(diff {actual - expected})."
            )

    return diffs, errors


def _increment_arrears(
    ctcs: list[CtcRecord],
    period_month: date | None,
    effective_from: date | None,
    arrear_by_base: dict[str, Decimal],
    inc_arrear_total: Decimal,
    comp_by_key: dict[str, ComponentConfig],
) -> tuple[dict[str, Any], list[str]]:
    """If two CTCs exist and the latest one is effective within the arrear window,
    expected per-component arrear = (new_monthly - old_monthly) * months_in_window.
    Compare to per-component arrears + increment_arrear_total in the register."""
    info: dict[str, Any] = {
        "applicable": False,
        "expected_total": 0.0,
        "expected_components": {},
        "months": 0,
        "actual_total": float(sum(arrear_by_base.values(), start=Decimal("0")) + inc_arrear_total),
    }
    errors: list[str] = []

    if len(ctcs) < 2 or not period_month:
        return info, errors

    new_ctc, old_ctc = ctcs[0], ctcs[1]
    if new_ctc.effective_from <= old_ctc.effective_from:
        return info, errors

    window_from = effective_from or new_ctc.effective_from
    if new_ctc.effective_from > period_month:
        return info, errors
    if window_from > period_month:
        return info, errors

    arrear_start = max(window_from, new_ctc.effective_from)
    if arrear_start > period_month:
        return info, errors

    months = _months_between_inclusive(arrear_start, period_month) - 1
    if months <= 0:
        return info, errors

    expected_components: dict[str, float] = {}
    expected_total = Decimal("0")
    for k, new_annual in (new_ctc.annual_components or {}).items():
        old_annual = (old_ctc.annual_components or {}).get(k, 0)
        new_m = Decimal(str(new_annual)) / Decimal(12)
        old_m = Decimal(str(old_annual)) / Decimal(12)
        diff_per_month = _q(new_m - old_m)
        if diff_per_month == 0:
            continue
        per_comp_total = _q(diff_per_month * Decimal(months))
        expected_components[k] = float(per_comp_total)
        expected_total += per_comp_total

    info["applicable"] = True
    info["months"] = months
    info["expected_components"] = expected_components
    info["expected_total"] = float(expected_total)

    actual_inc = inc_arrear_total
    actual_per_comp_total = sum(arrear_by_base.values(), start=Decimal("0"))
    actual_combined = actual_inc + actual_per_comp_total

    if (actual_combined - expected_total).copy_abs() > ARREAR_TOLERANCE:
        errors.append(
            f"Increment arrears mismatch: expected {_q(expected_total)} across {months} month(s), "
            f"got {_q(actual_combined)} (per-component {actual_per_comp_total} + "
            f"increment_arrear_total {actual_inc})."
        )

    for k, exp_amt in expected_components.items():
        actual_k = arrear_by_base.get(k, Decimal("0"))
        if (actual_k - Decimal(str(exp_amt))).copy_abs() > ARREAR_TOLERANCE and inc_arrear_total == 0:
            errors.append(
                f"{k} arrear missing or off: expected {exp_amt}, got {float(actual_k)}."
            )

    return info, errors


def _prior_month_diff(
    employee_id: str,
    regular: dict[str, Decimal],
    inc_arrear_total: Decimal,
    arrear_by_base: dict[str, Decimal],
    prior_rows: dict[str, SalaryRegisterRow],
) -> tuple[dict[str, Any], list[str]]:
    info: dict[str, Any] = {
        "is_joiner": False,
        "is_continuing": False,
        "changed_components": {},
    }
    errors: list[str] = []

    if not prior_rows:
        # No prior register exists at all — every employee is effectively a joiner
        # for this run from a MoM perspective.
        info["is_joiner"] = True
        return info, errors

    prior = prior_rows.get(employee_id)
    if not prior:
        info["is_joiner"] = True
        return info, errors

    info["is_continuing"] = True
    prior_components = prior.components or {}
    has_arrears = (
        inc_arrear_total > 0
        or any(v > 0 for v in arrear_by_base.values())
    )

    keys = set(prior_components.keys()) | set(regular.keys())
    changed: dict[str, dict[str, float]] = {}
    for k in keys:
        old = Decimal(str(prior_components.get(k, 0)))
        new = regular.get(k, Decimal("0"))
        if (new - old).copy_abs() > Decimal("1"):
            changed[k] = {"prior": float(old), "current": float(new), "diff": float(new - old)}

    info["changed_components"] = changed

    if changed and not has_arrears:
        names = ", ".join(sorted(changed.keys()))
        errors.append(
            f"Components changed vs prior month without arrears: {names}. "
            f"Confirm via increment-arrear run or update CTC."
        )

    return info, errors


def _compare_uploaded(
    row: dict[str, Any],
    keys: list[str],
    expected: Decimal,
    label: str,
    tol: Decimal = Decimal("1"),
) -> str | None:
    for k in keys:
        if k in row and row[k] not in (None, ""):
            actual = _dec(row[k])
            if (actual - expected).copy_abs() > tol:
                return f"{label} mismatch: expected {expected}, register has {actual} (diff {actual - expected})."
            return None
    return None


def validate_employees(
    db: Session,
    user: User,
    components: list[ComponentConfig],
    employees: list[dict[str, Any]],
    run_type: str,
    effective_from: date | None,
    effective_to: date | None,
    as_of: date | None,
    period_month: date | None = None,
) -> list[dict[str, Any]]:
    as_of = as_of or date.today()

    # ── Load configs ──────────────────────────────────────────────────────────
    # ConfigService provides the config-driven PF/ESIC settings; we also keep
    # StatutorySettings for PT/LWF state lists which are not yet in ConfigService.
    cfg_svc  = ConfigService(db)
    pf_cfg   = cfg_svc.get_pf_config(user.id)
    esic_cfg = cfg_svc.get_esic_config(user.id)
    settings = _get_or_default_settings(db, user)   # still used for PT/LWF states

    comp_by_key = _component_key_map(components)
    pt_states_cfg: list[str] = list(settings.pt_states or [])
    lwf_states_cfg: list[str] = list(settings.lwf_states or [])
    default_pt_state = pt_states_cfg[0] if pt_states_cfg else None
    default_lwf_state = lwf_states_cfg[0] if lwf_states_cfg else None
    months = num_months(effective_from, effective_to)
    month_labels = month_iter(effective_from, effective_to)

    pf_ceiling   = pf_cfg.wage.wage_ceiling
    esic_ceiling = esic_cfg.wage.wage_ceiling

    if period_month:
        period_month = period_month.replace(day=1)
        days_in_month = calendar.monthrange(period_month.year, period_month.month)[1]
    else:
        days_in_month = calendar.monthrange(as_of.year, as_of.month)[1]
    # Note: individual rows may override days_in_month via total_days / month_days column

    prior_rows = _prior_register_rows(db, user.id, period_month) if period_month else {}

    results: list[dict[str, Any]] = []

    for row in employees:
        eid = str(
            row.get("employee_id") or row.get("emp_id") or row.get("employee_code") or ""
        ).strip()
        if not eid:
            eid = "UNKNOWN"
        ename = row.get("employee_name") or row.get("name")
        if isinstance(ename, float):
            ename = str(int(ename)) if ename == int(ename) else str(ename)
        elif ename is not None:
            ename = str(ename)

        # Per-employee state for PT / LWF (multi-state tenants).
        # Looks for a "state" column on the register row; falls back to
        # the tenant's configured default. State must be one of the
        # tenant's configured states for that scheme; otherwise treated
        # as "no state" so PT / LWF won't be computed for that row.
        row_state_raw = (
            row.get("state")
            or row.get("work_state")
            or row.get("state_pt")
            or row.get("location_state")
        )
        row_state = str(row_state_raw).strip() if row_state_raw not in (None, "") else None

        if row_state and pt_states_cfg and row_state in pt_states_cfg:
            state_pt: str | None = row_state
        else:
            state_pt = default_pt_state

        if row_state and lwf_states_cfg and row_state in lwf_states_cfg:
            state_lwf: str | None = row_state
        else:
            state_lwf = default_lwf_state

        # Per-row working-days override: allow upload rows to carry
        # total_days / month_days / working_days to handle companies that use
        # 26-day payroll basis instead of calendar days.
        row_total_days_raw = (
            row.get("total_days")
            or row.get("month_days")
            or row.get("days_in_month")
            or row.get("working_days")
        )
        try:
            row_days_in_month: int = int(float(str(row_total_days_raw))) if row_total_days_raw not in (None, "") else days_in_month
        except (ValueError, TypeError):
            row_days_in_month = days_in_month
        # LOP proration uses per-row days; clamp to sane range
        if not (1 <= row_days_in_month <= 31):
            row_days_in_month = days_in_month

        regular, arrear_by_base, inc_arrear_total = split_row_amounts(row, comp_by_key)

        pf_wage = sum_flagged(regular, comp_by_key, "pf_applicable")
        esic_wage = sum_flagged(regular, comp_by_key, "esic_applicable")
        pt_base = sum_flagged(regular, comp_by_key, "pt_applicable")
        lwf_base = sum_flagged(regular, comp_by_key, "lwf_applicable")

        pf_arrear = sum_flagged(arrear_by_base, comp_by_key, "pf_applicable")
        esic_arrear = sum_flagged(arrear_by_base, comp_by_key, "esic_applicable")
        pt_arrear = sum_flagged(arrear_by_base, comp_by_key, "pt_applicable")
        lwf_arrear = sum_flagged(arrear_by_base, comp_by_key, "lwf_applicable")

        arrear_total = sum(arrear_by_base.values(), start=Decimal("0"))

        errors: list[str] = []
        tds_risk: list[str] = []

        # ── Config-driven PF / ESIC engines ──────────────────────────────────
        # Step 1: Recompute PF wage using config (may override flag-based sum above).
        employment_type = str(row.get("employment_type") or "employee").lower()

        pf_wage_cfg, pf_vol_wage = compute_pf_wage(regular, comp_by_key, pf_cfg)
        # pf_wage_cfg may differ from the flag-based pf_wage if config excludes/overrides.
        # Fall back to flag-based pf_wage only if config-based is zero and flag-based is non-zero
        # (e.g. no components have pf_applicable=True but config says use flag).
        effective_pf_wage = pf_wage_cfg if pf_wage_cfg > Decimal("0") else pf_wage

        pf_calc  = compute_pf(effective_pf_wage, pf_cfg, pf_vol_wage, employment_type)

        # Step 2: Recompute ESIC wage using config.
        esic_wage_cfg = compute_esic_wage(regular, comp_by_key, esic_cfg)
        effective_esic_wage = esic_wage_cfg if esic_wage_cfg > Decimal("0") else esic_wage

        esic_calc = compute_esic(effective_esic_wage, esic_cfg, employment_type)

        # Overwrite the locally computed pf_wage / esic_wage so the rest of the
        # function (PT, LWF, findings) uses the config-driven values.
        pf_wage   = effective_pf_wage
        esic_wage = effective_esic_wage

        msg = _compare_uploaded(
            row,
            ["pf_employee", "pf_emp"],
            Decimal(str(pf_calc["pf_employee"])),
            "PF employee",
        )
        if msg:
            errors.append(msg)
        msg = _compare_uploaded(
            row,
            ["pf_employer", "pf_employer_total"],
            Decimal(str(pf_calc["pf_employer_total"])),
            "PF employer",
        )
        if msg:
            errors.append(msg)
        msg = _compare_uploaded(
            row,
            ["esic_employee"],
            Decimal(str(esic_calc["esic_employee"])),
            "ESIC employee",
        )
        if msg:
            errors.append(msg)
        msg = _compare_uploaded(
            row,
            ["esic_employer"],
            Decimal(str(esic_calc["esic_employer"])),
            "ESIC employer",
        )
        if msg:
            errors.append(msg)

        # PT / LWF (tenant-managed slab_rules take precedence over seeded reference)
        emp_gender = row.get("gender") or row.get("sex")
        run_month = period_month.month if period_month else as_of.month
        pt_due, pt_slab = lookup_pt(
            db,
            state_pt,
            pt_base,
            as_of,
            user_id=user.id,
            gender=emp_gender,
            run_month=run_month,
        )
        lwf_erate, lwf_orate, lwf_eamt, lwf_oamt = lookup_lwf(
            db, state_lwf, lwf_base, as_of, user_id=user.id
        )

        msg = _compare_uploaded(row, ["pt", "pt_amount"], pt_due, "PT")
        if msg:
            errors.append(msg)
        msg = _compare_uploaded(row, ["lwf_employee"], lwf_eamt, "LWF employee")
        if msg:
            errors.append(msg)
        msg = _compare_uploaded(row, ["lwf_employer"], lwf_oamt, "LWF employer")
        if msg:
            errors.append(msg)

        # Arrear period checks (existing PF/ESIC band shift logic)
        arrear_months_count = len(month_labels) if month_labels else 0
        if run_type in ("arrear", "increment_arrear") and (effective_from is None or effective_to is None):
            errors.append("effective_month_from and effective_month_to are required for arrear runs.")

        if run_type in ("arrear", "increment_arrear") and effective_from and effective_to:
            per_m_pf = pf_arrear / Decimal(months)
            per_m_esic = esic_arrear / Decimal(months)
            per_m_pt = pt_arrear / Decimal(months)
            per_m_lwf = lwf_arrear / Decimal(months)

            for label in (month_labels or ["period"]):
                m_pf = pf_wage + per_m_pf
                m_esic = esic_wage + per_m_esic
                m_pt = pt_base + per_m_pt
                m_lwf = lwf_base + per_m_lwf

                if m_pf > pf_ceiling and pf_wage <= pf_ceiling:
                    errors.append(
                        f"PF arrear for {label} pushes PF wage above {pf_ceiling}; contribution should be capped."
                    )
                if m_esic > esic_ceiling and esic_wage <= esic_ceiling:
                    errors.append(
                        f"ESIC wage for {label} (with arrears) exceeds {esic_ceiling}; eligibility change detected."
                    )

                pt_due_m, _ = lookup_pt(
                    db, state_pt, m_pt, as_of, user_id=user.id,
                    gender=emp_gender, run_month=run_month,
                )
                pt_due_base, _ = lookup_pt(
                    db, state_pt, pt_base, as_of, user_id=user.id,
                    gender=emp_gender, run_month=run_month,
                )
                if pt_due_m != pt_due_base:
                    errors.append(f"PT slab may change for {label} when arrears are included.")

                _, _, lwf_e_m, _ = lookup_lwf(db, state_lwf, m_lwf, as_of, user_id=user.id)
                if lwf_e_m != lwf_eamt:
                    errors.append(f"LWF employee amount may change for {label} due to wage band shift.")

        # CTC-driven LOP & increment arrear checks
        ctcs = _latest_ctcs(db, user.id, eid, period_month or as_of) if eid != "UNKNOWN" else []
        ctc_monthly: dict[str, Decimal] = {}
        if ctcs:
            for k, v in (ctcs[0].annual_components or {}).items():
                ctc_monthly[k] = Decimal(str(v)) / Decimal(12)

        paid_days_raw = row.get("paid_days")
        lop_days_raw = row.get("lop_days") or row.get("lop")
        paid_days = _dec(paid_days_raw) if paid_days_raw not in (None, "") else None
        lop_days = _dec(lop_days_raw) if lop_days_raw not in (None, "") else None

        lop_diffs, lop_errors = _lop_proration_check(
            row, regular, paid_days, lop_days, row_days_in_month, ctc_monthly, comp_by_key
        )
        errors.extend(lop_errors)

        inc_info, inc_errors = _increment_arrears(
            ctcs,
            period_month,
            effective_from,
            arrear_by_base,
            inc_arrear_total,
            comp_by_key,
        )
        errors.extend(inc_errors)

        prior_info, prior_errors = _prior_month_diff(
            eid, regular, inc_arrear_total, arrear_by_base, prior_rows
        )
        errors.extend(prior_errors)

        # TDS risk heuristic
        taxable = taxable_exposure(components, regular)
        spike = taxable + (arrear_total * Decimal("0.3"))
        if spike > Decimal("500000") / 12:
            tds_risk.append("TDS slab not applied; high-income month possible due to arrears/bunching.")

        # Structured rule engine findings (v2)
        prior_components_map: dict[str, float] | None = None
        if prior_info.get("is_continuing") and eid in prior_rows:
            prior_components_map = {
                k: float(v)
                for k, v in (prior_rows[eid].components or {}).items()
            }
        elif prior_info.get("is_joiner"):
            prior_components_map = None  # new joiner — no prior

        emp_findings = build_findings(
            employee_id=eid,
            employee_name=ename if isinstance(ename, str) else None,
            row=row,
            comp_by_key=comp_by_key,
            regular=regular,
            arrear_by_base=arrear_by_base,
            inc_arrear_total=inc_arrear_total,
            paid_days=paid_days,
            lop_days=lop_days,
            days_in_month=row_days_in_month,
            pf_calc=pf_calc,
            esic_calc=esic_calc,
            pt_due=pt_due,
            lwf_eamt=lwf_eamt,
            lwf_oamt=lwf_oamt,
            prior_components=prior_components_map,
            prior_is_joiner=prior_info.get("is_joiner", False),
            lop_diffs=lop_diffs,
            inc_info=inc_info,
            tds_risk=tds_risk,
        )

        results.append(
            {
                "employee_id": eid,
                "employee_name": ename if isinstance(ename, str) else None,
                "pf_wage": float(pf_wage),
                "pf_type": pf_calc["pf_type"],
                "pf_amount_employee": pf_calc["pf_employee"],
                "pf_amount_employer": pf_calc["pf_employer_total"],
                "pf_breakup": {
                    "wage_capped": pf_calc["pf_wage_capped"],
                    "eps": pf_calc["pf_eps"],
                    "epf": pf_calc["pf_epf"],
                    "edli": pf_calc["pf_edli"],
                    "admin": pf_calc["pf_admin"],
                },
                "esic_wage": float(esic_wage),
                "esic_eligible": esic_calc["esic_eligible"],
                "esic_employee": esic_calc["esic_employee"],
                "esic_employer": esic_calc["esic_employer"],
                "pt_wage_base": float(pt_base),
                "pt_applicable_state": state_pt,
                "pt_monthly_slab": pt_slab,
                "pt_due": float(pt_due),
                "lwf_wage_base": float(lwf_base),
                "lwf_applicable_state": state_lwf,
                "lwf_employee_rate": float(lwf_erate),
                "lwf_employer_rate": float(lwf_orate),
                "lwf_employee": float(lwf_eamt),
                "lwf_employer": float(lwf_oamt),
                "paid_days": float(paid_days) if paid_days is not None else None,
                "lop_days": float(lop_days) if lop_days is not None else None,
                "days_in_month": days_in_month,
                "lop_check": {
                    "checked": bool(ctc_monthly) and (paid_days is not None or lop_days is not None),
                    "diffs": lop_diffs,
                },
                "increment_arrear": inc_info,
                "prior_month": prior_info,
                "run_type": run_type,
                "arrear_months": arrear_months_count,
                "arrear_total": float(arrear_total),
                "increment_arrear_total": float(inc_arrear_total),
                "tds_risk_flags": tds_risk,
                "errors": errors,
                "findings": [f.to_dict() for f in emp_findings],
                # risk placeholders — filled after batch_findings merge below
                "risk_score": 0,
                "risk_level": "LOW",
                "score_breakdown": {},
            }
        )

    # Batch-level findings (e.g. duplicate employee IDs)
    batch_fds = batch_findings(employees)

    # Attach batch findings to matching employee entries
    batch_by_eid: dict[str, list[ValidationFinding]] = {}
    for f in batch_fds:
        batch_by_eid.setdefault(f.employee_id, []).append(f)

    for rec in results:
        extra = batch_by_eid.get(rec["employee_id"], [])
        if extra:
            rec["findings"] = [f.to_dict() for f in extra] + rec["findings"]

    # Compute risk scores now that batch findings are merged
    for rec in results:
        risk = compute_risk(rec.get("findings", []))
        rec["risk_score"] = risk["risk_score"]
        rec["risk_level"] = risk["risk_level"]
        rec["score_breakdown"] = risk["score_breakdown"]

    # Build summary from finding dicts
    flat: list[dict] = []
    for rec in results:
        flat.extend(rec.get("findings", []))

    total_financial_impact = sum(
        float(f.get("financial_impact", 0) or 0)
        for f in flat if f.get("status") == "FAIL"
    )

    summary = {
        "total_findings": len(flat),
        "critical": sum(1 for f in flat if f.get("severity") == "CRITICAL" and f.get("status") == "FAIL"),
        "warning": sum(1 for f in flat if f.get("severity") == "WARNING" and f.get("status") == "FAIL"),
        "info": sum(1 for f in flat if f.get("severity") == "INFO"),
        "pass": sum(1 for f in flat if f.get("status") == "PASS"),
        "total_financial_impact": round(total_financial_impact, 2),
        "risk_distribution": risk_distribution(
            [{"risk_level": r["risk_level"]} for r in results]
        ),
    }

    # Rule-level breakdown
    rule_counts: dict[str, dict] = {}
    for f in flat:
        rid = f.get("rule_id", "")
        if rid not in rule_counts:
            rule_counts[rid] = {
                "rule_id": rid,
                "rule_name": f.get("rule_name", ""),
                "severity": f.get("severity", ""),
                "fail_count": 0,
            }
        if f.get("status") == "FAIL":
            rule_counts[rid]["fail_count"] += 1

    summary["rules_triggered"] = sorted(
        [v for v in rule_counts.values() if v["fail_count"] > 0],
        key=lambda x: x["fail_count"],
        reverse=True,
    )

    return results, summary
