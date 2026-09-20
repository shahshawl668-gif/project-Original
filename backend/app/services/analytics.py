"""
Payroll business intelligence.

Validation answers "is this month right?". These answer the questions an HR head
actually gets asked and usually cannot evidence:

* *why did payroll cost move?* — a bridge that decomposes the month-on-month
  change into joiners, leavers, pay changes, attendance and arrears;
* *what are we exposed to?* — under-deduction carried forward with interest and
  damages accruing by age, which is how a PF or ESIC notice is actually sized.

The bridge is built so its components sum exactly to the observed change. A
decomposition that leaves an unexplained remainder is worse than none: it
invites the reader to trust a number that has quietly lost some of the money.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models import FindingState, SalaryRegister, SalaryRegisterRow

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


def previous_month(period: date) -> date:
    return (period.replace(day=1) - timedelta(days=1)).replace(day=1)


@dataclass
class EmployeeMonth:
    """One employee's pay in one month, split the way the bridge needs it."""

    employee_id: str
    employee_name: str | None
    regular: Decimal
    arrears: Decimal
    paid_days: Decimal | None

    @property
    def total(self) -> Decimal:
        return self.regular + self.arrears


def _load_month(db: Session, entity_id: uuid.UUID, period: date) -> dict[str, EmployeeMonth]:
    register = (
        db.query(SalaryRegister)
        .filter(
            SalaryRegister.entity_id == entity_id,
            SalaryRegister.period_month == period.replace(day=1),
        )
        .first()
    )
    if register is None:
        return {}

    rows = db.query(SalaryRegisterRow).filter(SalaryRegisterRow.register_id == register.id).all()
    out: dict[str, EmployeeMonth] = {}
    for row in rows:
        regular = sum((_dec(v) for v in (row.components or {}).values()), Decimal("0"))
        arrears = sum((_dec(v) for v in (row.arrears or {}).values()), Decimal("0"))
        arrears += _dec(row.increment_arrear_total)
        out[row.employee_id] = EmployeeMonth(
            employee_id=row.employee_id,
            employee_name=row.employee_name,
            regular=regular,
            arrears=arrears,
            paid_days=_dec(row.paid_days) if row.paid_days is not None else None,
        )
    return out


@dataclass
class BridgeEffect:
    """One bar of the waterfall."""

    key: str
    label: str
    amount: Decimal = Decimal("0")
    employee_count: int = 0
    contributors: list[dict] = field(default_factory=list)

    def as_dict(self, top_n: int = 5) -> dict:
        ranked = sorted(self.contributors, key=lambda c: abs(c["amount"]), reverse=True)[:top_n]
        return {
            "key": self.key,
            "label": self.label,
            "amount": float(_q(self.amount)),
            "employee_count": self.employee_count,
            "top_contributors": [
                {**c, "amount": float(_q(c["amount"]))} for c in ranked
            ],
        }


def cost_bridge(
    db: Session, entity_id: uuid.UUID, period: date, compare_to: date | None = None
) -> dict:
    """
    Decompose the change in total payroll cost between two months.

    For someone present in both months the change is attributed in a fixed
    order, because the alternative is an arbitrary split:

    1. **arrears** — what was paid for earlier periods, taken out first so it
       cannot masquerade as a pay rise;
    2. **attendance** — the prior month's daily rate applied to the change in
       paid days, so a short month does not read as a pay cut;
    3. **pay change** — the residual, which is what actually changed about the
       person's pay.

    Joiners and leavers are attributed whole, since there is no prior or
    subsequent figure to compare them against.
    """
    period = period.replace(day=1)
    prior_period = (compare_to or previous_month(period)).replace(day=1)

    current = _load_month(db, entity_id, period)
    prior = _load_month(db, entity_id, prior_period)

    effects = {
        "joiners": BridgeEffect("joiners", "New joiners"),
        "leavers": BridgeEffect("leavers", "Leavers"),
        "pay_change": BridgeEffect("pay_change", "Pay changes"),
        "attendance": BridgeEffect("attendance", "Attendance / LOP"),
        "arrears": BridgeEffect("arrears", "Arrears & one-time"),
    }

    for employee_id, row in current.items():
        if employee_id in prior:
            continue
        effect = effects["joiners"]
        effect.amount += row.total
        effect.employee_count += 1
        effect.contributors.append(
            {"employee_id": employee_id, "employee_name": row.employee_name, "amount": row.total}
        )

    for employee_id, row in prior.items():
        if employee_id in current:
            continue
        effect = effects["leavers"]
        effect.amount -= row.total
        effect.employee_count += 1
        effect.contributors.append(
            {"employee_id": employee_id, "employee_name": row.employee_name, "amount": -row.total}
        )

    for employee_id, now in current.items():
        was = prior.get(employee_id)
        if was is None:
            continue

        arrear_delta = now.arrears - was.arrears

        # Attendance is only separable when the prior month gives a daily rate
        # to value the change at. Without it the whole regular movement is a
        # pay change, which is the honest attribution rather than a guess.
        attendance_delta = Decimal("0")
        if was.paid_days and was.paid_days > 0 and now.paid_days is not None:
            daily = was.regular / was.paid_days
            attendance_delta = daily * (now.paid_days - was.paid_days)

        pay_delta = (now.regular - was.regular) - attendance_delta

        for key, amount in (
            ("arrears", arrear_delta),
            ("attendance", attendance_delta),
            ("pay_change", pay_delta),
        ):
            if amount == 0:
                continue
            effect = effects[key]
            effect.amount += amount
            effect.employee_count += 1
            effect.contributors.append(
                {"employee_id": employee_id, "employee_name": now.employee_name, "amount": amount}
            )

    opening = sum((r.total for r in prior.values()), Decimal("0"))
    closing = sum((r.total for r in current.values()), Decimal("0"))
    explained = sum((e.amount for e in effects.values()), Decimal("0"))

    return {
        "period": period.isoformat(),
        "compare_to": prior_period.isoformat(),
        "opening_cost": float(_q(opening)),
        "closing_cost": float(_q(closing)),
        "net_change": float(_q(closing - opening)),
        "effects": [effects[k].as_dict() for k in
                    ("joiners", "leavers", "pay_change", "attendance", "arrears")],
        # Rounding only; the decomposition is exact by construction. Surfaced
        # rather than hidden so the reader can see the bridge closes.
        "unexplained": float(_q((closing - opening) - explained)),
        "headcount": {
            "opening": len(prior),
            "closing": len(current),
            "joiners": effects["joiners"].employee_count,
            "leavers": effects["leavers"].employee_count,
        },
    }


def cost_trend(db: Session, entity_id: uuid.UUID, months: int = 12) -> dict:
    """Total cost, headcount and cost per head for the most recent periods."""
    registers = (
        db.query(SalaryRegister)
        .filter(SalaryRegister.entity_id == entity_id)
        .order_by(SalaryRegister.period_month.desc())
        .limit(months)
        .all()
    )
    points = []
    for register in sorted(registers, key=lambda r: r.period_month):
        rows = _load_month(db, entity_id, register.period_month)
        total = sum((r.total for r in rows.values()), Decimal("0"))
        arrears = sum((r.arrears for r in rows.values()), Decimal("0"))
        headcount = len(rows)
        points.append(
            {
                "period": register.period_month.isoformat(),
                "total_cost": float(_q(total)),
                "regular_cost": float(_q(total - arrears)),
                "arrears": float(_q(arrears)),
                "headcount": headcount,
                "cost_per_head": float(_q(total / headcount)) if headcount else 0.0,
            }
        )
    return {"points": points}


# ---------------------------------------------------------------------------
# Statutory exposure
# ---------------------------------------------------------------------------
def _months_between(start: date, end: date) -> int:
    """Whole months from ``start`` to ``end``, floored at zero."""
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return max(months, 0)


def _damages_rate(config, months_delayed: int) -> Decimal:
    """The graded damages rate applicable to a delay of ``months_delayed``."""
    for slab in config.damages_slabs:
        if slab.up_to_months is None or months_delayed <= slab.up_to_months:
            return slab.annual_rate_pct
    return config.damages_slabs[-1].annual_rate_pct if config.damages_slabs else Decimal("0")


def _classify(rule_id: str, config) -> str | None:
    """Which statute a rule's shortfall belongs to, if any."""
    for head, prefixes in (
        ("pf", config.pf_rule_prefixes),
        ("esic", config.esic_rule_prefixes),
        ("pt", config.pt_rule_prefixes),
        ("tds", config.tds_rule_prefixes),
    ):
        if any(rule_id.startswith(prefix) for prefix in prefixes):
            return head
    return None


def statutory_exposure(
    db: Session,
    entity_id: uuid.UUID,
    config,
    as_of: date | None = None,
) -> dict:
    """
    Size the accumulated statutory shortfall, aged.

    Each still-outstanding shortfall is carried from the month it arose and
    grown by the interest and damages its age attracts. Two consequences worth
    stating plainly, because both are deliberate:

    * **waived findings are included.** A waiver is a decision not to act, not a
      reason the money stops being owed. They are reported in their own line so
      the reader can see what has been accepted;
    * **findings that later resolved are excluded**, since the underlying
      shortfall was corrected.
    """
    as_of = as_of or date.today()

    states = (
        db.query(FindingState)
        .filter(
            FindingState.entity_id == entity_id,
            FindingState.state.in_(("open", "acknowledged", "waived")),
        )
        .all()
    )

    heads: dict[str, dict] = {
        head: {
            "head": head,
            "principal": Decimal("0"),
            "interest": Decimal("0"),
            "damages": Decimal("0"),
            "finding_count": 0,
            "oldest_period": None,
        }
        for head in ("pf", "esic", "pt", "tds")
    }
    waived_principal = Decimal("0")
    ageing: dict[str, Decimal] = {"0-3m": Decimal("0"), "3-6m": Decimal("0"), "6-12m": Decimal("0"), "12m+": Decimal("0")}
    unclassified = Decimal("0")

    for state in states:
        head = _classify(state.rule_id, config)
        principal = _dec(state.last_financial_impact)
        if principal <= 0:
            continue
        if head is None:
            unclassified += principal
            continue

        # Contributions fall due the month after the wage month, which is where
        # the delay starts running from.
        due_from = state.first_seen_period
        months_delayed = _months_between(due_from, as_of)
        years = Decimal(months_delayed) / Decimal("12")

        interest = Decimal("0")
        damages = Decimal("0")
        if head == "pf":
            interest = principal * config.pf.interest_annual_pct / Decimal("100") * years
            rate = _damages_rate(config.pf, months_delayed)
            damages = principal * rate / Decimal("100") * years
            cap = principal * config.pf.damages_cap_pct_of_arrears / Decimal("100")
            damages = min(damages, cap)
        elif head == "esic":
            interest = principal * config.esic.interest_annual_pct / Decimal("100") * years

        bucket = heads[head]
        bucket["principal"] += principal
        bucket["interest"] += interest
        bucket["damages"] += damages
        bucket["finding_count"] += 1
        if bucket["oldest_period"] is None or due_from < bucket["oldest_period"]:
            bucket["oldest_period"] = due_from

        if state.state == "waived":
            waived_principal += principal

        if months_delayed < 3:
            ageing["0-3m"] += principal
        elif months_delayed < 6:
            ageing["3-6m"] += principal
        elif months_delayed < 12:
            ageing["6-12m"] += principal
        else:
            ageing["12m+"] += principal

    by_head = []
    total_principal = total_interest = total_damages = Decimal("0")
    for head in ("pf", "esic", "pt", "tds"):
        bucket = heads[head]
        total_principal += bucket["principal"]
        total_interest += bucket["interest"]
        total_damages += bucket["damages"]
        by_head.append(
            {
                "head": head,
                "principal": float(_q(bucket["principal"])),
                "interest": float(_q(bucket["interest"])),
                "damages": float(_q(bucket["damages"])),
                "total": float(_q(bucket["principal"] + bucket["interest"] + bucket["damages"])),
                "finding_count": bucket["finding_count"],
                "oldest_period": bucket["oldest_period"].isoformat() if bucket["oldest_period"] else None,
            }
        )

    return {
        "as_of": as_of.isoformat(),
        "by_head": by_head,
        "total_principal": float(_q(total_principal)),
        "total_interest": float(_q(total_interest)),
        "total_damages": float(_q(total_damages)),
        "total_exposure": float(_q(total_principal + total_interest + total_damages)),
        # Included in the totals above, and shown separately so an accepted
        # exposure is visible rather than implied.
        "waived_principal_included": float(_q(waived_principal)),
        "ageing": {k: float(_q(v)) for k, v in ageing.items()},
        "unclassified_principal": float(_q(unclassified)),
    }


# ---------------------------------------------------------------------------
# Cost analysis
# ---------------------------------------------------------------------------
def period_bucket(period: date, granularity: str) -> tuple[str, str]:
    """(sort key, label) for a period under month, quarter or year granularity."""
    if granularity == "year":
        return (f"{period.year}", str(period.year))
    if granularity == "quarter":
        # India's financial year runs April to March, so Q1 is Apr–Jun. A payroll
        # report that called January "Q1" would not reconcile with anything else
        # the finance team produces.
        fy_start = period.year if period.month >= 4 else period.year - 1
        quarter = ((period.month - 4) % 12) // 3 + 1
        return (f"{fy_start}-Q{quarter}", f"FY{str(fy_start + 1)[-2:]} Q{quarter}")
    return (period.isoformat(), period.strftime("%b %Y"))




def _register_rows(
    db: Session,
    entity_id: uuid.UUID,
    date_from: date | None,
    date_to: date | None,
) -> tuple[list, dict]:
    """Every stored register row in a period window, with its register."""
    registers = db.query(SalaryRegister).filter(SalaryRegister.entity_id == entity_id)
    if date_from:
        registers = registers.filter(SalaryRegister.period_month >= date_from.replace(day=1))
    if date_to:
        registers = registers.filter(SalaryRegister.period_month <= date_to.replace(day=1))
    registers = registers.order_by(SalaryRegister.period_month).all()
    if not registers:
        return [], {}

    by_register = {r.id: r for r in registers}
    rows = (
        db.query(SalaryRegisterRow)
        .filter(SalaryRegisterRow.register_id.in_(list(by_register)))
        .all()
    )
    return rows, by_register


class _Costing:
    """Costs rows, resolving each employee's PF basis from the right month."""

    def __init__(self, db: Session, entity_id: uuid.UUID):
        from app.services.cost_model import CostContext

        self.db = db
        self.entity_id = entity_id
        self.context = CostContext(db, entity_id)
        self._masters: dict[date, dict] = {}

    def _master_flag(self, period: date, employee_id: str) -> bool | None:
        if period not in self._masters:
            from app.services.workforce import master_as_of

            self._masters[period] = master_as_of(self.db, self.entity_id, period)
        record = self._masters[period].get(employee_id)
        return getattr(record, "pf_restricted", None) if record is not None else None

    def cost(self, row):
        return self.context.cost_row(
            row, pf_restricted=self._master_flag(row.period_month, row.employee_id)
        )


def _accumulate(into: dict[str, Decimal], measures: dict[str, Decimal]) -> None:
    for key, value in measures.items():
        into[key] = into.get(key, Decimal("0")) + value


def _as_floats(values: dict[str, Decimal]) -> dict[str, float]:
    from app.services.cost_model import with_derived

    return {k: float(_q(v)) for k, v in with_derived(values).items()}


def measure_catalogue() -> dict:
    """The taxonomy itself, so the UI never hard-codes a label or a layer."""
    from app.services.cost_model import DERIVED, MEASURES

    return {
        "measures": [
            {"key": m.key, "label": m.label, "layer": m.layer, "hint": m.hint}
            for m in MEASURES
        ],
        "derived": [
            {"key": key, "label": label, "parts": list(parts)} for key, label, parts in DERIVED
        ]
        + [{"key": "net", "label": "Net pay", "parts": ["gross", "-deductions"]}],
    }


def cost_analysis(
    db: Session,
    entity_id: uuid.UUID,
    *,
    group_by: str = "department",
    granularity: str = "month",
    measure: str = "ctc",
    date_from: date | None = None,
    date_to: date | None = None,
    filters: dict[str, list[str]] | None = None,
) -> dict:
    """
    Payroll cost sliced by one reporting dimension over time.

    Every row is costed through the full taxonomy — earnings, employer
    contributions, employee deductions — so one pass answers "what did
    engineering cost?" and "what was the employer's EPF bill?" from the same
    numbers. ``measure`` chooses which of those figures the series and the
    ranking are drawn on; the whole taxonomy comes back regardless, because a
    dashboard that has to re-query to change a dropdown is a slow dashboard.

    Dimensions are read from the snapshot stored on each register row, not
    joined from the current master, so a reorganisation cannot rewrite what an
    earlier month cost by department. See services/dimensions.py.
    """
    from app.services.cost_model import (
        ALL_MEASURE_KEYS,
        DERIVED_LABELS,
        MEASURE_BY_KEY,
        zero_measures,
    )
    from app.services.dimensions import DIMENSION_KEYS, DIMENSION_LABELS, UNASSIGNED

    if group_by not in DIMENSION_KEYS:
        raise ValueError(f"group_by must be one of: {', '.join(DIMENSION_KEYS)}")
    if granularity not in ("month", "quarter", "year"):
        raise ValueError("granularity must be month, quarter or year")
    if measure not in ALL_MEASURE_KEYS:
        raise ValueError(f"measure must be one of: {', '.join(ALL_MEASURE_KEYS)}")

    measure_label = (
        MEASURE_BY_KEY[measure].label
        if measure in MEASURE_BY_KEY
        else DERIVED_LABELS.get(measure, "Net pay")
    )

    rows, by_register = _register_rows(db, entity_id, date_from, date_to)
    if not rows:
        return {
            "group_by": group_by,
            "group_by_label": DIMENSION_LABELS[group_by],
            "granularity": granularity,
            "measure": measure,
            "measure_label": measure_label,
            "periods": [], "groups": [], "matrix": [], "period_totals": [],
            "totals": {**_as_floats(zero_measures()), "headcount": 0, "cost_per_head": 0.0},
            "sources": {"reported": 0.0, "computed": 0.0},
        }

    active = {k: set(v) for k, v in (filters or {}).items() if v}
    costing = _Costing(db, entity_id)

    cells: dict[tuple[str, str], dict[str, Decimal]] = {}
    heads: dict[tuple[str, str], set[str]] = {}
    period_measures: dict[str, dict[str, Decimal]] = {}
    period_heads: dict[str, set[str]] = {}
    period_labels: dict[str, str] = {}
    totals = zero_measures()
    all_heads: set[str] = set()
    reported_amount = Decimal("0")
    statutory_amount = Decimal("0")

    for row in rows:
        dims = row.dimensions or {}
        if any(dims.get(key, UNASSIGNED) not in wanted for key, wanted in active.items()):
            continue

        register = by_register[row.register_id]
        key, label = period_bucket(register.period_month, granularity)
        period_labels[key] = label
        group = dims.get(group_by) or UNASSIGNED

        costed = costing.cost(row)
        measures = costed.measures

        _accumulate(cells.setdefault((key, group), zero_measures()), measures)
        _accumulate(totals, measures)
        _accumulate(period_measures.setdefault(key, zero_measures()), measures)

        heads.setdefault((key, group), set()).add(row.employee_id)
        period_heads.setdefault(key, set()).add(row.employee_id)
        all_heads.add(row.employee_id)

        reported_amount += costed.reported_amount
        statutory_amount += sum(
            (measures[k] for k in MEASURE_BY_KEY if MEASURE_BY_KEY[k].layer != "earnings"),
            Decimal("0"),
        )

    periods = [{"key": k, "label": period_labels[k]} for k in sorted(period_labels)]
    total_values = _as_floats(totals)
    denominator = total_values.get(measure, 0.0)

    matrix = []
    for group in sorted({g for _, g in cells}):
        series = []
        group_measures = zero_measures()
        for period in periods:
            cell = cells.get((period["key"], group))
            values = _as_floats(cell) if cell else _as_floats(zero_measures())
            if cell:
                _accumulate(group_measures, cell)
            series.append({
                "period": period["key"],
                "value": values[measure],
                "headcount": len(heads.get((period["key"], group), set())),
                "measures": values,
            })
        group_values = _as_floats(group_measures)
        matrix.append({
            "group": group,
            "total": group_values[measure],
            "share_pct": (
                float(_q(Decimal(str(group_values[measure])) / Decimal(str(denominator)) * 100))
                if denominator else 0.0
            ),
            "measures": group_values,
            "series": series,
        })

    matrix.sort(key=lambda g: g["total"], reverse=True)

    period_totals = [
        {
            "period": period["key"],
            "label": period["label"],
            "headcount": len(period_heads.get(period["key"], set())),
            "measures": _as_floats(period_measures.get(period["key"], zero_measures())),
        }
        for period in periods
    ]

    return {
        "group_by": group_by,
        "group_by_label": DIMENSION_LABELS[group_by],
        "granularity": granularity,
        "measure": measure,
        "measure_label": measure_label,
        "periods": periods,
        "groups": [g["group"] for g in matrix],
        "matrix": matrix,
        "period_totals": period_totals,
        "totals": {
            **total_values,
            "headcount": len(all_heads),
            "cost_per_head": (
                float(_q(Decimal(str(total_values["ctc"])) / Decimal(len(all_heads))))
                if all_heads else 0.0
            ),
        },
        # How much of the statutory total was the payroll system's own figure
        # rather than this engine's. A reader deciding how far to trust a
        # contribution total should be able to see that without asking.
        "sources": {
            "reported": float(_q(reported_amount)),
            "computed": float(_q(statutory_amount - reported_amount)),
        },
    }


def cost_compare(
    db: Session,
    entity_id: uuid.UUID,
    *,
    period_a: date,
    period_b: date,
    group_by: str = "department",
    measure: str = "ctc",
    filters: dict[str, list[str]] | None = None,
) -> dict:
    """
    Two periods side by side, across the whole taxonomy and by one dimension.

    Both directions of the question the user actually asks are the same
    operation: *May against June* and *June this year against June last year*
    differ only in which two months are named. So there is one comparison, and
    the caller chooses the pair.

    Each period is costed independently and the difference reported per measure
    and per group, including groups present in only one of the two — a
    department that closed is exactly what a comparison is for, and dropping it
    would make the parts stop summing to the change.
    """
    from app.services.cost_model import MEASURES, MEASURE_BY_KEY, DERIVED_LABELS, ALL_MEASURE_KEYS, zero_measures
    from app.services.dimensions import DIMENSION_KEYS, DIMENSION_LABELS, UNASSIGNED

    if group_by not in DIMENSION_KEYS:
        raise ValueError(f"group_by must be one of: {', '.join(DIMENSION_KEYS)}")
    if measure not in ALL_MEASURE_KEYS:
        raise ValueError(f"measure must be one of: {', '.join(ALL_MEASURE_KEYS)}")

    period_a = period_a.replace(day=1)
    period_b = period_b.replace(day=1)
    active = {k: set(v) for k, v in (filters or {}).items() if v}
    costing = _Costing(db, entity_id)

    sides: dict[str, dict] = {}
    for name, period in (("a", period_a), ("b", period_b)):
        rows, by_register = _register_rows(db, entity_id, period, period)
        totals = zero_measures()
        by_group: dict[str, dict[str, Decimal]] = {}
        group_heads: dict[str, set[str]] = {}
        headcount: set[str] = set()
        for row in rows:
            dims = row.dimensions or {}
            if any(dims.get(key, UNASSIGNED) not in wanted for key, wanted in active.items()):
                continue
            group = dims.get(group_by) or UNASSIGNED
            measures = costing.cost(row).measures
            _accumulate(totals, measures)
            _accumulate(by_group.setdefault(group, zero_measures()), measures)
            group_heads.setdefault(group, set()).add(row.employee_id)
            headcount.add(row.employee_id)
        sides[name] = {
            "period": period.isoformat(),
            "label": period.strftime("%b %Y"),
            "present": bool(rows),
            "totals": totals,
            "by_group": by_group,
            "group_heads": group_heads,
            "headcount": len(headcount),
        }

    a, b = sides["a"], sides["b"]

    def delta_row(label: str, key: str, layer: str, va: Decimal, vb: Decimal) -> dict:
        change = vb - va
        return {
            "key": key,
            "label": label,
            "layer": layer,
            "a": float(_q(va)),
            "b": float(_q(vb)),
            "delta": float(_q(change)),
            # Percentage change is meaningless against a zero base — a
            # department that did not exist last month has not grown by
            # infinity. Null, and the UI says "new" rather than a number.
            "delta_pct": float(_q(change / va * 100)) if va else None,
        }

    a_values = _as_floats(a["totals"])
    b_values = _as_floats(b["totals"])

    by_measure = [
        delta_row(m.label, m.key, m.layer, a["totals"][m.key], b["totals"][m.key])
        for m in MEASURES
    ]
    by_derived = [
        delta_row(DERIVED_LABELS[key], key, "derived",
                  Decimal(str(a_values[key])), Decimal(str(b_values[key])))
        for key in ("gross", "employer_cost", "ctc", "deductions")
    ] + [
        delta_row("Net pay", "net", "derived",
                  Decimal(str(a_values["net"])), Decimal(str(b_values["net"])))
    ]

    def group_value(side: dict, group: str) -> Decimal:
        cell = side["by_group"].get(group)
        return Decimal(str(_as_floats(cell)[measure])) if cell else Decimal("0")

    groups = sorted(set(a["by_group"]) | set(b["by_group"]))
    by_group = [
        {
            **delta_row(group, group, "group", group_value(a, group), group_value(b, group)),
            "group": group,
            "headcount_a": len(a["group_heads"].get(group, set())),
            "headcount_b": len(b["group_heads"].get(group, set())),
        }
        for group in groups
    ]
    by_group.sort(key=lambda g: abs(g["delta"]), reverse=True)

    return {
        "group_by": group_by,
        "group_by_label": DIMENSION_LABELS[group_by],
        "measure": measure,
        "measure_label": (
            MEASURE_BY_KEY[measure].label
            if measure in MEASURE_BY_KEY
            else DERIVED_LABELS.get(measure, "Net pay")
        ),
        "a": {"period": a["period"], "label": a["label"], "present": a["present"],
              "headcount": a["headcount"], "measures": a_values},
        "b": {"period": b["period"], "label": b["label"], "present": b["present"],
              "headcount": b["headcount"], "measures": b_values},
        "by_measure": by_measure,
        "by_derived": by_derived,
        "by_group": by_group,
        "headcount": {
            "a": a["headcount"],
            "b": b["headcount"],
            "delta": b["headcount"] - a["headcount"],
        },
    }


def dimension_values(db: Session, entity_id: uuid.UUID) -> dict:
    """
    The values present for each dimension, so filters offer only real options.

    Read from the stored register snapshots rather than the master: these are
    the values cost was actually booked against, which is what a filter should
    be able to select.
    """
    from app.services.dimensions import DIMENSIONS, UNASSIGNED

    rows = (
        db.query(SalaryRegisterRow.dimensions)
        .filter(SalaryRegisterRow.entity_id == entity_id)
        .all()
    )
    found: dict[str, set[str]] = {key: set() for key, _ in DIMENSIONS}
    for (dims,) in rows:
        for key in found:
            found[key].add((dims or {}).get(key) or UNASSIGNED)

    return {
        "dimensions": [
            {
                "key": key,
                "label": label,
                # Unassigned sorts last: it is a gap in the data, not a unit.
                "values": sorted(found[key], key=lambda v: (v == UNASSIGNED, v.lower())),
            }
            for key, label in DIMENSIONS
        ]
    }


def available_periods(db: Session, entity_id: uuid.UUID) -> dict:
    """Which months hold a register, so a comparison can only name a real one."""
    rows = (
        db.query(SalaryRegister.period_month)
        .filter(SalaryRegister.entity_id == entity_id)
        .order_by(SalaryRegister.period_month.desc())
        .all()
    )
    return {
        "periods": [
            {"period": period.isoformat(), "label": period.strftime("%b %Y")}
            for (period,) in rows
        ]
    }
