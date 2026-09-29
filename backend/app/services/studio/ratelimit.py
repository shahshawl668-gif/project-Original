"""
Per-key request limits for the integration API.

A sliding one-minute window per credential, held in the API process. That is
exact for the single API instance this product runs today; with several
instances each enforces the limit separately, so the effective ceiling is the
limit times the instance count. Moving the counter into the database or a
shared cache is the change to make before scaling out — said here rather than
discovered.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass

_WINDOW = 60.0
_lock = threading.Lock()
_hits: dict[str, deque[float]] = {}


@dataclass
class Decision:
    allowed: bool
    limit: int
    remaining: int
    reset_seconds: int


def check(key: str, limit: int, now: float | None = None) -> Decision:
    now = time.monotonic() if now is None else now
    with _lock:
        window = _hits.setdefault(key, deque())
        while window and window[0] <= now - _WINDOW:
            window.popleft()
        if len(window) >= limit:
            reset = int(window[0] + _WINDOW - now) + 1
            return Decision(False, limit, 0, max(reset, 1))
        window.append(now)
        reset = int(window[0] + _WINDOW - now) + 1
        return Decision(True, limit, limit - len(window), max(reset, 1))


def reset(key: str | None = None) -> None:
    """For tests."""
    with _lock:
        if key is None:
            _hits.clear()
        else:
            _hits.pop(key, None)
