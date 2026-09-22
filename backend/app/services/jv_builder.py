"""
Turning a month of payroll cost into this company's journal voucher.

There is no standard payroll JV. The accounts are the company's own chart, the
split is whatever its ERP posts by, and whether gratuity is an expense this
month or a year-end provision is an accounting policy rather than a fact. A
module that hard-coded any of that would be right for one client.

So a template is data: ordered :class:`~app.models.JvRule` lines, each naming
**measures from the cost taxonomy**, an account, and a side. That indirection is
the point. A line mapped to ``er_pf`` posts exactly the employer PF the cost
dashboard reports, from the same costing pass, so the ledger and the dashboard
cannot tell two different stories about the same month.

Why a correct template balances by itself
-----------------------------------------
The ordinary Indian payroll voucher is::

    Dr  Salaries & wages                    gross
    Dr  Employer PF / ESI / gratuity        employer contributions
        Cr  PF payable                          employee PF + employer PF
        Cr  ESI / PT / TDS payable              the other deductions
        Cr  Gratuity provision                  gratuity
        Cr  Salary payable (bank)                net

and it balances for an arithmetic reason rather than a lucky one::

    debits  = gross + employer
    credits = employer + deductions + net
            = employer + deductions + (gross - deductions)
            = employer + gross

Which means the balance check is not a formality: it is a real test of the
*company's own mapping*. Forget to credit TDS payable and the credits fall
short by exactly the TDS. The check reports that, in rupees, naming the measure
that has no home.
"""
from __future__ import annotations

import uuid
from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.services.cost_model import (
    DEDUCTION_KEYS,
    DERIVED_LABELS,
    EARNING_KEYS,
    EMPLOYER_KEYS,
    MEASURE_BY_KEY,
    MEASURE_KEYS,
    with_derived,
)
from app.services.dimensions import DIMENSION_KEYS, DIMENSION_LABELS, UNASSIGNED

CENT = Decimal("0.01")


def _q(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# The options a company chooses between
# ---------------------------------------------------------------------------
POSTING_BASES: tuple[tuple[str, str, str], ...] = (
    ("accrual", "Accrual",
     "Every employer contribution, gratuity included, hits the month it is earned."),
    ("cash", "Cash / disbursement",
     "Only what is paid or remitted. Gratuity is left out, to be provided for separately."),
)

SPLIT_MODES: tuple[tuple[str, str, str], ...] = (
    ("consolidated", "One voucher",
     "A single voucher for the entity; each line carries its cost centre as a tag."),
    ("per_group", "One voucher per cost centre",
     "A separate, self-balancing voucher for each value of the grouping dimension."),
)

DETAIL_LEVELS: tuple[tuple[str, str, str], ...] = (
    ("summary", "One line per account", "The usual voucher: an account, a total."),
    ("by_component", "One line per component",
     "Each measure on its own line under its account. Longer, but traceable."),
    ("by_employee", "One line per employee",
     "Employee-wise posting. Only viable for small headcounts, and it carries "
     "individual pay into the ledger — check who can read your GL first."),
)

SIGN_CONVENTIONS: tuple[tuple[str, str, str], ...] = (
    ("two_column", "Debit and credit columns", "Separate columns, the accounting layout."),
    ("signed", "One signed amount column", "Credits negative. What most ERP imports expect."),
)

VOUCHER_DATE_RULES: tuple[tuple[str, str, str], ...] = (
    ("month_end", "Last day of the payroll month", "The usual accrual date."),
    ("month_start", "First day of the payroll month", ""),
    ("next_month_start", "First day of the following month",
     "For companies that post the salary voucher in the month of payment."),
)

ROUNDING_MODES: tuple[tuple[str, str, str], ...] = (
    ("none", "Report the difference",
     "Leave the voucher as it falls and report any imbalance. The honest default."),
    ("account", "Post to a rounding account",
     "Force the balance by posting the difference to a named account."),
    ("largest_line", "Absorb into the largest line",
     "Adjust the biggest line by the difference. Common, and it hides mapping errors "
     "as well as rounding — the reported imbalance still tells you which it was."),
)

NET_PAY_SOURCES: tuple[tuple[str, str, str], ...] = (
    ("computed", "Gross less deductions",
     "Derived from the taxonomy, so the voucher always balances."),
    ("stated", "The net the register declared",
     "What the bank was told to pay. Will not balance where the register deducts "
     "something it does not itemise, and that gap is reported."),
)

# Shaped like each system's import file, and labelled as a starting point
# rather than a specification: import layouts are version- and tenant-specific,
# and the only authority is the target system's own documentation.
EXPORT_FORMATS: tuple[tuple[str, str, str], ...] = (
    ("generic_csv", "Generic CSV", "Account, cost centre, debit, credit, narration."),
    ("tally_csv", "Tally-style CSV", "Ledger name and Dr/Cr per line."),
    ("sap_csv", "SAP-style CSV", "GL account with an S/H posting key and a cost centre."),
    ("zoho_csv", "Zoho Books-style CSV", "Journal date, account, debit, credit."),
    ("json", "JSON", "The whole document, for an integration to consume."),
)

# Measures a posting basis leaves out entirely.
BASIS_EXCLUDES: dict[str, tuple[str, ...]] = {
    "accrual": (),
    "cash": ("gratuity",),
}


def _options(rows: tuple[tuple[str, str, str], ...]) -> list[dict[str, str]]:
    return [{"key": k, "label": label, "hint": hint} for k, label, hint in rows]


def option_catalogue() -> dict:
    """Every choice a template exposes, so the editor hard-codes nothing."""
    return {
        "posting_bases": _options(POSTING_BASES),
        "split_modes": _options(SPLIT_MODES),
        "detail_levels": _options(DETAIL_LEVELS),
        "sign_conventions": _options(SIGN_CONVENTIONS),
        "voucher_date_rules": _options(VOUCHER_DATE_RULES),
        "rounding_modes": _options(ROUNDING_MODES),
        "net_pay_sources": _options(NET_PAY_SOURCES),
        "export_formats": _options(EXPORT_FORMATS),
        "group_by": [{"key": "", "label": "Do not split", "hint": "One set of lines for the entity."}]
        + [{"key": k, "label": DIMENSION_LABELS[k], "hint": ""} for k in DIMENSION_KEYS],
        "sides": [
            {"key": "debit", "label": "Debit", "hint": "Expense and asset lines."},
            {"key": "credit", "label": "Credit", "hint": "Liability and payable lines."},
        ],
        "measures": measure_catalogue(),
    }


def measure_catalogue() -> list[dict[str, Any]]:
    """The measures a rule can map, grouped the way the taxonomy groups them."""
    out: list[dict[str, Any]] = []
    for key in MEASURE_KEYS:
        measure = MEASURE_BY_KEY[key]
        out.append({
            "key": key, "label": measure.label, "layer": measure.layer,
            "hint": measure.hint, "derived": False, "parts": [key],
        })
    for key in ("gross", "employer_cost", "ctc", "deductions", "net"):
        # ``parts`` is sent rather than left for the client to infer, so the
        # editor's coverage indicator and the voucher's own coverage check read
        # the same expansion. Two copies of that map would drift.
        parts = sorted(expand_measures([key]))
        out.append({
            "key": key,
            "label": DERIVED_LABELS.get(key, "Net pay"),
            "layer": "derived",
            "hint": (
                "Roll-up of " + ", ".join(MEASURE_BY_KEY[p].label for p in parts)
                if parts else
                "The residual that balances the voucher. It stands in for no cost measure "
                "of its own, so the deductions netted out of it still need their own "
                "payable lines."
            ),
            "derived": True,
            "parts": parts,
        })
    return out


# Derived keys, in terms of the base measures they stand for. Used by the
# coverage check: a rule naming "gross" has accounted for every earning.
_EXPANSIONS: dict[str, tuple[str, ...]] = {
    "gross": EARNING_KEYS,
    "employer_cost": EMPLOYER_KEYS,
    "ctc": EARNING_KEYS + EMPLOYER_KEYS,
    "deductions": DEDUCTION_KEYS,
    # Net is deliberately absent. It is the residual that makes the voucher
    # balance, not a bucket of cost, and treating it as cover for the
    # deductions inside it would make the coverage check blind to exactly the
    # error it exists to catch: a template that nets TDS out of salary payable
    # but never credits TDS payable.
    "net": (),
}


def expand_measures(keys: list[str] | tuple[str, ...]) -> set[str]:
    out: set[str] = set()
    for key in keys or ():
        if key in _EXPANSIONS:
            out.update(_EXPANSIONS[key])
        elif key in MEASURE_KEYS:
            out.add(key)
    return out


# ---------------------------------------------------------------------------
# Starting-point templates
# ---------------------------------------------------------------------------
# Account codes here are placeholders in an obvious range. They exist so a new
# client sees a complete, balancing voucher on day one and edits the codes,
# rather than facing an empty rule list and guessing what a payroll JV contains.
PRESETS: tuple[dict[str, Any], ...] = (
    {
        "key": "standard_accrual",
        "name": "Standard accrual voucher",
        "note": "The usual monthly voucher: gross and employer cost debited, every "
                "statutory liability and net pay credited. Balances by construction.",
        "posting_basis": "accrual", "split_mode": "consolidated", "detail_level": "summary",
        "group_by": None, "sign_convention": "two_column", "net_pay_source": "computed",
        "rules": [
            {"label": "Salaries & wages", "account_code": "5001", "side": "debit",
             "measures": ["basic_da", "hra", "allowances"]},
            {"label": "Variable pay & bonus", "account_code": "5002", "side": "debit",
             "measures": ["variable_pay"]},
            {"label": "Arrears & one-time payments", "account_code": "5003", "side": "debit",
             "measures": ["arrears"]},
            {"label": "Employer PF contribution", "account_code": "5101", "side": "debit",
             "measures": ["er_pf", "er_pf_admin"]},
            {"label": "Employer ESI contribution", "account_code": "5102", "side": "debit",
             "measures": ["er_esi"]},
            {"label": "Gratuity expense", "account_code": "5103", "side": "debit",
             "measures": ["gratuity"]},
            {"label": "Employer LWF contribution", "account_code": "5104", "side": "debit",
             "measures": ["er_lwf"]},
            {"label": "PF payable", "account_code": "2101", "side": "credit",
             "measures": ["ee_pf", "er_pf", "er_pf_admin"]},
            {"label": "ESI payable", "account_code": "2102", "side": "credit",
             "measures": ["ee_esi", "er_esi"]},
            {"label": "Professional tax payable", "account_code": "2103", "side": "credit",
             "measures": ["pt"]},
            {"label": "LWF payable", "account_code": "2104", "side": "credit",
             "measures": ["ee_lwf", "er_lwf"]},
            {"label": "TDS payable", "account_code": "2105", "side": "credit",
             "measures": ["tds"]},
            {"label": "Gratuity provision", "account_code": "2106", "side": "credit",
             "measures": ["gratuity"]},
            {"label": "Salary payable", "account_code": "2001", "side": "credit",
             "measures": ["net"]},
        ],
    },
    {
        "key": "cost_centre_split",
        "name": "Cost-centre split voucher",
        "note": "The same mapping, one voucher per cost centre. For ledgers that post "
                "by profit centre.",
        "posting_basis": "accrual", "split_mode": "per_group", "detail_level": "summary",
        "group_by": "cost_center", "sign_convention": "two_column", "net_pay_source": "computed",
        "rules": "standard_accrual",
    },
    {
        "key": "cash_basis",
        "name": "Cash-basis voucher (no gratuity accrual)",
        "note": "For companies that provide for gratuity annually on an actuarial "
                "valuation rather than monthly.",
        "posting_basis": "cash", "split_mode": "consolidated", "detail_level": "summary",
        "group_by": None, "sign_convention": "two_column", "net_pay_source": "computed",
        "rules": "standard_accrual",
    },
)


def preset_rules(key: str) -> list[dict[str, Any]]:
    """The rule list for a preset, resolving one preset's reference to another."""
    preset = next((p for p in PRESETS if p["key"] == key), None)
    if preset is None:
        return []
    rules = preset.get("rules")
    if isinstance(rules, str):
        return preset_rules(rules)
    if rules:
        return [dict(r) for r in rules]
    # A preset with no rule list of its own inherits the standard mapping; the
    # posting basis is what makes it different, not the accounts.
    return preset_rules("standard_accrual")


def preset_catalogue() -> list[dict[str, Any]]:
    out = []
    for preset in PRESETS:
        data = {k: v for k, v in preset.items() if k != "rules"}
        data["rules"] = preset_rules(preset["key"])
        data["rule_count"] = len(data["rules"])
        out.append(data)
    return out


# ---------------------------------------------------------------------------
# Building a voucher
# ---------------------------------------------------------------------------
@dataclass
class JvLine:
    account_code: str
    account_name: str
    label: str
    side: str
    amount: Decimal
    cost_center: str | None = None
    measures: list[str] = field(default_factory=list)
    employee_id: str | None = None
    employee_name: str | None = None

    @property
    def debit(self) -> Decimal:
        return self.amount if self.side == "debit" else Decimal("0")

    @property
    def credit(self) -> Decimal:
        return self.amount if self.side == "credit" else Decimal("0")

    def as_dict(self) -> dict[str, Any]:
        return {
            "account_code": self.account_code, "account_name": self.account_name,
            "label": self.label, "side": self.side, "amount": float(self.amount),
            "debit": float(self.debit), "credit": float(self.credit),
            "cost_center": self.cost_center, "measures": list(self.measures),
            "employee_id": self.employee_id, "employee_name": self.employee_name,
        }


@dataclass
class Voucher:
    number: str
    voucher_date: date
    voucher_type: str
    scope: str | None
    narration: str
    lines: list[JvLine] = field(default_factory=list)

    @property
    def total_debit(self) -> Decimal:
        return _q(sum((line.debit for line in self.lines), Decimal("0")))

    @property
    def total_credit(self) -> Decimal:
        return _q(sum((line.credit for line in self.lines), Decimal("0")))

    @property
    def difference(self) -> Decimal:
        return _q(self.total_debit - self.total_credit)

    def as_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "date": self.voucher_date.isoformat(),
            "type": self.voucher_type,
            "scope": self.scope,
            "narration": self.narration,
            "lines": [line.as_dict() for line in self.lines],
            "total_debit": float(self.total_debit),
            "total_credit": float(self.total_credit),
            "difference": float(self.difference),
            "balanced": self.difference == 0,
        }


@dataclass
class JvDocument:
    period_month: date
    template_name: str
    vouchers: list[Voucher] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # The same problems as ``warnings``, structured. Reconciliation turns these
    # into stored exceptions; the strings are what a reader sees.
    issues: list[dict[str, Any]] = field(default_factory=list)
    cost_totals: dict[str, Decimal] = field(default_factory=dict)
    employee_count: int = 0
    options: dict[str, Any] = field(default_factory=dict)

    @property
    def total_debit(self) -> Decimal:
        return _q(sum((v.total_debit for v in self.vouchers), Decimal("0")))

    @property
    def total_credit(self) -> Decimal:
        return _q(sum((v.total_credit for v in self.vouchers), Decimal("0")))

    @property
    def difference(self) -> Decimal:
        return _q(self.total_debit - self.total_credit)

    def as_dict(self) -> dict[str, Any]:
        return {
            "period": self.period_month.isoformat(),
            "period_label": self.period_month.strftime("%b %Y"),
            "template": self.template_name,
            "options": self.options,
            "employee_count": self.employee_count,
            "vouchers": [v.as_dict() for v in self.vouchers],
            "total_debit": float(self.total_debit),
            "total_credit": float(self.total_credit),
            "difference": float(self.difference),
            "balanced": self.difference == 0,
            "warnings": list(self.warnings),
            "issues": [dict(i) for i in self.issues],
            "cost_totals": {k: float(v) for k, v in self.cost_totals.items()},
        }


def _note(
    document: JvDocument,
    code: str,
    severity: str,
    title: str,
    *,
    detail: str | None = None,
    expected: Decimal | None = None,
    actual: Decimal | None = None,
    difference: Decimal | None = None,
    scope: str | None = None,
    context: dict[str, Any] | None = None,
) -> None:
    """Record one problem, both as a sentence and as something storable."""
    document.warnings.append(title if detail is None else f"{title} {detail}")
    document.issues.append({
        "code": code, "severity": severity, "title": title, "detail": detail,
        "expected": None if expected is None else float(expected),
        "actual": None if actual is None else float(actual),
        "difference": None if difference is None else float(difference),
        "scope": scope, "context": context or {},
    })


def _voucher_date(period: date, rule: str) -> date:
    first = period.replace(day=1)
    if rule == "month_start":
        return first
    if rule == "next_month_start":
        return (first.replace(day=28) + timedelta(days=7)).replace(day=1)
    return first.replace(day=monthrange(first.year, first.month)[1])


def _matches(dimensions: dict[str, Any], filters: dict[str, Any]) -> bool:
    for key, allowed in (filters or {}).items():
        if not allowed:
            continue
        value = str(dimensions.get(key) or UNASSIGNED)
        if value not in {str(v) for v in allowed}:
            return False
    return True


def _opt(template: Any, name: str, default: Any) -> Any:
    value = getattr(template, name, None) if not isinstance(template, dict) else template.get(name)
    return default if value in (None, "") else value


def build_jv(
    db: Session,
    entity_id: uuid.UUID,
    period_month: date,
    template: Any,
    *,
    rules: list[Any] | None = None,
) -> JvDocument:
    """
    Build the voucher for one month under one template.

    Reads the stored register through the same costing pass the dashboard uses,
    so there is exactly one set of numbers in the product.
    """
    from app.services.analytics import _Costing, _register_rows

    period = period_month.replace(day=1)
    basis = _opt(template, "posting_basis", "accrual")
    split_mode = _opt(template, "split_mode", "consolidated")
    detail = _opt(template, "detail_level", "summary")
    group_by = _opt(template, "group_by", None)
    net_source = _opt(template, "net_pay_source", "computed")
    date_rule = _opt(template, "voucher_date_rule", "month_end")
    voucher_type = _opt(template, "voucher_type", "Journal")
    narration_template = _opt(
        template, "narration_template", "Payroll for {period_label}{scope_suffix}"
    )
    tolerance = Decimal(str(_opt(template, "balance_tolerance", "1.00")))
    rounding_mode = _opt(template, "rounding_mode", "none")
    rounding_account = _opt(template, "rounding_account", None)
    template_name = _opt(template, "name", "Untitled template")

    active_rules = [
        r for r in (rules if rules is not None else getattr(template, "rules", []) or [])
        if _opt(r, "active", True)
    ]
    active_rules.sort(key=lambda r: int(_opt(r, "sequence", 0) or 0))

    document = JvDocument(
        period_month=period,
        template_name=str(template_name),
        options={
            "posting_basis": basis, "split_mode": split_mode, "detail_level": detail,
            "group_by": group_by, "net_pay_source": net_source,
            "sign_convention": _opt(template, "sign_convention", "two_column"),
            "voucher_date_rule": date_rule, "rounding_mode": rounding_mode,
            "balance_tolerance": float(tolerance),
        },
    )

    rows, _ = _register_rows(db, entity_id, period, period)
    if not rows:
        _note(
            document, "jv.no_register", "high",
            f"No salary register is stored for {period.strftime('%B %Y')}, so there is "
            "nothing to post. Upload the register for this month first.",
        )
        return document
    if not active_rules:
        _note(
            document, "jv.no_rules", "high",
            "This template has no active rules, so it produces an empty voucher. "
            "Add at least one debit and one credit line.",
        )

    excluded = set(BASIS_EXCLUDES.get(basis, ()))
    costing = _Costing(db, entity_id)

    # Per-employee measure values, costed once and reused by every rule.
    entries: list[dict[str, Any]] = []
    cost_totals: dict[str, Decimal] = {}
    for row in rows:
        base = costing.cost(row).measures
        if excluded:
            base = {k: (Decimal("0") if k in excluded else v) for k, v in base.items()}
        values = with_derived(base)
        if net_source == "stated" and getattr(row, "net_pay", None) is not None:
            values["net"] = Decimal(str(row.net_pay))
        entries.append({
            "employee_id": row.employee_id,
            "employee_name": row.employee_name,
            "dimensions": row.dimensions or {},
            "values": values,
        })
        for key, value in values.items():
            cost_totals[key] = cost_totals.get(key, Decimal("0")) + value

    names = {e["employee_id"]: e["employee_name"] for e in entries}
    document.employee_count = len(entries)
    document.cost_totals = {k: _q(v) for k, v in cost_totals.items()}

    # ---- collect the lines ------------------------------------------------
    # Keyed by (scope, rule index, detail key) so ordering follows the rule
    # sequence the company set rather than dictionary insertion luck.
    collected: dict[str, list[JvLine]] = {}

    for index, rule in enumerate(active_rules):
        measures = list(_opt(rule, "measures", []) or [])
        if not measures:
            _note(
                document, "jv.rule_maps_nothing", "medium",
                f"Rule {index + 1} ({_opt(rule, 'label', 'unnamed')}) maps no measures, "
                "so it posts nothing.",
                context={"rule": index + 1},
            )
            continue
        side = str(_opt(rule, "side", "debit"))
        account_code = str(_opt(rule, "account_code", "") or "")
        account_name = str(_opt(rule, "account_name", "") or _opt(rule, "label", ""))
        label = str(_opt(rule, "label", account_name or account_code))
        filters = _opt(rule, "filters", {}) or {}
        line_group = _opt(rule, "cost_center_from", None) or group_by

        if not account_code:
            _note(
                document, "jv.missing_account_code", "medium",
                f"Rule {index + 1} ({label}) has no account code. The voucher will "
                "still total correctly, but it cannot be imported as it stands.",
                context={"rule": index + 1, "label": label},
            )

        buckets: dict[tuple[str | None, str | None, str | None], Decimal] = {}
        for entry in entries:
            if not _matches(entry["dimensions"], filters):
                continue
            scope = (
                str(entry["dimensions"].get(line_group) or UNASSIGNED) if line_group else None
            )
            if detail == "by_component":
                for measure in measures:
                    amount = entry["values"].get(measure, Decimal("0"))
                    if amount:
                        key = (scope, measure, None)
                        buckets[key] = buckets.get(key, Decimal("0")) + amount
            elif detail == "by_employee":
                amount = sum(
                    (entry["values"].get(m, Decimal("0")) for m in measures), Decimal("0")
                )
                if amount:
                    key = (scope, None, entry["employee_id"])
                    buckets[key] = buckets.get(key, Decimal("0")) + amount
            else:
                amount = sum(
                    (entry["values"].get(m, Decimal("0")) for m in measures), Decimal("0")
                )
                key = (scope, None, None)
                buckets[key] = buckets.get(key, Decimal("0")) + amount

        for (scope, measure, employee_id), amount in buckets.items():
            amount = _q(amount)
            if amount == 0:
                # A rule that matched nothing this month posts nothing. Several
                # ledger imports reject a zero line outright, and a voucher
                # padded with them is harder to read, not more complete.
                continue
            voucher_key = scope if split_mode == "per_group" else ""
            line_label = label
            if measure and measure in MEASURE_BY_KEY:
                line_label = f"{label} — {MEASURE_BY_KEY[measure].label}"
            elif employee_id:
                line_label = f"{label} — {employee_id}"
            collected.setdefault(voucher_key or "", []).append(
                JvLine(
                    account_code=account_code,
                    account_name=account_name or label,
                    label=line_label,
                    side=side,
                    amount=amount,
                    cost_center=scope,
                    measures=[measure] if measure else list(measures),
                    employee_id=employee_id,
                    employee_name=names.get(employee_id) if employee_id else None,
                )
            )

    if not collected:
        collected = {"": []}

    # ---- assemble vouchers -------------------------------------------------
    period_label = period.strftime("%B %Y")
    for scope in sorted(collected):
        lines = collected[scope]
        scope_label = scope or None
        number = f"PAY-{period:%Y%m}" + (f"-{_slug(scope)}" if scope else "")
        narration = _narrate(
            narration_template, period_label=period_label, scope=scope_label,
            template_name=str(template_name),
        )
        voucher = Voucher(
            number=number,
            voucher_date=_voucher_date(period, date_rule),
            voucher_type=str(voucher_type),
            scope=scope_label,
            narration=narration,
            lines=lines,
        )
        _apply_rounding(voucher, rounding_mode, rounding_account, tolerance, document)
        document.vouchers.append(voucher)

    _check(document, active_rules, tolerance)
    return document


def _slug(value: str) -> str:
    cleaned = "".join(c if c.isalnum() else "-" for c in str(value)).strip("-")
    return (cleaned[:24] or "NA").upper()


def _narrate(pattern: str, *, period_label: str, scope: str | None, template_name: str = "") -> str:
    values = {
        "period_label": period_label,
        "scope": scope or "",
        "scope_suffix": f" — {scope}" if scope else "",
        "template": template_name,
    }
    try:
        return str(pattern).format(**values)
    except (KeyError, IndexError, ValueError):
        # A narration is a label, not a calculation. An unknown placeholder
        # should not stop a voucher from being produced.
        return f"Payroll for {period_label}" + (f" — {scope}" if scope else "")


def _apply_rounding(
    voucher: Voucher,
    mode: str,
    account: str | None,
    tolerance: Decimal,
    document: JvDocument,
) -> None:
    difference = voucher.difference
    if difference == 0 or mode == "none":
        return
    if abs(difference) > tolerance:
        # Beyond tolerance this is a mapping error, not rounding. Forcing it
        # balanced would bury the very thing the check exists to surface.
        _note(
            document, "jv.beyond_tolerance", "high",
            f"Voucher {voucher.number} is out by ₹{abs(difference):,.2f}, which is beyond "
            f"the ₹{tolerance:,.2f} tolerance. It has been left unbalanced rather than "
            "adjusted — a difference this size is a mapping problem, not rounding.",
            difference=difference, scope=voucher.scope,
        )
        return
    if mode == "account":
        if not account:
            _note(
                document, "jv.no_rounding_account", "medium",
                f"Voucher {voucher.number} is out by ₹{abs(difference):,.2f} but no rounding "
                "account is set, so nothing was posted.",
                difference=difference, scope=voucher.scope,
            )
            return
        voucher.lines.append(
            JvLine(
                account_code=str(account), account_name="Rounding",
                label="Rounding difference",
                side="credit" if difference > 0 else "debit",
                amount=abs(difference), cost_center=voucher.scope, measures=[],
            )
        )
    elif mode == "largest_line" and voucher.lines:
        target = max(voucher.lines, key=lambda line: line.amount)
        adjustment = difference if target.side == "credit" else -difference
        target.amount = _q(target.amount + adjustment)
        _note(
            document, "jv.rounding_absorbed", "low",
            f"Voucher {voucher.number}: ₹{abs(difference):,.2f} was absorbed into "
            f"'{target.label}' to force a balance.",
            difference=difference, scope=voucher.scope,
        )


def _check(document: JvDocument, rules: list[Any], tolerance: Decimal) -> None:
    """Everything the template gets wrong, said in rupees."""
    if abs(document.difference) > tolerance:
        _note(
            document, "jv.unbalanced", "high",
            f"The voucher does not balance: debits ₹{document.total_debit:,.2f} against "
            f"credits ₹{document.total_credit:,.2f}, a difference of "
            f"₹{abs(document.difference):,.2f}. A correct mapping balances by construction, "
            "so this is a measure posted on one side only.",
            expected=document.total_debit, actual=document.total_credit,
            difference=document.difference,
        )

    mapped: set[str] = set()
    for rule in rules:
        mapped |= expand_measures(list(_opt(rule, "measures", []) or []))
    unmapped = [
        key for key in MEASURE_KEYS
        if key not in mapped and document.cost_totals.get(key, Decimal("0")) != 0
    ]
    for key in unmapped:
        amount = document.cost_totals.get(key, Decimal("0"))
        _note(
            document, "jv.measure_unmapped", "high",
            f"{MEASURE_BY_KEY[key].label} (₹{amount:,.2f}) is not mapped to any account, "
            "so it is missing from the voucher entirely.",
            actual=amount, context={"measure": key},
        )

    ctc = document.cost_totals.get("ctc", Decimal("0"))
    if ctc and abs(document.total_debit - ctc) > tolerance:
        _note(
            document, "jv.debits_vs_cost", "high",
            f"Debits total ₹{document.total_debit:,.2f} against payroll cost of "
            f"₹{ctc:,.2f} for the month. The voucher and the cost dashboard will not "
            "agree until these match.",
            expected=ctc, actual=document.total_debit,
            difference=_q(document.total_debit - ctc),
        )

    unassigned = sum(
        (line.amount for v in document.vouchers for line in v.lines
         if line.cost_center == UNASSIGNED),
        Decimal("0"),
    )
    if unassigned:
        _note(
            document, "jv.unassigned_cost_centre", "low",
            f"₹{unassigned:,.2f} posts to '{UNASSIGNED}' because those employees carry no "
            "value for the grouping dimension. Fill it in on the employee master and "
            "re-upload the register to split it properly.",
            actual=unassigned, scope=UNASSIGNED,
        )


# ---------------------------------------------------------------------------
# Handing the voucher to an accounting system
# ---------------------------------------------------------------------------
# Each layout is shaped like the target system's import file. None of them is a
# specification: import formats are version- and tenant-specific, and several
# of these systems accept more than one. Run the first month's file through the
# target system's own import preview before trusting it.
_EXPORT_HEADERS: dict[str, tuple[str, ...]] = {
    "generic_csv": ("Voucher No", "Date", "Voucher Type", "Account Code", "Account Name",
                    "Cost Centre", "Debit", "Credit", "Narration"),
    "tally_csv": ("Date", "Voucher Type", "Voucher No", "Dr/Cr", "Ledger Name",
                  "Amount", "Cost Centre", "Narration"),
    "sap_csv": ("Posting Date", "Document Type", "Document Number", "GL Account",
                "Posting Key", "Amount", "Cost Center", "Item Text"),
    "zoho_csv": ("Journal Date", "Journal Number", "Account", "Description",
                 "Debit", "Credit", "Notes"),
}


def export_rows(document: JvDocument, fmt: str, sign_convention: str = "two_column") -> tuple[
    list[str], list[list[Any]]
]:
    """The voucher as a header and rows, in one accounting system's shape."""
    header = list(_EXPORT_HEADERS.get(fmt, _EXPORT_HEADERS["generic_csv"]))
    rows: list[list[Any]] = []

    for voucher in document.vouchers:
        for line in voucher.lines:
            debit, credit = float(line.debit), float(line.credit)
            if fmt == "tally_csv":
                rows.append([
                    voucher.voucher_date.strftime("%d-%m-%Y"), voucher.voucher_type,
                    voucher.number, "Dr" if line.side == "debit" else "Cr",
                    line.account_name or line.account_code, float(line.amount),
                    line.cost_center or "", voucher.narration,
                ])
            elif fmt == "sap_csv":
                rows.append([
                    voucher.voucher_date.strftime("%Y%m%d"), "SA", voucher.number,
                    line.account_code,
                    # S and H are SAP's debit and credit posting keys.
                    "S" if line.side == "debit" else "H",
                    float(line.amount), line.cost_center or "", line.label,
                ])
            elif fmt == "zoho_csv":
                rows.append([
                    voucher.voucher_date.isoformat(), voucher.number,
                    line.account_name or line.account_code, line.label,
                    debit, credit, voucher.narration,
                ])
            else:
                if sign_convention == "signed":
                    # One amount column, credits negative: what most ERP imports want.
                    amount = float(line.amount if line.side == "debit" else -line.amount)
                    row = [voucher.number, voucher.voucher_date.isoformat(),
                           voucher.voucher_type, line.account_code,
                           line.account_name or line.label, line.cost_center or "",
                           amount, "", voucher.narration]
                else:
                    row = [voucher.number, voucher.voucher_date.isoformat(),
                           voucher.voucher_type, line.account_code,
                           line.account_name or line.label, line.cost_center or "",
                           debit, credit, voucher.narration]
                rows.append(row)

    if fmt in ("generic_csv", None) and sign_convention == "signed":
        header = list(header)
        header[6:8] = ["Amount", ""]
    return header, rows


def export_csv(document: JvDocument, fmt: str, sign_convention: str = "two_column") -> str:
    import csv as _csv
    import io as _io

    header, rows = export_rows(document, fmt, sign_convention)
    buffer = _io.StringIO()
    writer = _csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue()
