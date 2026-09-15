"""
Minimum wage lookup and compliance checks.

Two decisions here are worth stating, because both could reasonably go the
other way and both change what the tool reports:

**What counts towards the floor.** Indian minimum wage is a floor on the wages
payable, but which components count is contested and varies by schedule — HRA,
overtime and bonus are commonly excluded. Rather than encode one reading, the
comparison basis is configurable per entity, and the finding says which basis
it used so a reviewer can disagree with the setting rather than with a number
whose derivation is invisible.

**A missing rate is a finding.** If no rate is on file for an employee's state
and skill, the check reports that it could not verify. Silence would let an
unmaintained rate table read as a clean bill of health, which is the most
dangerous thing a compliance tool can do.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.models import MinimumWageRate
from app.models.minimum_wage import ANY_SCHEDULE, ANY_ZONE

CENT = Decimal("0.01")


def _q(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _normalise(value: str | None) -> str:
    return (value or "").strip().lower()


def lookup_rate(
    db: Session,
    entity_id: uuid.UUID,
    *,
    state: str | None,
    skill_category: str | None,
    as_of: date,
    zone: str | None = None,
    scheduled_employment: str | None = None,
) -> MinimumWageRate | None:
    """
    The most specific rate in force for this employee on ``as_of``.

    Specificity beats recency: a row naming the employee's exact schedule and
    zone wins over a wildcard row, even if the wildcard was notified later.
    Among equally specific rows the latest effective date wins.
    """
    if not state or not skill_category:
        return None

    candidates = (
        db.query(MinimumWageRate)
        .filter(
            MinimumWageRate.entity_id == entity_id,
            MinimumWageRate.effective_from <= as_of,
        )
        .all()
    )

    wanted_state = _normalise(state)
    wanted_skill = _normalise(skill_category)
    wanted_zone = _normalise(zone)
    wanted_schedule = _normalise(scheduled_employment)

    matches: list[tuple[int, int, date, MinimumWageRate]] = []
    for rate in candidates:
        if rate.effective_to is not None and rate.effective_to < as_of:
            continue
        if _normalise(rate.state) != wanted_state:
            continue
        if _normalise(rate.skill_category) != wanted_skill:
            continue

        zone_score = _match_score(rate.zone, wanted_zone)
        if zone_score is None:
            continue
        schedule_score = _match_score(rate.scheduled_employment, wanted_schedule)
        if schedule_score is None:
            continue

        matches.append((schedule_score, zone_score, rate.effective_from, rate))

    if not matches:
        return None
    matches.sort(key=lambda m: (m[0], m[1], m[2]), reverse=True)
    return matches[0][3]


def _match_score(rate_value: str, wanted: str) -> int | None:
    """1 for an exact match, 0 for a wildcard row, None if it does not apply."""
    value = _normalise(rate_value)
    if value in ("", ANY_ZONE, ANY_SCHEDULE):
        return 0
    if value == wanted:
        return 1
    return None


def prorated_floor(rate: MinimumWageRate, paid_days: Decimal | None, calendar_days: Decimal) -> Decimal:
    """
    The floor for the days actually paid.

    A month with unpaid leave owes proportionally less, so comparing a full
    monthly floor against a part-month's pay would manufacture a violation for
    every employee who took leave.
    """
    monthly = rate.total_per_month
    if paid_days is None or calendar_days <= 0:
        return _q(monthly)
    ratio = min(Decimal(paid_days) / Decimal(calendar_days), Decimal("1"))
    return _q(monthly * ratio)


def import_rates(
    db: Session,
    *,
    entity_id: uuid.UUID,
    user_id: uuid.UUID,
    rows: list[dict],
    replace: bool = False,
) -> dict:
    """
    Load rates in bulk.

    A row that repeats an existing (state, zone, schedule, skill, effective
    from) updates it rather than creating a duplicate, so re-importing a
    corrected sheet converges instead of doubling the table.
    """
    if replace:
        db.query(MinimumWageRate).filter(MinimumWageRate.entity_id == entity_id).delete()
        db.flush()

    existing = {
        _key(r): r
        for r in db.query(MinimumWageRate).filter(MinimumWageRate.entity_id == entity_id).all()
    }

    created = updated = 0
    for row in rows:
        payload = {
            "state": row["state"],
            "zone": row.get("zone") or ANY_ZONE,
            "scheduled_employment": row.get("scheduled_employment") or ANY_SCHEDULE,
            "skill_category": row["skill_category"],
            "basic_per_month": Decimal(str(row.get("basic_per_month", 0))),
            "vda_per_month": Decimal(str(row.get("vda_per_month", 0))),
            "working_days_basis": Decimal(str(row.get("working_days_basis", 26))),
            "effective_from": row["effective_from"],
            "effective_to": row.get("effective_to"),
            "source_reference": row.get("source_reference"),
        }
        found = existing.get(
            (
                _normalise(payload["state"]),
                _normalise(payload["zone"]),
                _normalise(payload["scheduled_employment"]),
                _normalise(payload["skill_category"]),
                payload["effective_from"],
            )
        )
        if found is not None:
            for field, value in payload.items():
                setattr(found, field, value)
            db.add(found)
            updated += 1
        else:
            db.add(MinimumWageRate(entity_id=entity_id, user_id=user_id, **payload))
            created += 1

    db.flush()
    return {"created": created, "updated": updated}


def _key(rate: MinimumWageRate) -> tuple:
    return (
        _normalise(rate.state),
        _normalise(rate.zone),
        _normalise(rate.scheduled_employment),
        _normalise(rate.skill_category),
        rate.effective_from,
    )


def coverage_report(db: Session, entity_id: uuid.UUID, required: list[tuple[str, str]]) -> dict:
    """
    Which (state, skill) combinations present in the workforce have no rate.

    Surfaced as its own report so a practice can see the gaps in its rate table
    before a validation run turns each one into a finding.
    """
    today = date.today()
    missing = []
    covered = []
    for state, skill in sorted(set(required)):
        rate = lookup_rate(db, entity_id, state=state, skill_category=skill, as_of=today)
        target = covered if rate is not None else missing
        target.append({"state": state, "skill_category": skill})
    return {
        "covered": covered,
        "missing": missing,
        "coverage_pct": round(100 * len(covered) / max(len(covered) + len(missing), 1), 1),
    }


# ---------------------------------------------------------------------------
# Compliance check
# ---------------------------------------------------------------------------
# Component flags that count towards the floor under each basis. Which reading
# is right is contested and schedule-dependent, so the entity picks one and the
# finding records which was used.
COMPARISON_BASES = {
    # The narrowest reading: only basic and dearness allowance.
    "basic_da": ("basic", "da", "dearness_allowance"),
    # The common middle reading: everything except HRA, overtime and one-offs.
    "wages_excl_hra": None,
    # The widest reading: total gross.
    "gross": None,
}

# Components excluded under the "wages_excl_hra" basis.
EXCLUDED_FROM_WAGES = (
    "hra", "house_rent_allowance", "overtime", "ot", "bonus",
    "gratuity", "leave_encashment", "reimbursement", "arrear",
)


def comparable_wage(
    components: dict[str, float | Decimal], basis: str = "wages_excl_hra"
) -> Decimal:
    """The part of an employee's pay that is measured against the floor."""
    total = Decimal("0")
    for name, amount in (components or {}).items():
        key = _normalise(name).replace(" ", "_")
        value = Decimal(str(amount or 0))

        if basis == "basic_da":
            if any(key == allowed or key.startswith(f"{allowed}_") for allowed in COMPARISON_BASES["basic_da"]):
                total += value
            continue

        if basis == "wages_excl_hra" and any(token in key for token in EXCLUDED_FROM_WAGES):
            continue

        total += value
    return total


def check_employee(
    db: Session,
    entity_id: uuid.UUID,
    *,
    employee_id: str,
    employee_name: str | None,
    components: dict,
    state: str | None,
    skill_category: str | None,
    paid_days: Decimal | None,
    calendar_days: Decimal,
    as_of: date,
    basis: str = "wages_excl_hra",
    zone: str | None = None,
    scheduled_employment: str | None = None,
) -> dict | None:
    """
    Compare one employee's pay against the applicable floor.

    Returns a finding dict, or None when the employee is compliant. A missing
    rate, or missing master data to select one, returns an INFO finding rather
    than None — the check could not be performed, which is not the same as
    passing it.
    """
    base = {
        "employee_id": employee_id,
        "employee_name": employee_name,
        "component": "minimum_wage",
        "status": "FAIL",
    }

    if not state or not skill_category:
        missing = "work state" if not state else "skill category"
        return {
            **base,
            "rule_id": "MW-003",
            "rule_name": "Minimum Wage — Cannot Verify",
            "severity": "INFO",
            "expected_value": "",
            "actual_value": "",
            "difference": "",
            "financial_impact": 0.0,
            "reason": f"No {missing} on the employee master, so no minimum wage rate applies.",
            "suggested_fix": f"Add the {missing} to the employee master and re-run.",
        }

    rate = lookup_rate(
        db, entity_id,
        state=state, skill_category=skill_category, as_of=as_of,
        zone=zone, scheduled_employment=scheduled_employment,
    )
    if rate is None:
        return {
            **base,
            "rule_id": "MW-003",
            "rule_name": "Minimum Wage — Cannot Verify",
            "severity": "INFO",
            "expected_value": "",
            "actual_value": "",
            "difference": "",
            "financial_impact": 0.0,
            "reason": (
                f"No minimum wage rate on file for {state} / {skill_category} "
                f"effective {as_of.isoformat()}."
            ),
            "suggested_fix": "Load the applicable rate under Minimum Wage settings.",
        }

    floor = prorated_floor(rate, paid_days, calendar_days)
    actual = _q(comparable_wage(components, basis))
    if actual >= floor:
        return None

    shortfall = _q(floor - actual)
    return {
        **base,
        "rule_id": "MW-001",
        "rule_name": "Below Minimum Wage",
        "severity": "CRITICAL",
        "expected_value": str(floor),
        "actual_value": str(actual),
        "difference": str(shortfall),
        "financial_impact": float(shortfall),
        "reason": (
            f"Wages of {actual} are below the {state} minimum of {floor} for a "
            f"{skill_category} worker"
            + (f" ({rate.source_reference})" if rate.source_reference else "")
            + f", measured on the '{basis}' basis."
        ),
        "suggested_fix": f"Increase wages by {shortfall} to meet the statutory floor.",
    }
