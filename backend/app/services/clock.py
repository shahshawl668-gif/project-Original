"""
Today's date, in India.

Statutory due dates, overdue issues and "as of today" views are Indian
calendar days. The server runs on UTC, where the system date is still
yesterday until 05:30 IST — so for five and a half hours each morning a PF
payment due "today" read as not yet due. India keeps no daylight saving, so a
fixed +05:30 offset is exact and needs no time-zone database.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30), "IST")


def india_today() -> date:
    return datetime.now(IST).date()
