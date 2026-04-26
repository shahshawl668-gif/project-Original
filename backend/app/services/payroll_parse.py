import io
from typing import Any

import pandas as pd

REQUIRED_BASE = {"employee_id"}
OPTIONAL_HEADERS = {"employee name", "location", "employment type"}


def normalize_col(c: str) -> str:
    return str(c).strip().lower().replace(" ", "_")


def parse_payroll_file(content: bytes, filename: str) -> pd.DataFrame:
    lower = filename.lower()
    if lower.endswith(".csv"):
        return pd.read_csv(io.BytesIO(content))
    if lower.endswith(".xlsx"):
        return pd.read_excel(io.BytesIO(content), engine="openpyxl")
    raise ValueError("Unsupported file type. Use .csv or .xlsx")


def dataframe_to_employees(df: pd.DataFrame) -> tuple[list[str], list[dict[str, Any]]]:
    df = df.copy()
    df.columns = [normalize_col(c) for c in df.columns]
    records: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        rec: dict[str, Any] = {}
        for k, v in row.items():
            if pd.isna(v):
                rec[k] = None
            elif isinstance(v, (int, float)):
                if k == "employee_id" and isinstance(v, float) and v == int(v):
                    rec[k] = str(int(v))
                else:
                    rec[k] = float(v)
            else:
                rec[k] = str(v).strip()
        records.append(rec)
    return list(df.columns), records


def validate_required_columns(
    columns: list[str],
    component_names: set[str],
    strict: bool,
) -> tuple[list[str], list[str]]:
    """
    Required: employee_id (or employee id normalized to employee_id).
    Dynamic: all configured component names must exist as columns OR strict=False allows missing with 0.
    """
    col_set = set(columns)
    missing: list[str] = []
    warnings: list[str] = []

    id_aliases = {"employee_id", "emp_id", "employee_code"}
    if not col_set & id_aliases:
        if "employee_id" not in col_set:
            missing.append("employee_id")

    for comp in sorted(component_names):
        key = normalize_col(comp)
        if key not in col_set:
            if strict:
                missing.append(comp)
            else:
                warnings.append(f"Missing column for component '{comp}'; treated as 0.")

    return missing, warnings


def ensure_employee_id_column(records: list[dict[str, Any]], columns: list[str]) -> None:
    """Map emp_id / employee_code -> employee_id if needed."""
    for r in records:
        if r.get("employee_id") in (None, ""):
            if r.get("emp_id") not in (None, ""):
                r["employee_id"] = r["emp_id"]
            elif r.get("employee_code") not in (None, ""):
                r["employee_id"] = r["employee_code"]
