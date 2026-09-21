"""
Reading a bank file, whatever shape this company's bank sends it in.

There is no standard. A bulk-payment file is whatever the corporate internet
banking channel was provisioned to emit, and across five banks you will see
five column orders, two date formats, amounts in rupees and amounts in paise,
files with a header and files without, and files that end with a control-total
line that is not a payment and must not be counted as one.

So the layout is configuration, not code. A :class:`~app.models.BankFileProfile`
says where each field lives and how to read its value; this module applies one
to a file. Adding a bank is filling in a form, not shipping a release.

What this module will not do
----------------------------
It will not guess. Where a profile does not say which column holds the amount,
the answer is an error naming the problem, not a column picked by looking for
the one with the most numbers in it. A bank reconciliation that silently read
the wrong column would agree with itself perfectly and mean nothing.

``suggest_mapping`` does inspect headers and propose a mapping, but it is a
*proposal* shown to an operator who confirms it — never applied on its own.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

CENT = Decimal("0.01")
PAISE = Decimal("100")


def _q(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# The fields a profile can map
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class BankField:
    key: str
    label: str
    required: bool
    hint: str


BANK_FIELDS: tuple[BankField, ...] = (
    BankField("employee_id", "Employee code", True,
              "The join key back to the salary register. Without it a file can only "
              "be reconciled in total, never line by line."),
    BankField("amount", "Amount", True,
              "What was paid to this account."),
    BankField("employee_name", "Beneficiary name", False,
              "Checked against the register's name, never used to match — two "
              "people are routinely called the same thing."),
    BankField("account_number", "Account number", False,
              "Compared with the employee master. An account that is not the one "
              "on file is the single most useful thing this module finds."),
    BankField("ifsc", "IFSC", False, "Branch code of the beneficiary account."),
    BankField("reference", "Reference / UTR", False,
              "The bank's own transaction reference, carried through to the exception "
              "report so a query to the bank can quote it."),
    BankField("status", "Status", False,
              "Where the bank returns one: processed, rejected, returned."),
    BankField("value_date", "Value date", False, "The date the payment was credited."),
    BankField("txn_type", "Transaction type", False,
              "Used only by the row filter, for statements that carry more than salary."),
)

BANK_FIELD_KEYS = tuple(f.key for f in BANK_FIELDS)
REQUIRED_FIELDS = tuple(f.key for f in BANK_FIELDS if f.required)

FILE_KINDS: tuple[tuple[str, str, str], ...] = (
    ("payment_advice", "Payment advice (sent to the bank)",
     "What payroll instructed. Reconciles against net pay in the register."),
    ("bank_statement", "Bank statement (received from the bank)",
     "What the account actually shows. Reconciles against the advice as well as the register."),
    ("return_file", "Return / reject file",
     "Payments the bank could not make. Every line here is an employee who was not paid."),
)

LAYOUTS: tuple[tuple[str, str, str], ...] = (
    ("delimited", "Delimited text (CSV, pipe, tab)", "Columns separated by a character."),
    ("excel", "Excel workbook", "Read with the first sheet's header row."),
    ("fixed", "Fixed width", "Columns at fixed character positions; map each as start and length."),
)

AMOUNT_UNITS: tuple[tuple[str, str], ...] = (
    ("rupees", "Rupees (12345.67)"),
    ("paise", "Paise (1234567)"),
)

AMOUNT_SIGNS: tuple[tuple[str, str, str], ...] = (
    ("as_is", "As written", "Take the sign in the file."),
    ("absolute", "Always positive", "Strip the sign. Statements that show debits as negative."),
    ("negate", "Flip the sign", "For files that write outgoing payments as negative."),
)

ID_TRANSFORMS: tuple[tuple[str, str, str], ...] = (
    ("trim", "Trim spaces", "Whitespace only."),
    ("upper", "Trim and upper-case", "For codes that differ only in case."),
    ("strip_leading_zeros", "Drop leading zeros", "'0042' and '42' are the same person."),
    ("digits_only", "Digits only", "Strips any prefix: 'EMP0042' becomes '0042'."),
    ("alnum_upper", "Letters and digits only, upper-cased", "Removes punctuation and spacing."),
)


def field_catalogue() -> dict:
    """Everything the profile editor needs, so the UI hard-codes none of it."""
    return {
        "fields": [
            {"key": f.key, "label": f.label, "required": f.required, "hint": f.hint}
            for f in BANK_FIELDS
        ],
        "kinds": [{"key": k, "label": lbl, "hint": h} for k, lbl, h in FILE_KINDS],
        "layouts": [{"key": k, "label": lbl, "hint": h} for k, lbl, h in LAYOUTS],
        "amount_units": [{"key": k, "label": lbl} for k, lbl in AMOUNT_UNITS],
        "amount_signs": [{"key": k, "label": lbl, "hint": h} for k, lbl, h in AMOUNT_SIGNS],
        "id_transforms": [{"key": k, "label": lbl, "hint": h} for k, lbl, h in ID_TRANSFORMS],
    }


# ---------------------------------------------------------------------------
# Starting points
# ---------------------------------------------------------------------------
# Deliberately called presets and not "bank formats". These are the layouts
# commonly seen from each channel, offered so an operator starts from something
# close rather than an empty form — but a corporate account can be provisioned
# with a different column set, and banks revise their specifications. Every one
# of these must be checked against the file the bank actually sends, which is
# what the "test against a file" step exists for.
PRESETS: tuple[dict[str, Any], ...] = (
    {
        "key": "generic_csv",
        "name": "Generic CSV",
        "bank_label": "Any",
        "note": "A plain header row. Start here when the file is your own export.",
        "layout": "delimited", "delimiter": ",", "has_header": True,
        "skip_rows": 0, "trailer_rows": 0, "amount_unit": "rupees", "amount_sign": "as_is",
        "employee_id_transform": "trim",
        "column_map": {
            "employee_id": "employee_id", "employee_name": "employee_name",
            "account_number": "account_number", "ifsc": "ifsc", "amount": "amount",
            "reference": "reference",
        },
    },
    {
        "key": "hdfc_bulk_neft",
        "name": "HDFC bulk NEFT (starting point)",
        "bank_label": "HDFC Bank",
        "note": "Headerless payment file, beneficiary code first. Check the column "
                "order against your own file before using.",
        "layout": "delimited", "delimiter": ",", "has_header": False,
        "skip_rows": 0, "trailer_rows": 0, "amount_unit": "rupees", "amount_sign": "as_is",
        "employee_id_transform": "trim",
        "column_map": {
            "employee_id": 2, "employee_name": 3, "account_number": 4,
            "ifsc": 5, "amount": 6, "reference": 7,
        },
    },
    {
        "key": "icici_cib",
        "name": "ICICI corporate internet banking (starting point)",
        "bank_label": "ICICI Bank",
        "note": "Header row present; amounts in rupees. Check against your own file.",
        "layout": "delimited", "delimiter": ",", "has_header": True,
        "skip_rows": 0, "trailer_rows": 0, "amount_unit": "rupees", "amount_sign": "as_is",
        "employee_id_transform": "trim",
        "column_map": {
            "employee_id": "Payee Code", "employee_name": "Payee Name",
            "account_number": "Payee Account No", "ifsc": "IFSC Code",
            "amount": "Amount", "reference": "Transaction Reference",
        },
    },
    {
        "key": "sbi_cinb",
        "name": "SBI corporate (starting point)",
        "bank_label": "State Bank of India",
        "note": "Pipe-delimited, no header, control total on the last line. Check "
                "the trailer count against your own file.",
        "layout": "delimited", "delimiter": "|", "has_header": False,
        "skip_rows": 0, "trailer_rows": 1, "amount_unit": "rupees", "amount_sign": "as_is",
        "employee_id_transform": "trim",
        "column_map": {
            "employee_id": 1, "employee_name": 2, "account_number": 3,
            "ifsc": 4, "amount": 5,
        },
    },
    {
        "key": "statement_generic",
        "name": "Bank statement (generic)",
        "bank_label": "Any",
        "note": "A downloaded statement, filtered to salary debits. Set the row "
                "filter to whatever your bank writes in the narration.",
        "kind": "bank_statement",
        "layout": "delimited", "delimiter": ",", "has_header": True,
        "skip_rows": 0, "trailer_rows": 0, "amount_unit": "rupees", "amount_sign": "absolute",
        "employee_id_transform": "trim",
        "column_map": {
            "employee_id": "Reference", "amount": "Withdrawal",
            "value_date": "Value Date", "reference": "Cheque/Ref No",
            "txn_type": "Description",
        },
    },
)

PRESET_BY_KEY = {p["key"]: p for p in PRESETS}


# ---------------------------------------------------------------------------
# Value parsing
# ---------------------------------------------------------------------------
_AMOUNT_STRIP = re.compile(r"[₹$,\s]")
_TRAILING_SIGN = re.compile(r"^(?P<body>.*?)\s*(?P<sign>CR|DR|C|D)$", re.IGNORECASE)
_NON_DIGIT = re.compile(r"\D")
_NON_ALNUM = re.compile(r"[^A-Za-z0-9]")

DATE_FORMATS = (
    "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y", "%d-%b-%Y", "%d %b %Y",
    "%m/%d/%Y", "%Y%m%d", "%d%m%Y",
)


def parse_amount(raw: Any, *, unit: str = "rupees", sign: str = "as_is") -> Decimal | None:
    """
    One amount, as the file wrote it.

    ``None`` rather than zero when the cell cannot be read as a number: a row
    whose amount is unreadable is an exception to be reported, and defaulting it
    to zero would hide a payment instead of flagging it.
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float, Decimal)):
        value = Decimal(str(raw))
    else:
        text = str(raw).strip()
        if not text:
            return None
        negative = False
        # Accounting parentheses, and the CR/DR suffix Indian statements use.
        if text.startswith("(") and text.endswith(")"):
            negative, text = True, text[1:-1]
        match = _TRAILING_SIGN.match(text)
        if match:
            text = match.group("body")
            if match.group("sign").upper() in {"DR", "D"}:
                negative = True
        text = _AMOUNT_STRIP.sub("", text)
        if not text or text in {"-", "+", "."}:
            return None
        try:
            value = Decimal(text)
        except InvalidOperation:
            return None
        if negative:
            value = -value

    if unit == "paise":
        value = value / PAISE
    if sign == "absolute":
        value = abs(value)
    elif sign == "negate":
        value = -value
    return _q(value)


def parse_bank_date(raw: Any, fmt: str | None = None) -> date | None:
    if raw in (None, ""):
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    text = str(raw).strip()
    if not text:
        return None
    formats = (fmt,) + DATE_FORMATS if fmt else DATE_FORMATS
    for candidate in formats:
        if not candidate:
            continue
        try:
            return datetime.strptime(text, candidate).date()
        except ValueError:
            continue
    return None


def normalise_employee_id(raw: Any, transform: str = "trim") -> str | None:
    """The join key, put into whichever shape both sides can agree on."""
    if raw is None:
        return None
    if isinstance(raw, float) and raw == int(raw):
        raw = int(raw)
    text = str(raw).strip()
    if not text or text.lower() in {"nan", "none"}:
        return None
    if transform == "upper":
        return text.upper()
    if transform == "strip_leading_zeros":
        stripped = text.lstrip("0")
        return (stripped or "0").upper()
    if transform == "digits_only":
        digits = _NON_DIGIT.sub("", text)
        return digits or None
    if transform == "alnum_upper":
        return (_NON_ALNUM.sub("", text) or "").upper() or None
    return text


def match_key(raw: Any, transform: str = "trim") -> str | None:
    """
    The comparison key for an employee code.

    Both sides go through the profile's transform *and* an upper-casing, so a
    register holding ``emp0042`` still meets a bank file holding ``EMP0042``.
    Matching on an exact string would report the entire payroll as unmatched
    over a case difference, which is the least useful possible answer.
    """
    value = normalise_employee_id(raw, transform)
    return value.upper() if value else None


# ---------------------------------------------------------------------------
# Reading a file
# ---------------------------------------------------------------------------
@dataclass
class ParsedRow:
    row_number: int
    employee_id: str | None
    employee_name: str | None
    account_number: str | None
    ifsc: str | None
    amount: Decimal
    reference: str | None
    status: str | None
    value_date: date | None
    raw: dict[str, Any]


@dataclass
class ParseResult:
    rows: list[ParsedRow] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    stated_total: Decimal | None = None
    header: list[str] = field(default_factory=list)
    skipped: int = 0

    @property
    def total(self) -> Decimal:
        return _q(sum((r.amount for r in self.rows), Decimal("0")))


class ProfileError(ValueError):
    """The profile cannot read this file, and saying how is the whole job."""


def _as_profile(profile: Any) -> dict[str, Any]:
    """Accept an ORM profile or a plain dict, so a dry run needs no saved row."""
    if isinstance(profile, dict):
        data = dict(profile)
    else:
        data = {
            "layout": getattr(profile, "layout", "delimited"),
            "delimiter": getattr(profile, "delimiter", ","),
            "encoding": getattr(profile, "encoding", "utf-8"),
            "has_header": getattr(profile, "has_header", True),
            "skip_rows": getattr(profile, "skip_rows", 0),
            "trailer_rows": getattr(profile, "trailer_rows", 0),
            "column_map": getattr(profile, "column_map", {}) or {},
            "amount_unit": getattr(profile, "amount_unit", "rupees"),
            "amount_sign": getattr(profile, "amount_sign", "as_is"),
            "date_format": getattr(profile, "date_format", None),
            "employee_id_transform": getattr(profile, "employee_id_transform", "trim"),
            "row_filter": getattr(profile, "row_filter", {}) or {},
        }
    data.setdefault("column_map", {})
    data.setdefault("row_filter", {})
    return data


def _raw_table(content: bytes, filename: str, cfg: dict[str, Any]) -> tuple[list[str], list[list[str]]]:
    """The file as a header and a list of string rows, before any mapping."""
    layout = cfg.get("layout", "delimited")

    if layout == "excel" or filename.lower().endswith((".xlsx", ".xls")):
        import pandas as pd

        frame = pd.read_excel(io.BytesIO(content), engine="openpyxl", header=None, dtype=str)
        table = [["" if v is None or str(v) == "nan" else str(v) for v in row]
                 for row in frame.values.tolist()]
    elif layout == "fixed":
        text = content.decode(cfg.get("encoding") or "utf-8", errors="replace")
        # Fixed-width rows are sliced per field later, so the whole line is kept
        # as a single cell here.
        table = [[line] for line in text.splitlines() if line.strip()]
    else:
        text = content.decode(cfg.get("encoding") or "utf-8", errors="replace")
        delimiter = (cfg.get("delimiter") or ",")[:1] or ","
        if delimiter == "\\t":
            delimiter = "\t"
        table = [row for row in csv.reader(io.StringIO(text), delimiter=delimiter) if any(
            str(cell).strip() for cell in row
        )]

    skip = max(int(cfg.get("skip_rows") or 0), 0)
    table = table[skip:]

    header: list[str] = []
    if cfg.get("has_header") and layout != "fixed" and table:
        header = [str(c).strip() for c in table[0]]
        table = table[1:]
    return header, table


def _cell(row: list[str], header: list[str], spec: Any, layout: str) -> Any:
    """One field out of one row, however the profile addresses it."""
    if spec is None or spec == "":
        return None
    if layout == "fixed":
        if not isinstance(spec, (list, tuple)) or len(spec) != 2:
            return None
        start, length = int(spec[0]), int(spec[1])
        line = row[0] if row else ""
        return line[max(start - 1, 0): max(start - 1, 0) + length].strip()
    if isinstance(spec, bool):
        return None
    if isinstance(spec, int):
        index = spec - 1  # profiles are written 1-based, as bank specs are
        return row[index] if 0 <= index < len(row) else None
    name = str(spec).strip()
    if header:
        lowered = [h.strip().lower() for h in header]
        key = name.lower()
        if key in lowered:
            index = lowered.index(key)
            return row[index] if index < len(row) else None
    # A name against a headerless file is a configuration error rather than a
    # missing value, and is reported as one by the caller.
    return None


def _passes_filter(row: list[str], header: list[str], cfg: dict[str, Any], layout: str) -> bool:
    rule = cfg.get("row_filter") or {}
    column = rule.get("column")
    if not column:
        return True
    value = _cell(row, header, column, layout)
    text = ("" if value is None else str(value)).strip().lower()
    include = [str(v).strip().lower() for v in (rule.get("in") or [])]
    exclude = [str(v).strip().lower() for v in (rule.get("not_in") or [])]
    contains = str(rule.get("contains") or "").strip().lower()
    if include and not any(text == v for v in include):
        return False
    if exclude and any(text == v for v in exclude):
        return False
    return not (contains and contains not in text)


def parse_bank_file(content: bytes, filename: str, profile: Any) -> ParseResult:
    """
    Apply one profile to one file.

    Rows that cannot be read are reported in ``problems`` and left out of
    ``rows``, so the total never silently includes a line nobody could parse.
    """
    cfg = _as_profile(profile)
    column_map = cfg.get("column_map") or {}
    layout = cfg.get("layout", "delimited")

    missing = [f for f in REQUIRED_FIELDS if not column_map.get(f)]
    if missing:
        raise ProfileError(
            "This profile does not say which column holds: "
            + ", ".join(missing)
            + ". Map every required field before reading a file — a reconciliation "
              "built on a guessed column would agree with itself and prove nothing."
        )

    header, table = _raw_table(content, filename, cfg)
    if not table:
        raise ProfileError("No data rows were found once the header and skipped rows were removed.")

    result = ParseResult(header=header)

    trailer_count = max(int(cfg.get("trailer_rows") or 0), 0)
    if trailer_count:
        if trailer_count >= len(table):
            raise ProfileError(
                f"The profile drops {trailer_count} trailer row(s) but the file has "
                f"only {len(table)} row(s) of data."
            )
        trailer, table = table[-trailer_count:], table[:-trailer_count]
        # A control total on the trailer is read from the same column the
        # payment amount comes from, which is where banks put it.
        stated = parse_amount(
            _cell(trailer[0], header, column_map.get("amount"), layout),
            unit=cfg.get("amount_unit", "rupees"),
            sign="absolute",
        )
        if stated is not None:
            result.stated_total = stated

    if header and not any(
        isinstance(spec, str) and spec.strip().lower() in {h.strip().lower() for h in header}
        for spec in column_map.values()
        if spec
    ) and any(isinstance(spec, str) for spec in column_map.values() if spec):
        result.problems.append(
            "None of the column names in this profile appear in the file's header row. "
            f"The file's columns are: {', '.join(header[:12])}"
            + ("…" if len(header) > 12 else "")
        )

    transform = cfg.get("employee_id_transform", "trim")
    unit = cfg.get("amount_unit", "rupees")
    sign = cfg.get("amount_sign", "as_is")
    date_fmt = cfg.get("date_format")

    for offset, row in enumerate(table, start=1):
        if not _passes_filter(row, header, cfg, layout):
            result.skipped += 1
            continue

        amount = parse_amount(
            _cell(row, header, column_map.get("amount"), layout), unit=unit, sign=sign
        )
        if amount is None:
            result.problems.append(f"Row {offset}: the amount could not be read as a number.")
            continue

        raw: dict[str, Any] = {}
        if header:
            raw = {h: (row[i] if i < len(row) else None) for i, h in enumerate(header)}
        elif layout != "fixed":
            raw = {str(i + 1): value for i, value in enumerate(row)}
        else:
            raw = {"line": row[0] if row else ""}

        result.rows.append(
            ParsedRow(
                row_number=offset,
                employee_id=normalise_employee_id(
                    _cell(row, header, column_map.get("employee_id"), layout), transform
                ),
                employee_name=_text(_cell(row, header, column_map.get("employee_name"), layout)),
                account_number=_digits_or_text(
                    _cell(row, header, column_map.get("account_number"), layout)
                ),
                ifsc=_upper(_cell(row, header, column_map.get("ifsc"), layout)),
                amount=amount,
                reference=_text(_cell(row, header, column_map.get("reference"), layout)),
                status=_text(_cell(row, header, column_map.get("status"), layout)),
                value_date=parse_bank_date(
                    _cell(row, header, column_map.get("value_date"), layout), date_fmt
                ),
                raw=raw,
            )
        )

    if not result.rows:
        raise ProfileError(
            "No row in this file could be read with this profile. "
            + (result.problems[0] if result.problems else "Check the column mapping.")
        )

    unidentified = sum(1 for r in result.rows if not r.employee_id)
    if unidentified:
        result.problems.append(
            f"{unidentified} of {len(result.rows)} rows carry no employee code. Those rows "
            "can only be reconciled in total, not line by line."
        )
    return result


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _upper(value: Any) -> str | None:
    text = _text(value)
    return text.upper() if text else None


def _digits_or_text(value: Any) -> str | None:
    """
    An account number, kept as written.

    Not coerced to a number: leading zeros are significant, and a long account
    number that has been through a float is a different account number.
    """
    if value is None:
        return None
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    return _text(value)


# ---------------------------------------------------------------------------
# Helping an operator build a mapping
# ---------------------------------------------------------------------------
_HEADER_HINTS: dict[str, tuple[str, ...]] = {
    "employee_id": ("employee_id", "employee code", "emp code", "empcode", "payee code",
                    "beneficiary code", "emp id", "employee no", "staff id", "emp_no"),
    "employee_name": ("employee_name", "beneficiary name", "payee name", "name",
                      "account name", "beneficiary"),
    "account_number": ("account", "account number", "account no", "a/c no", "acno",
                       "payee account", "beneficiary account", "bank account"),
    "ifsc": ("ifsc", "ifsc code", "branch code", "neft code"),
    "amount": ("amount", "net amount", "payment amount", "txn amount", "debit",
               "withdrawal", "net pay", "transaction amount"),
    "reference": ("reference", "utr", "ref no", "transaction reference", "cheque",
                  "narration", "remarks"),
    "status": ("status", "txn status", "payment status", "result"),
    "value_date": ("value date", "date", "txn date", "transaction date", "payment date"),
    "txn_type": ("type", "txn type", "transaction type", "description", "particulars"),
}


def suggest_mapping(content: bytes, filename: str, *, delimiter: str = ",") -> dict[str, Any]:
    """
    Read a file's header row and propose a mapping for an operator to confirm.

    A proposal only. It is returned alongside the headers it was drawn from so
    the person approving it can see what it matched against, and nothing is
    saved until they say so.
    """
    cfg = {
        "layout": "excel" if filename.lower().endswith((".xlsx", ".xls")) else "delimited",
        "delimiter": delimiter, "has_header": True, "skip_rows": 0, "trailer_rows": 0,
    }
    header, table = _raw_table(content, filename, cfg)
    if not header:
        return {
            "header": [], "sample": [row[:12] for row in table[:5]], "column_map": {},
            "note": "This file has no header row. Map each field to its column number instead.",
        }

    lowered = [h.strip().lower() for h in header]
    proposed: dict[str, Any] = {}
    taken: set[int] = set()
    for field_key, hints in _HEADER_HINTS.items():
        best: tuple[int, int] | None = None  # (specificity, index)
        for index, name in enumerate(lowered):
            if index in taken or not name:
                continue
            for hint in hints:
                if name == hint:
                    score = 100
                elif hint in name:
                    score = len(hint)
                else:
                    continue
                if best is None or score > best[0]:
                    best = (score, index)
        if best is not None:
            proposed[field_key] = header[best[1]]
            taken.add(best[1])

    return {
        "header": header,
        "sample": [row[:12] for row in table[:5]],
        "column_map": proposed,
        "unmapped_columns": [h for i, h in enumerate(header) if i not in taken and h],
        "note": "A suggestion from the header row. Check every line of it against the "
                "bank's own file specification before saving.",
    }
