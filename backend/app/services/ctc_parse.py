from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pandas as pd

from app.services.payroll_parse import normalize_col, parse_payroll_file


RESERVED_KEYS = {
    "employee_id",
    "emp_id",
    "employee_code",
    "employee_name",
    "name",
    "effective_from",
    "effective_date",
    "ctc_effective_from",
    "location",
    "department",
    "designation",
    "annual_ctc",
    "ctc",
}


def _parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    try:
        return pd.to_datetime(value).date()
    except Exception:
        return None


def _dec(v: Any) -> Decimal:
    if v is None or v == "" or (isinstance(v, float) and pd.isna(v)):
        return Decimal("0")
    try:
        return Decimal(str(v))
    except Exception:
        return Decimal("0")


def parse_ctc_file(
    content: bytes,
    filename: str,
    component_keys: set[str],
    default_effective_from: date | None = None,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Parse a CTC report. Returns (columns, records).

    Each record contains:
      - employee_id (str)
      - employee_name (str | None)
      - effective_from (ISO date string)
      - annual_components (dict[str, float])  # only configured component keys
      - annual_ctc (float)
    """
    df = parse_payroll_file(content, filename)
    df = df.copy()
    df.columns = [normalize_col(c) for c in df.columns]
    columns = list(df.columns)

    records: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        eid_raw = row.get("employee_id") or row.get("emp_id") or row.get("employee_code")
        if eid_raw is None or (isinstance(eid_raw, float) and pd.isna(eid_raw)):
            continue
        eid = str(eid_raw).strip()
        if not eid:
            continue
        if isinstance(eid_raw, float) and eid_raw == int(eid_raw):
            eid = str(int(eid_raw))

        ename = row.get("employee_name") or row.get("name")
        if isinstance(ename, float):
            if pd.isna(ename):
                ename = None
            else:
                ename = str(int(ename)) if ename == int(ename) else str(ename)
        elif ename is not None:
            ename = str(ename).strip() or None

        eff_raw = (
            row.get("effective_from")
            or row.get("effective_date")
            or row.get("ctc_effective_from")
        )
        eff = _parse_date(eff_raw) or default_effective_from
        if eff is None:
            continue

        annual: dict[str, float] = {}
        for k, v in row.items():
            if k in RESERVED_KEYS or k.startswith("_"):
                continue
            if k not in component_keys:
                continue
            amt = _dec(v)
            if amt != 0:
                annual[k] = float(amt)

        annual_ctc_raw = row.get("annual_ctc") or row.get("ctc")
        annual_ctc = _dec(annual_ctc_raw) if annual_ctc_raw is not None else Decimal("0")
        if annual_ctc == 0 and annual:
            annual_ctc = sum((Decimal(str(v)) for v in annual.values()), start=Decimal("0"))

        records.append(
            {
                "employee_id": eid,
                "employee_name": ename if isinstance(ename, str) else None,
                "effective_from": eff.isoformat(),
                "annual_components": annual,
                "annual_ctc": float(annual_ctc),
            }
        )

    return columns, records
