"""
What a new password must be.

At least 8 characters, at most 128 (OWASP ASVS 5.0 6.2.1, 6.2.9), and not one
of the 10,000 most common passwords of that length (6.2.4, which asks for at
least 3,000). Nothing else: composition rules ("one capital, one symbol")
produce ``Password1!`` and are not asked for.

Checked where a password is set — sign-up, accepting an invitation, reset —
never at sign-in, so an existing password keeps working until it is changed.

Not done here: checking against breached-password corpora (6.2.12), which
would mean sending a hash prefix to an outside service; recorded as an open
item in docs/SECURITY.md.

The list lives in app/data/common_passwords.txt with its source. To refresh
it, regenerate from the same source and keep the header.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

LIST = Path(__file__).resolve().parent.parent / "data" / "common_passwords.txt"
MIN_LENGTH = 8
MAX_LENGTH = 128


@lru_cache(maxsize=1)
def _common() -> frozenset[str]:
    lines = LIST.read_text(encoding="utf-8").splitlines()
    return frozenset(line for line in lines if line and not line.startswith("#"))


def problem(password: str) -> str | None:
    """Why this password is refused, or None."""
    if len(password) < MIN_LENGTH:
        return f"Use at least {MIN_LENGTH} characters."
    if len(password) > MAX_LENGTH:
        return f"Use at most {MAX_LENGTH} characters."
    if password.lower() in _common():
        return "That password is one of the most commonly used, and is among the first an attacker tries. Choose another."
    return None


def check(password: str) -> str:
    """For a pydantic validator: the password, or ValueError with the reason."""
    reason = problem(password)
    if reason:
        raise ValueError(reason)
    return password
