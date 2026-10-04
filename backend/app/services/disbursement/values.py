"""
Reading one value at a time, the way real exports write them.

Trailing spaces, lower-case IFSC codes, amounts written as text with commas,
account numbers that a spreadsheet turned into a number: all of these are read
as what they mean. What cannot be read is reported, never guessed.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from difflib import SequenceMatcher
from typing import Any

from app.services.bank_file import parse_bank_date

IFSC_PATTERN = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
SCIENTIFIC = re.compile(r"^[+-]?\d+(\.\d+)?[eE][+-]?\d+$")
_SPACES = re.compile(r"\s+")
_NAME_CHARS = re.compile(r"[^a-z\s]")

_TRUE = {"yes", "y", "true", "1", "processed", "done", "completed", "hold", "on hold"}
_FALSE = {"no", "n", "false", "0", "pending", "not processed", "", "none"}


def text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and value == int(value):
        value = int(value)
    out = str(value).strip()
    return out or None


def account(value: Any) -> str | None:
    """An account number as written, trimmed. Never through a float: leading zeros are digits."""
    return text(value)


def ifsc(value: Any) -> str | None:
    out = text(value)
    return out.upper() if out else None


def ifsc_problem(code: str | None) -> str | None:
    if not code:
        return "IFSC is blank"
    if len(code) != 11:
        return f"IFSC must be 11 characters; this has {len(code)}"
    if not IFSC_PATTERN.match(code):
        return "IFSC must be 4 letters, then 0, then 6 letters or digits"
    return None


def account_problem(number: str | None, lo: int, hi: int) -> str | None:
    if not number:
        return "account number is blank"
    if SCIENTIFIC.match(number):
        return ("account number was stored as a number in a spreadsheet and shows in scientific "
                "notation; digits beyond the 15th are lost")
    if not number.isdigit():
        return "account number contains characters other than digits"
    if not lo <= len(number) <= hi:
        return f"account number has {len(number)} digits; between {lo} and {hi} are expected"
    return None


def same_account(file_value: str | None, master_value: str | None) -> tuple[bool, str | None]:
    """
    Whether the file pays the master's account, and a note when they differ only in form.

    A master exported through a spreadsheet often loses leading zeros while the
    payment file keeps them; that is the same account, and saying otherwise would
    hold correct payments. The reverse — the *file* lost them — is not: the bank
    would be asked to credit a different number, so it is a mismatch.
    """
    a, b = (file_value or "").strip(), (master_value or "").strip()
    if a == b:
        return True, None
    if a.isdigit() and b.isdigit() and a.lstrip("0") == b.lstrip("0"):
        if len(a) > len(b):
            return True, "the master lost leading zeros that the file keeps"
        return False, "the file lost leading zeros that the master has; the bank would credit a different number"
    return False, None


def flag(value: Any) -> bool | None:
    """Yes or no, or ``None`` when the cell said neither (reported by the caller)."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    out = str(value).strip().lower()
    if out in _TRUE:
        return True
    if out in _FALSE:
        return False
    return None


def when(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    out = text(value)
    if not out:
        return None
    if "T" in out:
        out = out.split("T", 1)[0]
    elif " " in out and out[:4].isdigit():
        out = out.split(" ", 1)[0]
    return parse_bank_date(out)


def is_verified(status: str | None, accepted: frozenset[str]) -> bool:
    return bool(status) and status.strip().lower() in accepted


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------
def name_tokens(value: str | None, salutations: frozenset[str]) -> list[str]:
    cleaned = _NAME_CHARS.sub(" ", (value or "").lower())
    return [t for t in _SPACES.split(cleaned) if t and t not in salutations]


def name_similarity(a: str | None, b: str | None, salutations: frozenset[str]) -> float:
    """
    0..1. Case, spacing, punctuation and salutations ignored; an initial matches a
    word it begins; word order does not matter; small spelling differences
    (Mohammad / Mohammed) count as a match. "Anil Kumar Sharma" against
    "A. K. Sharma" is 1.0; against "Anil Sharma" 0.8; against "Rahul Verma" 0.
    """
    left, right = name_tokens(a, salutations), name_tokens(b, salutations)
    if not left or not right:
        return 0.0
    free = list(right)
    matched = 0
    pending: list[str] = []
    for token in left:                      # whole words first, exact then close
        if token in free:
            free.remove(token)
            matched += 1
        else:
            pending.append(token)
    still: list[str] = []
    for token in pending:
        if len(token) > 1:
            close = next((w for w in free if len(w) > 1 and SequenceMatcher(None, token, w).ratio() >= 0.85), None)
            if close is not None:
                free.remove(close)
                matched += 1
                continue
        still.append(token)
    for token in still:                     # then initials, either side
        hit = next((w for w in free if (len(token) == 1 and w.startswith(token))
                    or (len(w) == 1 and token.startswith(w))), None)
        if hit is not None:
            free.remove(hit)
            matched += 1
    return 2 * matched / (len(left) + len(right))
