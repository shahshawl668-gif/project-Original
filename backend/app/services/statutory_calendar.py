"""
Statutory values that change on a day, not on the first of a month.

Tenant configuration — the base ``statutory_config`` and its dated versions —
starts on the first of a month. The law does not wait for one: the EPF wage
ceiling rose from ₹15,000 to ₹25,000 on **17 September 2026** (S.O. 5109(E)),
and September 2026 contributions are split, days 1–16 on the old ceiling and
17–30 on the new. A register checked on either single figure is wrong for
every employee earning above ₹15,000.

This module is the dated record of those defaults, in the same spirit as
``tax_year_defaults.py`` and ``pt_defaults.py``: data, not engine logic. It is
applied when configuration is loaded for a payroll month:

* A tenant following the law gets the ceiling in force for the month, and for
  a month in which it changed, the day-weighted segments. This is what keeps
  an April 2026 register on ₹15,000 and an October 2026 register on ₹25,000
  without anyone publishing a version. The base configuration follows the
  law when its ceiling is any statutory figure; a dated version follows it
  when its ceiling is the figure the law had on the version's first day (a
  version published in April 2026 for some other change, carrying ₹15,000, so
  still moves to ₹25,000 from 17 September). Versions can only begin on the
  first of a month, so a version from 1 September 2026 carrying ₹25,000 — the
  figure the law reached during that month — follows the law too, and its
  September is split like everyone else's.
* A tenant who chose a figure the law did not have at that point — a
  non-statutory figure, or ₹25,000 published from July 2026 — made a
  deliberate decision; it is used exactly as configured.

The ESI contribution periods are recorded here for the same reason: they are
statutory structure, not engine logic.

When a ceiling changes again: add a ``Change`` below with its source, re-run
``tools/statutory_worksheet.py``, and add the month to
``tests/test_law_scenarios.py`` before anything else.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal


@dataclass(frozen=True)
class Change:
    effective: date
    value: Decimal
    source: str
    status: str = "CONFIRMED"     # CONFIRMED | VERIFY


# EPF wage ceiling. The EPS pensionable-wage cap and the EDLI wage cap follow it.
PF_WAGE_CEILING: tuple[Change, ...] = (
    Change(date(2014, 9, 1), Decimal("15000"), "G.S.R. 609(E), 22 August 2014"),
    Change(date(2026, 9, 17), Decimal("25000"),
           "S.O. 5109(E), 17 September 2026; EPS amended by G.S.R. 847(E), 25 September 2026"),
)


# ESI contribution periods: 1 April – 30 September and 1 October – 31 March
# (the "contribution period" of the ESI (Central) Rules, 1950). Coverage is settled at the start of each and
# lasts to its end (ESI Act s.2(9) proviso).
ESIC_CONTRIBUTION_PERIOD_STARTS: tuple[int, ...] = (4, 10)


def esic_period_start(month: date) -> date:
    """The first day of the ESI contribution period containing ``month``."""
    starts = sorted(ESIC_CONTRIBUTION_PERIOD_STARTS)
    earlier = [m for m in starts if m <= month.month]
    if earlier:
        return date(month.year, earlier[-1], 1)
    return date(month.year - 1, starts[-1], 1)


def value_on(changes: tuple[Change, ...], day: date) -> Decimal:
    """The value in force on ``day`` (the earliest value for days before the first change)."""
    current = changes[0].value
    for change in changes:
        if change.effective <= day:
            current = change.value
    return current


def month_segments(changes: tuple[Change, ...], month: date) -> list[tuple[Decimal, Decimal]]:
    """``[(share of the month's days, value), …]`` for the calendar month containing ``month``.

    One segment for an ordinary month; two (or more) for a month in which the
    value changed. Shares are exact fractions of the month's calendar days and
    sum to 1.
    """
    first = month.replace(day=1)
    days = calendar.monthrange(first.year, first.month)[1]
    segments: list[tuple[Decimal, Decimal]] = []
    start = first
    end = first + timedelta(days=days)          # first day of the next month
    cuts = sorted(c.effective for c in changes if first < c.effective < end)
    for cut in [*cuts, end]:
        span = (cut - start).days
        if span > 0:
            segments.append((Decimal(span) / Decimal(days), value_on(changes, start)))
        start = cut
    merged: list[tuple[Decimal, Decimal]] = []
    for share, value in segments:
        if merged and merged[-1][1] == value:
            merged[-1] = (merged[-1][0] + share, value)
        else:
            merged.append((share, value))
    return merged


def follows_statute(changes: tuple[Change, ...], value: Decimal, since: date | None = None) -> bool:
    """Is the tenant following the law rather than overriding it?

    Without ``since`` (the base configuration): ``value`` is a figure the law
    has used. With ``since`` (a dated version's first day): ``value`` is the
    figure in force on that day.
    """
    try:
        value = Decimal(str(value))
    except Exception:
        return False
    if since is not None:
        # Either the figure on the version's first day, or — because a version
        # can only start on the 1st — the figure the law reached during that
        # first month.
        month_end = since.replace(day=calendar.monthrange(since.year, since.month)[1])
        return value in (value_on(changes, since), value_on(changes, month_end))
    return value in {c.value for c in changes}


def ceiling_segments(value, month: date) -> list[tuple[Decimal, Decimal]]:
    """Day-weighted PF wage ceilings for ``month`` given a configured ``value``.

    A statutory figure follows the law (split in a month the ceiling changed);
    any other figure is a single segment of itself.
    """
    if follows_statute(PF_WAGE_CEILING, value):
        return month_segments(PF_WAGE_CEILING, month)
    return [(Decimal("1"), Decimal(str(value)))]


def apply_pf_ceiling(wage_cfg, month: date, since: date | None = None):
    """The PF wage configuration with the ceiling the law sets for ``month``.

    Returns the configuration unchanged when the tenant has set a non-statutory
    ceiling. Otherwise ``wage_ceiling`` is the ceiling at the month's end and
    ``ceiling_segments`` carries the day-weighted split when it changed during
    the month (``None`` otherwise).
    """
    if not follows_statute(PF_WAGE_CEILING, wage_cfg.wage_ceiling, since):
        return wage_cfg
    segments = month_segments(PF_WAGE_CEILING, month)
    return wage_cfg.model_copy(update={
        "wage_ceiling": segments[-1][1],
        "ceiling_segments": segments if len(segments) > 1 else None,
    })
