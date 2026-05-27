"""Lightweight helpers shared across Phase 2 validators."""
from __future__ import annotations

import calendar

import pandas as pd


def get_month_days(year: int, month: int) -> int:
    """Number of days in the given calendar month."""
    return calendar.monthrange(year, month)[1]


_ISO_DATE = r"^\d{4}-\d{2}-\d{2}(?:[T ].*)?$"


def parse_date_column(series: pd.Series) -> pd.Series:
    """Coerce a column to pandas datetimes; unparseable values become NaT.

    Strategy:
      * already-datetime → return as-is
      * ISO-shaped strings (`YYYY-MM-DD…`) → parse with `dayfirst=False`
      * everything else → try `dayfirst=True` first (Indian payroll convention),
        then fall back to `dayfirst=False` for the remaining unparsed rows.
    """
    if pd.api.types.is_datetime64_any_dtype(series):
        return series

    s = series.astype(object)
    iso_mask = s.astype(str).str.match(_ISO_DATE, na=False)

    parsed = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
    if iso_mask.any():
        parsed.loc[iso_mask] = pd.to_datetime(
            series[iso_mask], errors="coerce", dayfirst=False
        )
    remainder = ~iso_mask
    if remainder.any():
        parsed.loc[remainder] = pd.to_datetime(
            series[remainder], errors="coerce", dayfirst=True
        )
        still_missing = remainder & parsed.isna() & series.notna()
        if still_missing.any():
            parsed.loc[still_missing] = pd.to_datetime(
                series[still_missing], errors="coerce", dayfirst=False
            )
    return parsed
