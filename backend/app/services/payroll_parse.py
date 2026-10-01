import io
import re
from typing import Any

import pandas as pd

from app.services.upload_safety import check_workbook

REQUIRED_BASE = {"employee_id"}
EMPLOYEE_ID_HEADERS = {"employee_id", "emp_id", "employee_code", "employee_number"}
IDENTIFIER_HEADERS = EMPLOYEE_ID_HEADERS | {
    "bank_account", "account_number", "saving_account_number", "uan", "pan", "pan_number",
    "ifsc", "ifsc_code", "bank_ifsc", "esi_number", "ip_number",
    "esi_no", "esic_ip_number", "esic_number", "aadhaar", "aadhar", "aadhaar_number",
}
OPTIONAL_HEADERS = {"employee name", "location", "employment type"}

# Fields understood by the validator. Component destinations are added per entity.
IMPORT_FIELDS = (
    "employee_id", "employee_name", "state", "location", "department",
    "designation", "gender", "total_days", "paid_days", "lop_days",
    "gross", "total_deductions", "net", "pf_employee", "pf_employer",
    "esic_employee", "esic_employer", "pt", "lwf_employee",
    "lwf_employer", "tds", "bank_account", "ifsc", "pan", "uan",
    "arrear_days", "arrear_from", "arrear_to", "arrear_months",
    "increment_arrear", "increment_arrear_total", "previous_months_lop_days",
    "notice_period_recovery", "loan_recovery",
    # Read by the identity, lifecycle and statutory checks. Before these were
    # admitted, an uploaded register could never supply them: the checks either
    # never ran or — worse — reported an ESI number as missing when the file
    # carried one. Every field the engine reads by name must be importable.
    "aadhaar", "esi_number", "dob", "doj", "dol", "payment_mode", "tax_regime",
    "employment_type", "disability", "international_worker", "adolescent_permit",
    "death_or_disablement", "pf_eps", "bonus", "gratuity",
)
ALIASES = {
    "emp_id": "employee_id", "employee_code": "employee_id",
    "employee_number": "employee_id", "staff_id": "employee_id",
    "name": "employee_name", "location_state": "state", "work_state": "state",
    "gross_salary": "gross", "gross_pay": "gross", "total_gross": "gross",
    "net_salary": "net", "net_pay": "net", "take_home": "net",
    "total_deduction": "total_deductions", "total_deductions_amount": "total_deductions",
    "pf_emp": "pf_employee", "pt_amount": "pt", "income_tax": "tds",
    "account_number": "bank_account", "bank_ifsc": "ifsc", "emp_name": "employee_name",
    "ifsc_code": "ifsc", "sex": "gender", "lop": "lop_days",
    "month_days": "total_days", "days_in_month": "total_days", "working_days": "total_days",
    "aadhar": "aadhaar", "aadhaar_number": "aadhaar", "aadhaar_no": "aadhaar",
    "esi_no": "esi_number", "ip_number": "esi_number", "esic_ip_number": "esi_number",
    "esic_number": "esi_number", "esic_no": "esi_number",
    "date_of_birth": "dob", "birth_date": "dob",
    "date_of_joining": "doj", "joining_date": "doj",
    "date_of_leaving": "dol", "date_of_exit": "dol", "exit_date": "dol", "leaving_date": "dol",
    "regime": "tax_regime", "eps": "pf_eps", "eps_employer": "pf_eps",
}


def normalize_col(c: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", str(c).strip().lower())).strip("_")


def parse_payroll_file(content: bytes, filename: str) -> pd.DataFrame:
    lower = filename.lower()
    if lower.endswith(".csv"):
        headers = pd.read_csv(io.BytesIO(content), nrows=0).columns
        id_types = {h: str for h in headers if normalize_col(h) in IDENTIFIER_HEADERS}
        return pd.read_csv(io.BytesIO(content), dtype=id_types)
    if lower.endswith(".xlsx"):
        check_workbook(content)
        headers = pd.read_excel(io.BytesIO(content), engine="openpyxl", nrows=0).columns
        id_types = {h: str for h in headers if normalize_col(h) in IDENTIFIER_HEADERS}
        return pd.read_excel(io.BytesIO(content), engine="openpyxl", dtype=id_types)
    raise ValueError("Unsupported file type. Use .csv or .xlsx")


def allowed_destinations(component_names: set[str]) -> set[str]:
    components = {normalize_col(name) for name in component_names}
    return set(IMPORT_FIELDS) | components | {f"{name}_arrear" for name in components}


def suggested_mapping(columns: list[str], component_names: set[str]) -> dict[str, str]:
    allowed = allowed_destinations(component_names)
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for source in columns:
        key = normalize_col(source)
        target = ALIASES.get(key, key)
        if target not in allowed and target.endswith("_arrears"):
            target = target[:-1]
        if target in allowed and target not in used:
            mapping[source] = target
            used.add(target)
    return mapping


def suggestion_basis(columns: list[str], component_names: set[str]) -> dict[str, str]:
    """
    How each suggested destination was found: ``exact`` when the header is
    the field's own name, ``alias`` when it is a known alternative spelling.
    A screen shows this as the suggestion's confidence — it is the only
    evidence the suggestion has, so it is the only one worth claiming.
    """
    basis: dict[str, str] = {}
    for source, target in suggested_mapping(columns, component_names).items():
        basis[source] = "exact" if normalize_col(source) == target else "alias"
    return basis


def required_fields(component_names: set[str], strict: bool = True) -> list[str]:
    """What an upload must map: Employee ID, and under the strict header check
    a column for every configured salary component (see ``validate_required_columns``)."""
    if not strict:
        return ["employee_id"]
    return ["employee_id", *sorted({normalize_col(c) for c in component_names})]


def check_mapping(
    columns: list[str], mapping: dict[str, str], component_names: set[str]
) -> None:
    allowed = allowed_destinations(component_names)
    if not isinstance(mapping, dict):
        raise ValueError("Column mapping must be an object.")
    unknown = set(mapping) - set(columns)
    if unknown:
        raise ValueError(f"Mapped source column is absent: {sorted(unknown)[0]}")
    targets = list(mapping.values())
    if any(not isinstance(t, str) or t not in allowed for t in targets):
        raise ValueError("Mapping contains a field that is not configured for this entity.")
    if len(targets) != len(set(targets)):
        raise ValueError("Two source columns cannot map to the same field.")
    if "employee_id" not in targets:
        raise ValueError("Map a source column to Employee ID before uploading.")


def apply_mapping(df: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    """Keep explicitly mapped columns only; never treat an unknown deduction as earnings."""
    return df.loc[:, list(mapping)].rename(columns=mapping)


def dataframe_to_employees(df: pd.DataFrame) -> tuple[list[str], list[dict[str, Any]]]:
    df = df.copy()
    df.columns = [normalize_col(c) for c in df.columns]
    if len(set(df.columns)) != len(df.columns):
        raise ValueError("Mapped columns have duplicate names after normalization.")
    records: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        rec: dict[str, Any] = {}
        for k, v in row.items():
            if pd.isna(v):
                rec[k] = None
            elif k in IDENTIFIER_HEADERS:
                # IDs are identifiers, not amounts; never turn 123 into 123.0.
                rec[k] = str(int(v)) if isinstance(v, float) and v.is_integer() else str(v).strip()
            elif isinstance(v, (int, float)):
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

    id_aliases = EMPLOYEE_ID_HEADERS
    if not col_set & id_aliases and "employee_id" not in col_set:
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
            elif r.get("employee_number") not in (None, ""):
                r["employee_id"] = r["employee_number"]
