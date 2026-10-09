from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pandas as pd

from app.services.payroll_parse import normalize_col, parse_payroll_file
from app.services.workforce_parse import parse_date, parse_decimal

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
    """
    The effective date, read day first as Indian files write it.

    pandas guesses month first, so "01/04/2026" — 1 April, the start of the
    financial year — used to become 4 January. The employee master's reader
    already reads it correctly; this uses the same one. A blank is None, never
    the "NaT" pandas produces.
    """
    parsed = parse_date(value)
    if parsed is not None:
        return parsed
    text = str(value).strip() if value is not None else ""
    try:
        # "2026-04-01 00:00:00", as a spreadsheet date often arrives in a CSV.
        return datetime.fromisoformat(text).date() if text else None
    except ValueError:
        return None


def _dec(v: Any, where: str) -> Decimal:
    """An amount. Blank is zero here (a CTC component not paid); text that is not a number is refused."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return Decimal("0")
    if isinstance(v, str) and v.strip().lower() in {"", "nan", "none", "-", "na", "n/a"}:
        return Decimal("0")
    amount = parse_decimal(v)
    if amount is None:
        raise ValueError(f"{where} “{v}” is not an amount. Nothing was stored; correct it and upload again.")
    return amount


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
    return parse_ctc_frame(parse_payroll_file(content, filename), component_keys, default_effective_from)


def parse_ctc_frame(
    df: pd.DataFrame,
    component_keys: set[str],
    default_effective_from: date | None = None,
) -> tuple[list[str], list[dict[str, Any]]]:
    """The same parse over a frame already read — a file, or records sent to the API."""
    df = df.copy()
    df.columns = [normalize_col(c) for c in df.columns]
    columns = list(df.columns)

    records: list[dict[str, Any]] = []
    undated: list[str] = []
    for position, (_, row) in enumerate(df.iterrows()):
        line = position + 2   # the header is row 1
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
            # The ternary ruff suggests here nests one conditional inside
            # another, which is harder to read than the branches.
            if pd.isna(ename):  # noqa: SIM108
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
            # Skipping it quietly would leave this employee on an older CTC
            # with nothing to say a row was dropped.
            undated.append(f"row {line} ({eid})")
            continue

        annual: dict[str, float] = {}
        for k, v in row.items():
            if k in RESERVED_KEYS or k.startswith("_"):
                continue
            if k not in component_keys:
                continue
            amt = _dec(v, f"Row {line}, {k}")
            if amt != 0:
                annual[k] = float(amt)

        annual_ctc_raw = row.get("annual_ctc") or row.get("ctc")
        annual_ctc = _dec(annual_ctc_raw, f"Row {line}, annual CTC") if annual_ctc_raw is not None else Decimal("0")
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

    if undated:
        raise ValueError(
            f"{len(undated)} row(s) have no readable effective date and no default was given: "
            + ", ".join(undated[:10]) + ("…" if len(undated) > 10 else "")
            + ". Add an effective_from column or choose a default date."
        )
    return columns, records
