"""
The gender pay gap, measured the way it has to be measured to be safe to read.

This is the most sensitive analytic in the product, and the one most easily
misread. Two numbers get called "the gender pay gap" and they answer different
questions:

* the **unadjusted gap** compares everyone's pay against everyone else's. It
  mostly measures *who holds which jobs* — a firm whose senior engineers are men
  and whose support staff are women has a large unadjusted gap without ever
  paying two people differently for the same work;
* the **like-for-like gap** compares within a grade, department or designation.
  That is the one that speaks to section 3 of the Code on Wages, 2019, which
  prohibits discrimination in wages on the ground of gender for the same work or
  work of a similar nature.

Reporting either alone misleads. The unadjusted figure on its own reads as an
accusation of unequal pay; the like-for-like figure on its own hides a
representation problem that is just as real. So both are always reported, with
the pay quartiles that show representation directly.

What this deliberately will not do
----------------------------------
* **No individual ever appears.** Unlike every other analytic here, there is no
  employee-level row at any permission level. The question is about the
  population.
* **Small groups are suppressed.** A "median female salary in Legal" computed
  over two people discloses two salaries. Any cell below the minimum group size
  is withheld and *reported as withheld*, so the reader knows something was held
  back rather than assuming it was absent.
* **No causal claim.** A gap is a measurement, not a finding of discrimination,
  and its absence is not proof of fairness. Grade is a proxy for "work of a
  similar nature" and not the legal test, which is about the job.
* **No third gender folded into a binary.** Where the master records a value
  outside male and female it is counted in its own right, and it is almost
  always suppressed for size — which is a fact about group size, not a judgement
  about the people in it.

Employees whose gender the master does not record are counted and reported as
coverage, never dropped: dropping them silently changes the denominator of every
figure below.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models import SalaryRegister, SalaryRegisterRow

CENT = Decimal("0.01")

# Below this, a group's median is a disclosure rather than a statistic. Five is
# the common floor in statistical disclosure control and in the UK's own pay gap
# guidance. A caller may raise it; nothing can lower it.
MIN_GROUP_SIZE = 5

# The order figures are reported in, and the labels used throughout.
GENDERS: tuple[tuple[str, str], ...] = (
    ("female", "Women"),
    ("male", "Men"),
    ("other", "Other / self-described"),
    ("not_recorded", "Not recorded"),
)
GENDER_LABELS = dict(GENDERS)

_MALE = {"m", "male", "man", "men", "boy", "1"}
_FEMALE = {"f", "female", "woman", "women", "girl", "2"}
# India recognises a third gender in law (Transgender Persons (Protection of
# Rights) Act, 2019). These values are kept as their own category rather than
# being coerced into the binary or discarded.
_OTHER = {
    "o", "other", "others", "t", "third", "third gender", "transgender", "trans",
    "tg", "x", "nb", "non-binary", "nonbinary", "non binary", "prefer not to say",
    "undisclosed", "self-described", "3",
}


BASIS = (
    "Annualised ordinary pay — monthly cost to company × 12, excluding arrears "
    "and variable pay. Variable pay is compared separately."
)

DIRECTION_NOTE = (
    "Every gap is (men − women) ÷ men × 100. A positive figure means women are "
    "paid less; a negative figure means they are paid more."
)

CAVEATS = [
    "The unadjusted gap compares everyone against everyone and mostly reflects "
    "which roles are held by whom. It is not a measure of unequal pay for the "
    "same work.",
    "The like-for-like comparison uses the reporting dimension selected as a "
    "proxy for similar work. Section 3 of the Code on Wages, 2019 turns on the "
    "same work or work of a similar nature, which is a question about the job "
    "rather than about the band it sits in.",
    "A gap is a measurement, not a finding of discrimination — and the absence "
    "of one is not proof that pay is fair.",
    "Groups smaller than the minimum are withheld and listed as withheld, "
    "because a median over a handful of people discloses their pay.",
    "Employees whose gender the master does not record are counted in coverage "
    "and excluded from gendered figures. Low coverage makes every figure here "
    "less reliable, not more favourable.",
]


def _q(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def normalise_gender(value: Any) -> str:
    """Map whatever the master recorded onto a reporting category."""
    if value is None:
        return "not_recorded"
    text = str(value).strip().lower()
    if not text or text in {"nan", "none", "-", "na", "n/a", "null", "unknown"}:
        return "not_recorded"
    if text in _MALE:
        return "male"
    if text in _FEMALE:
        return "female"
    if text in _OTHER:
        return "other"
    # An unrecognised spelling is not silently guessed at. It is "not recorded"
    # for the purposes of the figures and shows up in the coverage line, where
    # someone can see that the master needs cleaning.
    return "not_recorded"


def _median(values: list[Decimal]) -> Decimal:
    if not values:
        return Decimal("0")
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / Decimal("2")


def _mean(values: list[Decimal]) -> Decimal:
    if not values:
        return Decimal("0")
    return sum(values, Decimal("0")) / Decimal(len(values))


def gap_pct(men: Decimal, women: Decimal) -> float | None:
    """
    The gap as a percentage of men's pay.

    ``(men − women) ÷ men × 100``. **A positive number means women are paid
    less**, which is the convention every published gender pay gap uses and the
    one readers half-remember, so the direction is stated on every figure this
    produces rather than left to the sign.
    """
    if men <= 0:
        return None
    return float(_q((men - women) / men * Decimal("100")))


class _Cell:
    """One comparable group: its pay, its variable pay, and how many people."""

    def __init__(self) -> None:
        self.pay: list[Decimal] = []
        self.variable: list[Decimal] = []
        self.receiving_variable = 0

    def add(self, pay: Decimal, variable: Decimal) -> None:
        self.pay.append(pay)
        self.variable.append(variable)
        if variable > 0:
            self.receiving_variable += 1

    @property
    def count(self) -> int:
        return len(self.pay)


def _summary(cell: _Cell, threshold: int) -> dict:
    """A group's figures, or the reason they are withheld."""
    if cell.count < threshold:
        return {
            "count": cell.count,
            "suppressed": True,
            "median": None,
            "mean": None,
            "variable_median": None,
            "variable_receipt_pct": None,
        }
    return {
        "count": cell.count,
        "suppressed": False,
        "median": float(_q(_median(cell.pay))),
        "mean": float(_q(_mean(cell.pay))),
        "variable_median": float(_q(_median(cell.variable))),
        "variable_receipt_pct": float(
            _q(Decimal(cell.receiving_variable) / Decimal(cell.count) * Decimal("100"))
        ),
    }


def _compare(men: _Cell, women: _Cell, threshold: int) -> dict:
    """Men against women for one comparable set, or why it cannot be shown."""
    if men.count < threshold or women.count < threshold:
        return {
            "comparable": False,
            "reason": (
                f"Fewer than {threshold} employees of one gender in this group. "
                "Publishing a median over so few people would disclose individual pay."
            ),
            "median_gap_pct": None,
            "mean_gap_pct": None,
            "variable_gap_pct": None,
        }
    return {
        "comparable": True,
        "reason": None,
        "median_gap_pct": gap_pct(_median(men.pay), _median(women.pay)),
        "mean_gap_pct": gap_pct(_mean(men.pay), _mean(women.pay)),
        "variable_gap_pct": gap_pct(_median(men.variable), _median(women.variable)),
    }


def pay_equity(
    db: Session,
    entity_id: uuid.UUID,
    *,
    period: date | None = None,
    group_by: str = "grade",
    min_group_size: int = MIN_GROUP_SIZE,
    filters: dict[str, list[str]] | None = None,
) -> dict:
    """
    The gender pay gap for one month, unadjusted and like-for-like.

    One month rather than a range, for the same reason the compensation view
    takes one: averaging a person across months and then taking a median of
    those averages answers a question nobody asked. Pay is annualised CTC
    excluding arrears, so the figure is quoted in the unit every salary band and
    benchmark uses.
    """
    from app.services.analytics import _Costing
    from app.services.dimensions import DIMENSION_KEYS, DIMENSION_LABELS, UNASSIGNED
    from app.services.workforce import master_as_of

    if group_by not in DIMENSION_KEYS:
        raise ValueError(f"group_by must be one of: {', '.join(DIMENSION_KEYS)}")
    # A caller may be more careful than the default. Never less.
    threshold = max(int(min_group_size), MIN_GROUP_SIZE)

    register = db.query(SalaryRegister).filter(SalaryRegister.entity_id == entity_id)
    if period:
        register = register.filter(SalaryRegister.period_month == period.replace(day=1))
    register = register.order_by(SalaryRegister.period_month.desc()).first()

    empty = {
        "period": None,
        "period_label": None,
        "group_by": group_by,
        "group_by_label": DIMENSION_LABELS[group_by],
        "min_group_size": threshold,
        "basis": BASIS,
        "coverage": {"total": 0, "recorded": 0, "recorded_pct": 0.0, "by_gender": []},
        "headline": None,
        "quartiles": [],
        "like_for_like": [],
        "suppressed_groups": [],
        "direction": DIRECTION_NOTE,
        "caveats": CAVEATS,
    }
    if register is None:
        return empty

    rows = (
        db.query(SalaryRegisterRow)
        .filter(SalaryRegisterRow.register_id == register.id)
        .all()
    )
    master = master_as_of(db, entity_id, register.period_month)
    active = {k: set(v) for k, v in (filters or {}).items() if v}
    costing = _Costing(db, entity_id)

    by_gender: dict[str, _Cell] = {key: _Cell() for key, _ in GENDERS}
    by_group: dict[str, dict[str, _Cell]] = {}
    # (annualised pay, gender) for every employee, for the quartile split.
    population: list[tuple[Decimal, str]] = []

    for row in rows:
        dims = row.dimensions or {}
        if any(dims.get(key, UNASSIGNED) not in wanted for key, wanted in active.items()):
            continue

        measures = costing.cost(row).measures
        from app.services.cost_model import DERIVED_PARTS

        monthly = sum((measures[k] for k in DERIVED_PARTS["ctc"]), Decimal("0"))
        # The headline gap and the quartiles are drawn on *ordinary* pay —
        # everything except variable pay and arrears — and variable pay is
        # compared on its own below. That is how every published pay gap is
        # constructed, and for good reason: bonus is the element most likely to
        # differ, and folding it into the headline hides how much of the gap it
        # is. A bonus gap is routinely several times the base pay gap.
        variable = measures["variable_pay"] * Decimal("12")
        annual = (monthly - measures["arrears"] - measures["variable_pay"]) * Decimal("12")

        record = master.get(row.employee_id)
        gender = normalise_gender(getattr(record, "gender", None) if record else None)

        by_gender[gender].add(annual, variable)
        population.append((annual, gender))

        group = dims.get(group_by) or UNASSIGNED
        cells = by_group.setdefault(group, {key: _Cell() for key, _ in GENDERS})
        cells[gender].add(annual, variable)

    if not population:
        return empty

    total = len(population)
    recorded = total - by_gender["not_recorded"].count

    # ---- headline: the unadjusted gap --------------------------------------
    men, women = by_gender["male"], by_gender["female"]
    headline = {
        **_compare(men, women, threshold),
        "women": _summary(women, threshold),
        "men": _summary(men, threshold),
        "other": _summary(by_gender["other"], threshold),
    }

    # ---- pay quartiles ------------------------------------------------------
    # Everyone sorted by pay and split into four equal bands, which is the
    # measure that shows representation directly: an organisation can have no
    # like-for-like gap at all and still have every woman in the lowest band.
    quartiles = []
    ordered = sorted(population, key=lambda pair: pair[0])
    size, remainder = divmod(total, 4)
    start = 0
    for index, name in enumerate(("Lower", "Lower middle", "Upper middle", "Upper")):
        length = size + (1 if index < remainder else 0)
        band = ordered[start:start + length]
        start += length
        counts = {key: 0 for key, _ in GENDERS}
        for _, gender in band:
            counts[gender] += 1
        known = len(band) - counts["not_recorded"]
        quartiles.append({
            "band": name,
            "count": len(band),
            "counts": counts,
            # Shares are of employees whose gender is recorded, and the payload
            # says so — a share of the whole band would silently treat a gap in
            # the master as a third gender.
            "female_pct": float(_q(Decimal(counts["female"]) / Decimal(known) * 100)) if known else None,
            "male_pct": float(_q(Decimal(counts["male"]) / Decimal(known) * 100)) if known else None,
            "known": known,
            "pay_from": float(_q(band[0][0])) if band else None,
            "pay_to": float(_q(band[-1][0])) if band else None,
        })

    # ---- like for like ------------------------------------------------------
    like_for_like = []
    suppressed = []
    for group in sorted(by_group):
        cells = by_group[group]
        comparison = _compare(cells["male"], cells["female"], threshold)
        entry = {
            "group": group,
            "total": sum(cell.count for cell in cells.values()),
            "women": _summary(cells["female"], threshold),
            "men": _summary(cells["male"], threshold),
            **comparison,
        }
        like_for_like.append(entry)
        if not comparison["comparable"]:
            suppressed.append({
                "group": group,
                "women": cells["female"].count,
                "men": cells["male"].count,
                "reason": comparison["reason"],
            })

    # Comparable groups first, widest gap at the top — the rows someone can act
    # on, before the rows they cannot.
    like_for_like.sort(
        key=lambda g: (not g["comparable"], -abs(g["median_gap_pct"] or 0))
    )

    return {
        "period": register.period_month.isoformat(),
        "period_label": register.period_month.strftime("%b %Y"),
        "group_by": group_by,
        "group_by_label": DIMENSION_LABELS[group_by],
        "min_group_size": threshold,
        "basis": BASIS,
        "coverage": {
            "total": total,
            "recorded": recorded,
            "recorded_pct": float(_q(Decimal(recorded) / Decimal(total) * 100)) if total else 0.0,
            "by_gender": [
                {"key": key, "label": label, "count": by_gender[key].count}
                for key, label in GENDERS
            ],
        },
        "headline": headline,
        "quartiles": quartiles,
        "like_for_like": like_for_like,
        "suppressed_groups": suppressed,
        "direction": DIRECTION_NOTE,
        "caveats": CAVEATS,
    }


