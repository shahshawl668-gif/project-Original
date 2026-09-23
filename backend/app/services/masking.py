"""
Showing a cost report without showing who earns what.

A department head needs to know their team costs ₹42 lakh a month. They very
often must *not* know that the number is mostly one person. A payroll analytics
product that can only answer the first question by answering the second is not
usable by the people who need it most, so identity is masked by default for
anyone below analyst, and can be switched on deliberately by anyone at all
(presenting to a room, sharing a screen, exporting for a wider audience).

The pseudonym is stable and per entity: the same employee is the same token on
every screen and in every export, so a conversation about "EMP-3F9A2C" is
possible, but the token carries nothing back to the person and does not survive
across tenants. It is derived with HMAC over the application secret — not a
plain hash of the employee id, which anyone holding a staff list could reverse
in a second by hashing every id they know.
"""
from __future__ import annotations

import hashlib
import hmac
import uuid
from typing import Any

from app.config import settings

# Fields never returned to a masked caller, whatever endpoint they came from.
SENSITIVE_FIELDS = (
    "employee_name", "name", "pan", "aadhaar", "uan", "bank_account", "ifsc",
    "date_of_birth", "esic_ip_number", "pf_number", "gender",
)


def pseudonym(entity_id: uuid.UUID | str, employee_id: str) -> str:
    """A stable, per-entity token for one employee."""
    # The fallback string keeps the old product name on purpose: it is an HMAC
    # key, not a label. Changing it would change every pseudonym derived from
    # it, so the same employee would appear as two different people either side
    # of the rename.
    key = str(getattr(settings, "jwt_secret", "") or "payrollcheck").encode()
    digest = hmac.new(
        key, f"{entity_id}:{employee_id}".encode(), hashlib.sha256
    ).hexdigest()
    return f"EMP-{digest[:6].upper()}"


def mask_name(name: str | None) -> str | None:
    """
    Initials only.

    Enough to tell two rows apart when someone is reading a list aloud, not
    enough to identify anyone in a company of any size.
    """
    if not name:
        return None
    parts = [p for p in str(name).split() if p]
    if not parts:
        return None
    return " ".join(f"{p[0].upper()}." for p in parts[:3])


class Identity:
    """How one request is allowed to see people."""

    def __init__(self, entity_id: uuid.UUID, masked: bool, reason: str):
        self.entity_id = entity_id
        self.masked = masked
        self.reason = reason

    def employee(self, employee_id: str, employee_name: str | None = None) -> dict:
        if not self.masked:
            return {"employee_id": employee_id, "employee_name": employee_name, "masked": False}
        return {
            "employee_id": pseudonym(self.entity_id, employee_id),
            "employee_name": mask_name(employee_name),
            "masked": True,
        }

    def apply(self, row: dict[str, Any]) -> dict[str, Any]:
        """Mask one outgoing record in place of returning it raw."""
        if not self.masked:
            return row
        out = dict(row)
        if "employee_id" in out:
            out["employee_id"] = pseudonym(self.entity_id, str(out["employee_id"]))
        for field in SENSITIVE_FIELDS:
            if field in out:
                out[field] = mask_name(out[field]) if field in ("employee_name", "name") else None
        out["masked"] = True
        return out

    def as_dict(self) -> dict:
        return {"masked": self.masked, "reason": self.reason}
