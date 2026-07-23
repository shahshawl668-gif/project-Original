"""
Identity & data-quality validators (pure functions, no I/O).

Formats implemented per Indian statutory identifiers:
  * PAN     — [A-Z]{5}[0-9]{4}[A-Z]; 4th character 'P' for individuals.
  * Aadhaar — 12 digits, Verhoeff checksum, first digit 2-9.
  * UAN     — 12 digits.
  * ESI     — 10 or 17 digits (old IP number / new registration format).
  * IFSC    — [A-Z]{4}0[A-Z0-9]{6}.

Date helpers parse register cell values (str / date / datetime / pandas
Timestamp) tolerantly and return None when unparseable.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
UAN_RE = re.compile(r"^[0-9]{12}$")
ESI_RE = re.compile(r"^([0-9]{10}|[0-9]{17})$")

# ── Verhoeff checksum (for Aadhaar) ──────────────────────────────────────────

_VERHOEFF_D = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
    [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
    [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
    [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
    [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
    [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
    [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
    [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]
_VERHOEFF_P = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
    [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
    [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
    [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
    [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
    [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]


def _verhoeff_valid(number: str) -> bool:
    c = 0
    for i, ch in enumerate(reversed(number)):
        c = _VERHOEFF_D[c][_VERHOEFF_P[i % 8][int(ch)]]
    return c == 0


# ── Field validators ─────────────────────────────────────────────────────────

def clean_id(v: Any) -> str:
    """Normalise a register cell to an uppercase, space/dash-free string."""
    if v is None:
        return ""
    s = str(v).strip().upper().replace(" ", "").replace("-", "")
    # Excel often renders numeric ids as floats ("123456789012.0")
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    return s


def validate_pan(pan: Any) -> tuple[bool, str]:
    """Return (valid, reason). Individual PANs must have 'P' as 4th char."""
    s = clean_id(pan)
    if not s:
        return False, "missing"
    if not PAN_RE.match(s):
        return False, "format"
    if s[3] != "P":
        return False, "not_individual"
    return True, ""


def validate_aadhaar(aadhaar: Any) -> tuple[bool, str]:
    s = clean_id(aadhaar)
    if not s:
        return False, "missing"
    if not s.isdigit() or len(s) != 12:
        return False, "format"
    if s[0] in ("0", "1"):
        return False, "leading_digit"
    if not _verhoeff_valid(s):
        return False, "checksum"
    return True, ""


def validate_uan(uan: Any) -> tuple[bool, str]:
    s = clean_id(uan)
    if not s:
        return False, "missing"
    if not UAN_RE.match(s):
        return False, "format"
    return True, ""


def validate_esi_number(esi: Any) -> tuple[bool, str]:
    s = clean_id(esi)
    if not s:
        return False, "missing"
    if not ESI_RE.match(s):
        return False, "format"
    return True, ""


def validate_ifsc(ifsc: Any) -> tuple[bool, str]:
    s = clean_id(ifsc)
    if not s:
        return False, "missing"
    if not IFSC_RE.match(s):
        return False, "format"
    return True, ""


# ── Date helpers ─────────────────────────────────────────────────────────────

_DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%d-%b-%Y", "%d %b %Y")


def parse_cell_date(v: Any) -> date | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    # pandas Timestamp repr / ISO datetime
    if "T" in s or " " in s:
        s = s.split("T")[0].split(" ")[0]
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def age_in_years(dob: date, as_of: date) -> float:
    return (as_of - dob).days / 365.25


def completed_service_years(doj: date, dol: date) -> int:
    """Completed years for gratuity: fraction beyond 6 months rounds up."""
    if dol <= doj:
        return 0
    total_days = (dol - doj).days
    years = total_days // 365
    remainder_days = total_days - years * 365
    if remainder_days > 182:
        years += 1
    return int(years)


def row_flag(row: dict[str, Any], *keys: str) -> bool:
    """Interpret a truthy flag column ('1', 'yes', 'true', 'y')."""
    for k in keys:
        v = row.get(k)
        if v is None or v == "":
            continue
        return str(v).strip().lower() in ("1", "true", "yes", "y", "1.0")
    return False


def row_text(row: dict[str, Any], *keys: str) -> str:
    for k in keys:
        v = row.get(k)
        if v not in (None, ""):
            return str(v).strip()
    return ""
