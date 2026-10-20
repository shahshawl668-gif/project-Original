"""
Headcount roll-forward: last month's paid headcount + joiners − exits = this month's.

Joiners are people whose date of joining falls in this month; exits are people
on last month's register whose last working day was before this month began.
Anyone the arithmetic does not account for is a gap with a name: on last
month's register and missing now with no exit, or back on this one without
joining this month.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any


@dataclass
class RollForward:
    last_month: int
    joiners: list[str] = field(default_factory=list)
    exits: list[str] = field(default_factory=list)
    this_month: int = 0
    missing_without_exit: list[str] = field(default_factory=list)   # on last month's, not this, no exit
    left_this_month_unpaid: list[str] = field(default_factory=list)  # exit date in this month, no final pay
    unexplained_additions: list[str] = field(default_factory=list)  # on this month's, not last, not a joiner

    @property
    def expected(self) -> int:
        return self.last_month + len(self.joiners) - len(self.exits)

    @property
    def gap(self) -> int:
        return self.this_month - self.expected

    def as_dict(self) -> dict[str, Any]:
        return {
            "last_month": self.last_month, "joiners": len(self.joiners), "exits": len(self.exits),
            "expected": self.expected, "this_month": self.this_month, "gap": self.gap,
            "missing_without_exit": self.missing_without_exit,
            "left_this_month_unpaid": self.left_this_month_unpaid,
            "unexplained_additions": self.unexplained_additions,
            "joiner_ids": self.joiners, "exit_ids": self.exits,
        }


def roll_forward(period_month: date, last_ids: set[str], this_ids: set[str], master: dict[str, Any]) -> RollForward:
    start = period_month.replace(day=1)
    next_start = (start + timedelta(days=32)).replace(day=1)

    def doj(eid):
        rec = master.get(eid)
        return getattr(rec, "date_of_joining", None) if rec is not None else None

    def dox(eid):
        rec = master.get(eid)
        return getattr(rec, "date_of_exit", None) if rec is not None else None

    out = RollForward(last_month=len(last_ids), this_month=len(this_ids))
    for eid in sorted(this_ids - last_ids):
        joined = doj(eid)
        if joined and start <= joined < next_start:
            out.joiners.append(eid)
        elif last_ids:
            out.unexplained_additions.append(eid)
    for eid in sorted(last_ids - this_ids):
        left = dox(eid)
        if left and left < start:
            out.exits.append(eid)
        elif left and left < next_start:
            out.left_this_month_unpaid.append(eid)
        else:
            out.missing_without_exit.append(eid)
    return out
