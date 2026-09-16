"""
Approved budget, actual against it, and a forecast that never pretends to be either.

Three things live here, and the boundaries between them are the point:

* **budget** — a number Finance approved before the month happened;
* **actual** — what the registers say happened;
* **forecast** — an arithmetic projection from stated assumptions.

They are carried separately all the way to the response, each labelled, because
the single most damaging thing this module could do is let a projection be read
as a result. Every forecast figure comes back under a ``forecast`` key with the
assumptions that produced it attached, and nothing in the API returns a blended
"expected" number that would hide which is which.

A budget version stays in ``draft`` until someone with authority approves it,
and only an approved version is offered as a comparison. A draft presented as
the approved budget is how a board gets misled.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models import BudgetLine, BudgetVersion, ENTITY_SCOPE

CENT = Decimal("0.01")


def _q(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _dec(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def variance(actual: Decimal, comparison: Decimal | None) -> dict:
    """
    Actual less comparison, and the same as a percentage.

    Percentage variance against a zero comparison is undefined, not infinite and
    not zero: a department with no budget has not overspent by 100%, it has no
    budget. Null, and the reader is told which.
    """
    if comparison is None:
        return {"variance": None, "variance_pct": None, "basis": "no comparison"}
    delta = actual - comparison
    return {
        "variance": float(_q(delta)),
        "variance_pct": float(_q(delta / comparison * 100)) if comparison else None,
        "basis": "actual − comparison",
    }


# ---------------------------------------------------------------------------
# Parsing an uploaded budget
# ---------------------------------------------------------------------------
PERIOD_KEYS = ("period", "month", "payroll_month", "period_month", "budget_month")
SCOPE_KEYS = ("scope", "department", "cost_center", "cost_centre", "business_unit",
              "location", "grade", "entity", "name")
AMOUNT_KEYS = ("amount", "budget", "budget_amount", "budgeted_cost", "cost", "value")
HEADCOUNT_KEYS = ("headcount", "heads", "employees", "budget_headcount")


def _first(row: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return None


def parse_period(value: Any) -> date | None:
    """
    Read a budget month from whatever the finance team typed.

    Accepts an ISO date, a datetime from Excel, and the spellings a monthly
    budget is actually written in — "Apr 2026", "2026-04", "04/2026".
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date().replace(day=1)
    if isinstance(value, date):
        return value.replace(day=1)

    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m", "%b %Y", "%B %Y", "%b-%Y", "%B-%Y",
                "%m/%Y", "%m-%Y", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m"):
        try:
            return datetime.strptime(text, fmt).date().replace(day=1)
        except ValueError:
            continue
    return None


def parse_budget_rows(
    records: list[dict[str, Any]],
    scope_key: str,
) -> tuple[list[dict], list[str]]:
    """
    Turn parsed spreadsheet rows into budget lines, and say what could not be read.

    Problems are *collected*, not raised on the first one. A finance team fixing
    a 200-row budget file needs the whole list, not the first bad cell followed
    by another upload.
    """
    from app.services.payroll_parse import normalize_col

    lines: list[dict] = []
    problems: list[str] = []
    seen: set[tuple[date, str]] = set()

    for index, raw in enumerate(records, start=2):  # row 1 is the header
        row = {normalize_col(str(k)): v for k, v in raw.items() if k is not None}

        period = parse_period(_first(row, PERIOD_KEYS))
        if period is None:
            problems.append(f"Row {index}: no readable budget month.")
            continue

        scope_value = _first(row, (scope_key,) + SCOPE_KEYS)
        scope = str(scope_value).strip() if scope_value not in (None, "") else ENTITY_SCOPE

        amount_raw = _first(row, AMOUNT_KEYS)
        if amount_raw is None:
            problems.append(f"Row {index}: no budget amount.")
            continue
        amount = _dec(amount_raw)
        if amount < 0:
            problems.append(f"Row {index}: a negative budget ({amount}) — check the sign.")
            continue

        key = (period, scope)
        if key in seen:
            problems.append(
                f"Row {index}: {scope} already has a line for {period:%b %Y}. "
                "Two budgets for one month cannot both be the approved one."
            )
            continue
        seen.add(key)

        headcount_raw = _first(row, HEADCOUNT_KEYS)
        try:
            headcount = int(float(headcount_raw)) if headcount_raw not in (None, "") else None
        except (TypeError, ValueError):
            headcount = None

        consumed = set(PERIOD_KEYS + SCOPE_KEYS + AMOUNT_KEYS + HEADCOUNT_KEYS) | {scope_key}
        lines.append({
            "period_month": period,
            "scope_value": scope,
            "amount": amount,
            "headcount": headcount,
            "extra": {k: v for k, v in row.items() if k not in consumed and v not in (None, "")},
        })

    return lines, problems


def save_version(
    db: Session,
    entity_id: uuid.UUID,
    *,
    name: str,
    scope_key: str,
    measure: str,
    lines: list[dict],
    financial_year: str | None = None,
    note: str | None = None,
    source_filename: str | None = None,
    created_by: Any | None = None,
) -> BudgetVersion:
    """Store a budget as a new draft version. Approval is a separate act."""
    existing = (
        db.query(BudgetVersion)
        .filter(BudgetVersion.entity_id == entity_id, BudgetVersion.name == name)
        .first()
    )
    if existing is not None:
        raise ValueError(
            f"A budget named {name!r} already exists. Budgets are versioned rather "
            "than overwritten — give this one its own name."
        )

    version = BudgetVersion(
        entity_id=entity_id,
        name=name,
        financial_year=financial_year,
        scope_key=scope_key,
        measure=measure,
        note=note,
        source_filename=source_filename,
        created_by_user_id=getattr(created_by, "id", None),
        state="draft",
    )
    db.add(version)
    db.flush()

    for line in lines:
        db.add(BudgetLine(
            version_id=version.id,
            entity_id=entity_id,
            period_month=line["period_month"],
            scope_value=line["scope_value"],
            amount=line["amount"],
            headcount=line.get("headcount"),
            extra=line.get("extra") or {},
        ))
    return version


def approve(db: Session, version: BudgetVersion, user: Any) -> BudgetVersion:
    """
    Approve a budget, and make it the one the dashboards compare against.

    Approving a new version stands the previous one down rather than deleting
    it: the variance someone argued about in April is still reconstructable.
    """
    (
        db.query(BudgetVersion)
        .filter(
            BudgetVersion.entity_id == version.entity_id,
            BudgetVersion.id != version.id,
            BudgetVersion.is_current.is_(True),
        )
        .update({"is_current": False}, synchronize_session=False)
    )
    version.state = "approved"
    version.is_current = True
    version.approved_by_user_id = getattr(user, "id", None)
    version.approved_by_email = getattr(user, "email", None)
    version.approved_at = datetime.now(timezone.utc)
    return version


def current_version(db: Session, entity_id: uuid.UUID) -> BudgetVersion | None:
    return (
        db.query(BudgetVersion)
        .filter(
            BudgetVersion.entity_id == entity_id,
            BudgetVersion.state == "approved",
            BudgetVersion.is_current.is_(True),
        )
        .first()
    )


# ---------------------------------------------------------------------------
# Actual against budget
# ---------------------------------------------------------------------------
def budget_variance(
    db: Session,
    entity_id: uuid.UUID,
    *,
    version_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    filters: dict[str, list[str]] | None = None,
) -> dict:
    """
    Actual payroll cost against the approved budget, by month and by scope.

    The comparison is drawn on the measure the budget was approved on — a budget
    set on gross pay is not compared against CTC, which would show a 10%
    overspend that is really the employer's own contributions.

    A month with a budget and no register is reported as unspent rather than
    dropped; a month with a register and no budget is reported as unbudgeted.
    Silently showing only the intersection would make a total that reconciles to
    neither side.
    """
    from app.services.analytics import cost_analysis

    version = (
        db.get(BudgetVersion, version_id) if version_id else current_version(db, entity_id)
    )
    if version is None or version.entity_id != entity_id:
        return {
            "version": None,
            "periods": [],
            "scopes": [],
            "totals": {"actual": 0.0, "budget": None, "variance": None, "variance_pct": None},
            "note": "No approved budget. Upload one and approve it to see variance.",
        }

    group_by = version.scope_key if version.scope_key != ENTITY_SCOPE else "department"
    analysis = cost_analysis(
        db, entity_id,
        group_by=group_by,
        granularity="month",
        measure=version.measure,
        date_from=date_from,
        date_to=date_to,
        filters=filters,
    )

    lines = (
        db.query(BudgetLine)
        .filter(BudgetLine.version_id == version.id)
        .all()
    )
    if date_from:
        lines = [l for l in lines if l.period_month >= date_from.replace(day=1)]
    if date_to:
        lines = [l for l in lines if l.period_month <= date_to.replace(day=1)]

    entity_wide = version.scope_key == ENTITY_SCOPE
    budget_by_period: dict[str, Decimal] = {}
    budget_by_scope: dict[tuple[str, str], Decimal] = {}
    for line in lines:
        key = line.period_month.isoformat()
        budget_by_period[key] = budget_by_period.get(key, Decimal("0")) + _dec(line.amount)
        budget_by_scope[(key, line.scope_value)] = (
            budget_by_scope.get((key, line.scope_value), Decimal("0")) + _dec(line.amount)
        )

    actual_by_period = {p["period"]: Decimal(str(p["measures"][version.measure]))
                        for p in analysis["period_totals"]}
    labels = {p["period"]: p["label"] for p in analysis["period_totals"]}
    for key in budget_by_period:
        labels.setdefault(key, date.fromisoformat(key).strftime("%b %Y"))

    periods = []
    for key in sorted(set(actual_by_period) | set(budget_by_period)):
        actual = actual_by_period.get(key, Decimal("0"))
        budget = budget_by_period.get(key)
        periods.append({
            "period": key,
            "label": labels[key],
            "actual": float(_q(actual)),
            "budget": float(_q(budget)) if budget is not None else None,
            "has_actual": key in actual_by_period,
            "has_budget": key in budget_by_period,
            **variance(actual, budget),
            "utilisation_pct": float(_q(actual / budget * 100)) if budget else None,
        })

    scopes = []
    if not entity_wide:
        actual_by_scope: dict[tuple[str, str], Decimal] = {}
        for group in analysis["matrix"]:
            for point in group["series"]:
                actual_by_scope[(point["period"], group["group"])] = Decimal(str(point["value"]))

        names = sorted({scope for _, scope in set(budget_by_scope) | set(actual_by_scope)})
        for name in names:
            actual = sum(
                (v for (p, s), v in actual_by_scope.items() if s == name), Decimal("0")
            )
            budgeted = [v for (p, s), v in budget_by_scope.items() if s == name]
            budget = sum(budgeted, Decimal("0")) if budgeted else None
            scopes.append({
                "scope": name,
                "actual": float(_q(actual)),
                "budget": float(_q(budget)) if budget is not None else None,
                **variance(actual, budget),
                "utilisation_pct": float(_q(actual / budget * 100)) if budget else None,
            })
        scopes.sort(key=lambda s: abs(s["variance"] or 0), reverse=True)

    total_actual = sum((Decimal(str(p["actual"])) for p in periods), Decimal("0"))
    budgeted_totals = [Decimal(str(p["budget"])) for p in periods if p["budget"] is not None]
    total_budget = sum(budgeted_totals, Decimal("0")) if budgeted_totals else None

    return {
        "version": {
            "id": str(version.id),
            "name": version.name,
            "financial_year": version.financial_year,
            "scope_key": version.scope_key,
            "measure": version.measure,
            "approved_by": version.approved_by_email,
            "approved_at": version.approved_at.isoformat() if version.approved_at else None,
        },
        "measure": version.measure,
        "periods": periods,
        "scopes": scopes,
        "totals": {
            "actual": float(_q(total_actual)),
            "budget": float(_q(total_budget)) if total_budget is not None else None,
            **variance(total_actual, total_budget),
            "utilisation_pct": (
                float(_q(total_actual / total_budget * 100)) if total_budget else None
            ),
        },
        "unbudgeted_periods": [p["label"] for p in periods if not p["has_budget"]],
        "unspent_periods": [p["label"] for p in periods if not p["has_actual"]],
    }


# ---------------------------------------------------------------------------
# Forecast
# ---------------------------------------------------------------------------
def forecast(
    db: Session,
    entity_id: uuid.UUID,
    *,
    months: int = 6,
    increment_pct: Decimal | float = 0,
    increment_from: date | None = None,
    new_hires_per_month: int = 0,
    average_hire_cost: Decimal | float = 0,
    exits_per_month: int = 0,
    bonus_month: date | None = None,
    bonus_amount: Decimal | float = 0,
    measure: str = "ctc",
) -> dict:
    """
    Project payroll cost forward from the last actual month and stated assumptions.

    This is arithmetic on assumptions someone typed, not a prediction. Each
    month's figure carries the components that produced it, so a reader can see
    that a 9% rise is an increment and a hiring plan rather than a black box —
    and every figure is under a ``forecast`` key that nothing else in the API
    uses.

    The base is the most recent month's actual cost, less that month's arrears:
    projecting a one-off catch-up payment forward twelve times is the fastest way
    to produce a forecast nobody believes.
    """
    from app.services.analytics import cost_analysis

    analysis = cost_analysis(db, entity_id, group_by="department", measure=measure)
    points = analysis["period_totals"]
    if not points:
        return {"forecast": [], "assumptions": {}, "base": None,
                "note": "No registers yet, so there is nothing to project from."}

    last = points[-1]
    base = Decimal(str(last["measures"][measure])) - Decimal(str(last["measures"]["arrears"]))
    base_headcount = last["headcount"]
    per_head = base / Decimal(base_headcount) if base_headcount else Decimal("0")

    hire_cost = _dec(average_hire_cost) or per_head
    increment = _dec(increment_pct) / Decimal("100")
    increment_from = increment_from.replace(day=1) if increment_from else None

    period = date.fromisoformat(last["period"])
    running = base
    headcount = base_headcount
    rows = []

    # An increment lands once, in the month it takes effect, and is carried in
    # the run rate from then on. Applying it every month would compound a single
    # pay review into an exponential curve — the classic way a payroll forecast
    # ends up double the truth by March.
    first_month = date(
        (period.year * 12 + period.month) // 12,
        (period.year * 12 + period.month) % 12 + 1,
        1,
    )
    increment_month = increment_from or first_month
    increment_applied = False

    for step in range(1, months + 1):
        total = (period.year * 12 + period.month - 1) + step
        month = date(total // 12, total % 12 + 1, 1)

        applied_increment = Decimal("0")
        if increment and not increment_applied and month >= increment_month:
            applied_increment = running * increment
            running += applied_increment
            increment_applied = True

        joiner_cost = _dec(new_hires_per_month) * hire_cost
        leaver_cost = _dec(exits_per_month) * per_head
        headcount = headcount + new_hires_per_month - exits_per_month
        running += joiner_cost - leaver_cost

        bonus = (
            _dec(bonus_amount)
            if bonus_month and month == bonus_month.replace(day=1)
            else Decimal("0")
        )

        rows.append({
            "period": month.isoformat(),
            "label": month.strftime("%b %Y"),
            "forecast": float(_q(running + bonus)),
            "is_forecast": True,
            "headcount": headcount,
            "components": {
                "run_rate": float(_q(running - bonus if bonus else running)),
                "increment": float(_q(applied_increment)),
                "joiners": float(_q(joiner_cost)),
                "exits": float(_q(-leaver_cost)),
                "bonus": float(_q(bonus)),
            },
        })

    return {
        "base": {
            "period": last["period"],
            "label": last["label"],
            "actual": float(_q(base)),
            "headcount": base_headcount,
            "note": "Most recent actual month, excluding that month's arrears.",
        },
        "measure": measure,
        "forecast": rows,
        "assumptions": {
            "increment_pct": float(_dec(increment_pct)),
            "increment_from": increment_from.isoformat() if increment_from else "immediately",
            "new_hires_per_month": new_hires_per_month,
            "average_hire_cost": float(_q(hire_cost)),
            "exits_per_month": exits_per_month,
            "bonus_month": bonus_month.isoformat() if bonus_month else None,
            "bonus_amount": float(_dec(bonus_amount)),
        },
        "disclaimer": (
            "A projection from the assumptions above, not a financial result and "
            "not an approved budget."
        ),
    }
