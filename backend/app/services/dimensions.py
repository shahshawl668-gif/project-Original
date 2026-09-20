"""
The reporting attributes payroll cost is analysed by.

Cost questions are always "by something": by location, by business unit, by
department, by grade. Those attributes live on the employee master, and the
obvious implementation joins them at read time.

That would be wrong. A reorganisation in November would silently rewrite what
April cost by department, and the year-on-year comparison someone presents to a
board would change between one viewing and the next. So the attributes are
**copied onto the register row when the register is stored** — cost history stays
answerable as it was reported at the time, which is the only version anyone can
defend.

A dimension the master does not carry is recorded as unassigned rather than
dropped, so the total of any breakdown always equals the total payroll cost.
"""
from __future__ import annotations

from typing import Any

UNASSIGNED = "Unassigned"

# Ordered as they are usually read: widest organisational unit first, then where
# the person sits, then what they do.
DIMENSIONS: tuple[tuple[str, str], ...] = (
    ("business_unit", "Business unit"),
    ("department", "Department"),
    ("cost_center", "Cost centre"),
    ("work_location", "Location"),
    ("work_state", "State"),
    ("grade", "Grade"),
    ("designation", "Designation"),
    ("employment_type", "Employment type"),
    ("skill_category", "Skill category"),
)

DIMENSION_KEYS = tuple(key for key, _ in DIMENSIONS)
DIMENSION_LABELS = dict(DIMENSIONS)

# Register columns that can supply a dimension when the master is silent. A
# client who has not uploaded a master can still get a cost breakdown from
# whatever their register carries.
ROW_FALLBACKS: dict[str, tuple[str, ...]] = {
    "business_unit": ("business_unit", "bu", "division", "vertical", "lob", "segment"),
    "department": ("department", "dept", "function"),
    "cost_center": ("cost_center", "cost_centre", "cc", "cost_code"),
    "work_location": ("location", "work_location", "branch", "office", "site"),
    "work_state": ("state", "work_state", "location_state"),
    "grade": ("grade", "band", "level"),
    "designation": ("designation", "title", "job_title", "role"),
    "employment_type": ("employment_type", "emp_type", "employee_type", "category"),
    "skill_category": ("skill_category", "skill", "skill_level"),
}


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "-", "na", "n/a"}:
        return None
    return text


def snapshot(master_record: Any, row: dict[str, Any] | None = None) -> dict[str, str]:
    """
    The dimension values for one employee, as at the period being stored.

    The master is authoritative; a normalised register column fills a gap where
    the master is silent. Every dimension is always present, as ``Unassigned``
    when nothing supplies it — a breakdown whose parts do not sum to the whole is
    worse than one with an explicit unknown bucket.
    """
    from app.services.payroll_parse import normalize_col

    row_norm = (
        {normalize_col(str(k)): v for k, v in row.items() if k is not None}
        if row else {}
    )

    out: dict[str, str] = {}
    for key in DIMENSION_KEYS:
        value = _clean(getattr(master_record, key, None)) if master_record is not None else None
        if value is None:
            for alias in ROW_FALLBACKS.get(key, ()):
                value = _clean(row_norm.get(alias))
                if value is not None:
                    break
        out[key] = value or UNASSIGNED
    return out
