"""
Whether an employee's PF is restricted to the statutory ceiling.

This is a per-employee decision, not a per-employer one. On the same payroll,
one person can be capped at the ₹15,000 ceiling while another contributes on
full basic — typically because they were a member before the ceiling applied to
them, or because the employer agreed to contribute on full wage for a grade.
Treating it as one switch for the whole entity silently mis-states PF for
everyone on the other basis, and the error compounds every month.

Three sources can settle it, in order of how specific they are:

1. the **salary register row** — the payroll system's own view for this month;
2. the **employee master** — the standing HR position;
3. the **entity's PF configuration** — the default when nobody has said.

The row wins because it describes the month actually being validated. The
resolved value carries its source, so a finding can say *why* a basis was used
rather than merely asserting one.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.payroll_parse import normalize_col

# Column spellings that carry the restriction flag on a register or master.
RESTRICTION_KEYS = (
    "pf_restricted", "pf_restriction", "pf_capped", "pf_cap",
    "restrict_pf", "pf_ceiling_applied", "pf_limit_applied", "pf_basis",
)

# Values meaning "capped at the ceiling".
_RESTRICTED = {"y", "yes", "true", "1", "restricted", "capped", "limited", "ceiling", "15000"}
# Values meaning "PF on full wage".
_UNRESTRICTED = {"n", "no", "false", "0", "unrestricted", "uncapped", "full", "actual", "full_wage"}


@dataclass(frozen=True)
class PFBasis:
    """The restriction decision for one employee, and where it came from."""

    restricted: bool
    source: str  # "register" | "master" | "entity default"

    @property
    def label(self) -> str:
        return "restricted to ceiling" if self.restricted else "unrestricted (full wage)"


def parse_flag(value: Any) -> bool | None:
    """
    Read a restriction flag, or None when it says nothing.

    None is distinct from False on purpose: "not stated" must fall through to
    the next source rather than silently meaning "unrestricted".
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if not text or text in {"nan", "none", "-", "na", "n/a"}:
        return None
    if text in _RESTRICTED:
        return True
    if text in _UNRESTRICTED:
        return False
    return None


def from_row(row: dict[str, Any]) -> bool | None:
    """The flag as stated on this month's register row, if it states one."""
    normalised = {normalize_col(str(k)): v for k, v in row.items() if k is not None}
    for key in RESTRICTION_KEYS:
        if key in normalised:
            flag = parse_flag(normalised[key])
            if flag is not None:
                return flag
    return None


def resolve(
    row: dict[str, Any],
    master_flag: bool | None,
    entity_default: bool,
) -> PFBasis:
    """Settle the basis for one employee, most specific source first."""
    row_flag = from_row(row)
    if row_flag is not None:
        return PFBasis(restricted=row_flag, source="register")
    if master_flag is not None:
        return PFBasis(restricted=master_flag, source="master")
    return PFBasis(restricted=entity_default, source="entity default")
