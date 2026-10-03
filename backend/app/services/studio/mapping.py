"""
Data mapping: from another system's records to the product's fields.

A mapping version is a specification — data, never code — that says, for each
product field, where its value comes from and how it is read:

    {"target": "employee_id", "source": "EmpNo", "type": "id", "required": true, "pad_to": 6}
    {"target": "date_of_joining", "source": "job.hireDate", "type": "date", "formats": ["%d/%m/%Y"]}
    {"target": "work_state", "source": "Location", "lookup": {"BLR": "Karnataka"}, "on_unmatched": "reject"}
    {"target": "employment_type", "cases": [{"when": {"source": "Type", "op": "eq", "value": "C"},
                                             "value": "Contract"}], "else": "Permanent"}
    {"target": "basic", "formula": "BasicMonthly * 12", "type": "number"}
    {"target": "extra.cost_code", "source": "CostCode"}
    {"target": "attendance", "source": "days", "type": "attendance_codes",
     "codes": {"P": "present", "A": "lop", "L": "paid_leave", "WO": "weekly_off", "H": "holiday"}}

**It transforms; it never judges.** There is no rule here that raises a
finding, no statutory rate, no payroll calculation. Whether a basic salary is
right is the validation engine's question; this module only reads the number
the other system sent.

**Absent is not zero.** An empty or missing source value produces no field at
all. A ``default`` applies only where someone wrote one, and the default is
stated in the specification for anyone to read. "0" is zero.

**Nothing is silently discarded.** A value that cannot be read, a lookup with
no match (unless the mapping says to keep or blank it), or a missing required
field is an error on that record, naming the target field and the source
field, and the record is rejected with its source row.

Formulas run through the same whitelisted evaluator as validation rules and
KPIs: arithmetic and a few pure functions over the record's own numbers.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.services.formula_eval import ALLOWED_FUNCS, FormulaError, evaluate_formula
from app.services.workforce_parse import (
    ATTENDANCE_ALIASES,
    EMPLOYEE_MASTER_ALIASES,
    parse_date,
)

TYPES = ("text", "id", "number", "currency", "date", "boolean", "attendance_codes")
OPS = ("eq", "ne", "in", "not_in", "present", "absent", "gt", "gte", "lt", "lte")
ATTENDANCE_CATEGORIES = ("present", "lop", "paid_leave", "weekly_off", "holiday", "half_lop")
MAX_FIELDS = 200

_TRUE = {"y", "yes", "true", "1", "t"}
_FALSE = {"n", "no", "false", "0", "f"}
_CURRENCY = re.compile(r"(₹|rs\.?|inr)", re.I)


def targets_for(object_type: str, components: list[str] | None = None) -> list[dict[str, str]]:
    """The product fields a mapping for this object type can fill."""
    components = sorted(components or [])
    from app.services.disbursement.fields import TARGETS as DISBURSEMENT_TARGETS
    from app.services.disbursement.fields import targets as disbursement_targets

    if object_type in DISBURSEMENT_TARGETS:
        return disbursement_targets(object_type)
    if object_type == "employee_master":
        fields = list(EMPLOYEE_MASTER_ALIASES)
    elif object_type == "attendance":
        fields = list(ATTENDANCE_ALIASES)
    elif object_type == "ctc":
        fields = ["employee_id", "employee_name", "effective_from", "annual_ctc", *components]
    elif object_type == "salary_register":
        from app.services.payroll_parse import IMPORT_FIELDS

        fields = list(IMPORT_FIELDS) + [c for c in components if c not in IMPORT_FIELDS]
    else:
        raise ValueError(f"Unknown object type {object_type}")
    kinds = {"date_of_joining": "date", "date_of_exit": "date", "date_of_birth": "date", "effective_from": "date",
             "dob": "date", "doj": "date", "dol": "date"}
    return [{"target": f, "type": kinds.get(f, "id" if f == "employee_id" else "text")} for f in fields]


class SpecError(ValueError):
    """A mapping specification that cannot be used, with the field it concerns."""


def _names(expression: str) -> set[str]:
    try:
        tree = ast.parse(expression or "", mode="eval")
    except SyntaxError as exc:
        raise SpecError(f"Formula is not valid: {exc.msg}") from exc
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id not in ALLOWED_FUNCS}


def check_spec(spec: dict[str, Any], object_type: str, components: list[str] | None = None) -> dict[str, Any]:
    """Validate a specification before it is saved. Returns it normalised."""
    if not isinstance(spec, dict):
        raise SpecError("A mapping is an object with a 'fields' list.")
    fields = spec.get("fields")
    if not isinstance(fields, list) or not fields:
        raise SpecError("Map at least one field.")
    if len(fields) > MAX_FIELDS:
        raise SpecError(f"A mapping may have at most {MAX_FIELDS} fields.")
    allowed = {t["target"] for t in targets_for(object_type, components)}
    seen: set[str] = set()
    out = []
    for i, f in enumerate(fields, start=1):
        if not isinstance(f, dict):
            raise SpecError(f"Field {i} is not an object.")
        target = str(f.get("target") or "").strip()
        kind = f.get("type", "text")
        if kind not in TYPES:
            raise SpecError(f"{target or f'Field {i}'}: type must be one of {', '.join(TYPES)}.")
        if kind == "attendance_codes":
            if object_type != "attendance":
                raise SpecError("Attendance codes can only be mapped in an attendance mapping.")
            codes = f.get("codes") or {}
            if not isinstance(codes, dict) or not codes:
                raise SpecError("Attendance codes need a table of code → category.")
            bad = sorted({v for v in codes.values() if v not in ATTENDANCE_CATEGORIES})
            if bad:
                raise SpecError(f"Unknown attendance categories: {', '.join(bad)}.")
            target = target or "attendance"
        elif not target.startswith("extra.") and target not in allowed:
            raise SpecError(f"'{target}' is not a field a {object_type.replace('_', ' ')} mapping can fill.")
        if target in seen:
            raise SpecError(f"'{target}' is mapped twice.")
        seen.add(target)
        sources = [bool(f.get("source")), bool(f.get("formula")), bool(f.get("cases"))]
        if sum(sources) != 1 and f.get("default") is None:
            raise SpecError(f"{target}: give exactly one of source, formula or cases (or only a default).")
        if f.get("formula"):
            names = _names(str(f["formula"]))
            try:
                evaluate_formula(str(f["formula"]), dict.fromkeys(names, 1.0))
            except FormulaError as exc:
                raise SpecError(f"{target}: {exc}") from exc
        if f.get("lookup") is not None and not isinstance(f["lookup"], dict):
            raise SpecError(f"{target}: a lookup is a table of source value → product value.")
        if f.get("on_unmatched", "reject") not in ("reject", "keep", "blank"):
            raise SpecError(f"{target}: on_unmatched is reject, keep or blank.")
        for case in f.get("cases") or []:
            cond = case.get("when") or {}
            if cond.get("op", "eq") not in OPS or not cond.get("source"):
                raise SpecError(f"{target}: each case needs when.source and an operator ({', '.join(OPS)}).")
        if f.get("pad_to") is not None and not (isinstance(f["pad_to"], int) and 1 <= f["pad_to"] <= 20):
            raise SpecError(f"{target}: pad_to is a width from 1 to 20.")
        out.append({**f, "target": target, "type": kind})
    if not any(f["target"] == "employee_id" for f in out):
        raise SpecError("Map employee_id: every record needs one.")
    return {**spec, "fields": out}


# ---------------------------------------------------------------------------
# Reading values
# ---------------------------------------------------------------------------
def dig(record: Any, path: str) -> Any:
    """``a.b.c`` into nested objects; a key containing dots is tried whole first."""
    if isinstance(record, dict) and path in record:
        return record[path]
    value = record
    for part in path.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            return None
    return value


def blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and value != value:
        return True
    return isinstance(value, str) and value.strip().lower() in {"", "-", "na", "n/a", "null", "none", "nan"}


def read_number(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("a yes/no value is not a number")
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))
    text = _CURRENCY.sub("", str(value)).replace(",", "").replace(" ", "").strip()
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"“{value}” is not a number") from exc
    return -number if negative else number


def read_date(value: Any, formats: list[str] | None) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in formats or []:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    if formats:
        raise ValueError(f"“{value}” does not match {', '.join(formats)}")
    parsed = parse_date(text)
    if parsed is None:
        raise ValueError(f"“{value}” is not a date this mapping can read")
    return parsed


def read_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    raise ValueError(f"“{value}” is not yes or no")


def read_id(value: Any, pad_to: int | None) -> str:
    if isinstance(value, float) and value == int(value):
        value = int(value)
    text = str(value).strip()
    if pad_to and text.isdigit():
        text = text.zfill(pad_to)
    return text


def _compare(actual: Any, op: str, expected: Any) -> bool:
    if op == "present":
        return not blank(actual)
    if op == "absent":
        return blank(actual)
    if blank(actual):
        return False
    if op in ("in", "not_in"):
        values = expected if isinstance(expected, list) else [expected]
        hit = str(actual).strip() in {str(v).strip() for v in values}
        return hit if op == "in" else not hit
    if op in ("gt", "gte", "lt", "lte"):
        try:
            a, b = read_number(actual), read_number(expected)
        except ValueError:
            return False
        return {"gt": a > b, "gte": a >= b, "lt": a < b, "lte": a <= b}[op]
    same = str(actual).strip() == str(expected).strip()
    return same if op == "eq" else not same


def _identifier(name: str) -> str:
    return re.sub(r"\W", "_", name.strip()).strip("_")


def _formula_vars(record: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    flat: dict[str, Any] = {}

    def walk(prefix: str, value: Any) -> None:
        if isinstance(value, dict):
            for k, v in value.items():
                walk(f"{prefix}_{k}" if prefix else str(k), v)
        else:
            flat[prefix] = value

    walk("", record)
    for key, value in flat.items():
        if blank(value):
            continue
        try:
            out[_identifier(key)] = float(read_number(value))
        except ValueError:
            continue
    return out


def _attendance(value: Any, codes: dict[str, str]) -> dict[str, Decimal]:
    if isinstance(value, str):
        items = [x for x in re.split(r"[\s,|;]+", value.strip()) if x]
    elif isinstance(value, list):
        items = [str(x).strip() for x in value]
    else:
        raise ValueError("attendance codes must be a list or a delimited string")
    lookup = {k.strip().upper(): v for k, v in codes.items()}
    tally = {c: Decimal(0) for c in ("present", "lop", "paid_leave", "weekly_off", "holiday")}
    unknown = sorted({x for x in items if x.upper() not in lookup})
    if unknown:
        raise ValueError(f"unknown attendance code(s): {', '.join(unknown[:5])}")
    for x in items:
        category = lookup[x.upper()]
        if category == "half_lop":
            tally["lop"] += Decimal("0.5")
            tally["present"] += Decimal("0.5")
        else:
            tally[category] += 1
    days = Decimal(len(items))
    return {
        "calendar_days": days, "present_days": tally["present"], "lop_days": tally["lop"],
        "paid_leave_days": tally["paid_leave"], "weekly_off_days": tally["weekly_off"],
        "holiday_days": tally["holiday"], "paid_days": days - tally["lop"],
    }


# ---------------------------------------------------------------------------
# Applying a mapping
# ---------------------------------------------------------------------------
@dataclass
class Mapped:
    row: int
    output: dict[str, Any] | None
    errors: list[dict[str, str]] = field(default_factory=list)
    source_record_id: str | None = None
    raw: Any = None
    defaults_used: list[str] = field(default_factory=list)


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value) if value != value.to_integral() else int(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def apply_one(spec: dict[str, Any], record: Any, row: int) -> Mapped:
    if not isinstance(record, dict):
        return Mapped(row, None, [{"code": "invalid_record", "field": "", "message": "A record must be an object."}],
                      raw=record)
    out: dict[str, Any] = {}
    extra: dict[str, Any] = {}
    errors: list[dict[str, str]] = []
    defaults: list[str] = []
    variables: dict[str, Any] | None = None
    for f in spec["fields"]:
        target, kind = f["target"], f.get("type", "text")
        src = f.get("source")
        where = src or target
        try:
            if f.get("formula"):
                if variables is None:
                    variables = _formula_vars(record)
                names = _names(f["formula"])
                missing = sorted(n for n in names if n not in variables)
                value = None if missing else evaluate_formula(f["formula"], variables)
                if missing and f.get("required"):
                    raise ValueError(f"the formula needs {', '.join(missing)}, which this record does not have")
            elif f.get("cases"):
                value = None
                for case in f["cases"]:
                    cond = case["when"]
                    if _compare(dig(record, cond["source"]), cond.get("op", "eq"), cond.get("value")):
                        value = case.get("value")
                        break
                else:
                    value = f.get("else")
            elif src:
                value = dig(record, src)
                if value is None:
                    for alias in f.get("aliases") or []:
                        value = dig(record, alias)
                        if value is not None:
                            where = alias
                            break
            else:
                value = None
            if blank(value) and f.get("default") is not None:
                value = f["default"]
                defaults.append(target)
            if blank(value):
                if f.get("required"):
                    errors.append({"code": "missing_required", "field": target,
                                   "message": f"{target} is required and {where} is empty or missing."})
                continue
            if f.get("lookup") is not None:
                table = {str(k).strip(): v for k, v in f["lookup"].items()}
                key = str(value).strip()
                if key in table:
                    value = table[key]
                else:
                    policy = f.get("on_unmatched", "reject")
                    if policy == "reject":
                        raise ValueError(f"“{value}” has no entry in the lookup table")
                    if policy == "blank":
                        continue
            if kind == "attendance_codes":
                for k, v in _attendance(value, f.get("codes") or {}).items():
                    out[k] = _plain(v)
                continue
            if kind == "id":
                value = read_id(value, f.get("pad_to"))
            elif kind in ("number", "currency"):
                value = _plain(read_number(value))
            elif kind == "date":
                value = read_date(value, f.get("formats")).isoformat()
            elif kind == "boolean":
                value = read_bool(value)
            else:
                value = str(value).strip() if not isinstance(value, (int, float)) else value
        except ValueError as exc:
            errors.append({"code": "invalid_value", "field": target, "message": f"{target} (from {where}): {exc}."})
            continue
        if target.startswith("extra."):
            extra[target[6:]] = value
        else:
            out[target] = value
    if spec.get("keep_unmapped"):
        used = {f.get("source") for f in spec["fields"] if f.get("source")}
        for k, v in record.items():
            if k not in used and not isinstance(v, (dict, list)) and not blank(v):
                extra.setdefault(k, v)
    record_id_field = spec.get("record_id")
    source_id = dig(record, record_id_field) if record_id_field else record.get("_source_record_id")
    if extra:
        # Kept apart, never merged into the record: "cost_code" is also an
        # alias of the product's cost_center, and a client-specific field
        # must not quietly become a product field.
        out["_extra"] = extra
    if source_id is not None:
        out["_source_record_id"] = str(source_id)
    return Mapped(row, None if errors else out, errors, str(source_id) if source_id is not None else None,
                  raw=record, defaults_used=defaults)


def apply(spec: dict[str, Any], records: list[Any], start_row: int = 1) -> list[Mapped]:
    return [apply_one(spec, r, i) for i, r in enumerate(records, start=start_row)]


def compare(a: dict[str, Any], b: dict[str, Any]) -> list[dict[str, Any]]:
    """Field-by-field differences between two specifications."""
    left = {f["target"]: f for f in a.get("fields", [])}
    right = {f["target"]: f for f in b.get("fields", [])}
    out = []
    for target in sorted(set(left) | set(right)):
        if target not in left:
            out.append({"target": target, "change": "added", "after": right[target]})
        elif target not in right:
            out.append({"target": target, "change": "removed", "before": left[target]})
        elif left[target] != right[target]:
            out.append({"target": target, "change": "changed", "before": left[target], "after": right[target]})
    for key in ("keep_unmapped", "record_id"):
        if a.get(key) != b.get(key):
            out.append({"target": f"({key})", "change": "changed", "before": a.get(key), "after": b.get(key)})
    return out
