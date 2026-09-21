"""
Holding the register, the bank and the ledger against each other.

Payroll produces three numbers a month and a payroll system has no independent
view of any of them:

* the **register** says what was due — net pay, employee by employee;
* the **bank file** says what was paid — an account number and an amount;
* the **journal voucher** says what was booked — cost, by account.

They should agree. When they do not, the difference is either an error someone
has to correct or money that went somewhere nobody intended, and there is no
third possibility. This module finds the differences and says which employee
and how many rupees, because a reconciliation that reports "does not match" and
stops is one nobody can act on.

What counts as a match
----------------------
Employee code, and only employee code. Not name — two people are routinely
called the same thing, and a payroll fraud that matters is one where the name
is right and the account is not. Not amount — matching on amount would pair an
employee with someone else's identical salary and report a clean run.

Codes are compared through the profile's own transform and upper-cased, so
``emp0042`` in the register meets ``EMP0042`` in the bank file. That is
normalisation, not fuzzy matching: nothing here guesses that two different
codes are the same person.

Severity
--------
High means money may have moved wrongly: an unexpected payee, an account that
is not the one on the master, a payment nobody was due. Medium means the
figures disagree and someone must explain it. Low means a detail worth
checking that does not by itself move money.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models import BankFile, BankFileRow, ReconException, ReconRun
from app.services.bank_file import match_key
from app.services.cost_model import with_derived

CENT = Decimal("0.01")
# A rupee either way on a per-employee net is rounding; more is a difference.
DEFAULT_TOLERANCE = Decimal("1.00")


def _q(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _dec(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


# ---------------------------------------------------------------------------
# What can go wrong, and what it means
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ExceptionKind:
    code: str
    label: str
    severity: str
    meaning: str
    action: str


EXCEPTION_KINDS: tuple[ExceptionKind, ...] = (
    # ---- bank ----------------------------------------------------------
    ExceptionKind(
        "bank.not_in_file", "Due but not paid", "high",
        "The register shows net pay due, and the bank file contains no payment to this employee.",
        "Confirm whether they were paid outside this file. If not, they have not been paid.",
    ),
    ExceptionKind(
        "bank.not_in_register", "Paid but not due", "high",
        "The bank file pays an employee code the register does not contain for this month.",
        "Establish who authorised this payment before the file is released.",
    ),
    ExceptionKind(
        "bank.amount_mismatch", "Paid a different amount", "high",
        "The amount paid is not the net pay the register stated.",
        "Identify the difference. A recovery or advance settled outside the register "
        "explains some of these; nothing explains the rest.",
    ),
    ExceptionKind(
        "bank.duplicate_payment", "Paid more than once", "high",
        "The same employee code appears on more than one line of the bank file.",
        "Unless the split is intentional, one of these is a double payment.",
    ),
    ExceptionKind(
        "bank.shared_account", "One account, several employees", "high",
        "Two or more employees are being paid into the same bank account.",
        "Occasionally genuine between family members. Usually it is not.",
    ),
    ExceptionKind(
        "bank.account_differs_from_master", "Account is not the one on file", "high",
        "The account in the bank file is not the account the employee master holds.",
        "The single most important line in this report. Verify the change was requested "
        "by the employee through a channel that is not email alone.",
    ),
    ExceptionKind(
        "bank.account_missing_on_master", "No account on the master", "low",
        "The employee master holds no bank account for this employee, so the account "
        "paid could not be checked.",
        "Complete the master so this employee is covered next month.",
    ),
    ExceptionKind(
        "bank.name_mismatch", "Beneficiary name differs", "low",
        "The beneficiary name on the payment is not the name in the register.",
        "Often a spelling or initials difference. Read it alongside the account check.",
    ),
    ExceptionKind(
        "bank.non_positive_amount", "Zero or negative payment", "medium",
        "A payment line carries an amount of zero or less.",
        "A bank will reject these. Establish why the line is in the file.",
    ),
    ExceptionKind(
        "bank.unidentified_row", "Payment with no employee code", "medium",
        "A payment line carries no employee code, so it cannot be matched to anyone.",
        "Map the employee code column, or establish who this payment is for.",
    ),
    ExceptionKind(
        "bank.returned", "Returned or rejected by the bank", "high",
        "The bank has marked this payment returned, rejected or failed.",
        "This employee has not been paid. Re-issue before month end.",
    ),
    ExceptionKind(
        "bank.total_mismatch", "File total is not the register total", "high",
        "The sum of the bank file does not equal net pay due for the month.",
        "Reconcile the line-level exceptions below; they add up to this difference.",
    ),
    ExceptionKind(
        "bank.stated_total_mismatch", "File disagrees with its own control total", "high",
        "The control total on the file's trailer is not the sum of the file's own lines.",
        "The file is truncated or has been edited since the bank produced it. Obtain a fresh copy.",
    ),
    # ---- the register's own arithmetic ---------------------------------
    ExceptionKind(
        "net.stated_vs_computed", "Stated net is not gross less deductions", "medium",
        "The net pay the register declares is not its own gross less its own deductions.",
        "Usually a deduction the register does not itemise — a loan instalment or salary "
        "advance. Confirm what it is; the amount is being paid out either way.",
    ),
    ExceptionKind(
        "net.no_stated_net", "Register states no net pay", "low",
        "The register carries no net pay column, so the bank file is being compared "
        "against net computed from the taxonomy.",
        "Include a net pay column in the register export for an exact comparison.",
    ),
    # ---- ledger ---------------------------------------------------------
    ExceptionKind(
        "jv.unbalanced", "Voucher does not balance", "high",
        "Debits and credits differ by more than the template's tolerance.",
        "A measure is posted on one side only. The unmapped-measure lines usually name it.",
    ),
    ExceptionKind(
        "jv.measure_unmapped", "Cost not mapped to any account", "high",
        "A component of payroll cost has no account in this template, so it is missing "
        "from the voucher.",
        "Add a rule for it, or confirm deliberately that it is posted elsewhere.",
    ),
    ExceptionKind(
        "jv.debits_vs_cost", "Voucher total is not payroll cost", "high",
        "The voucher's debits do not equal the month's payroll cost.",
        "The ledger and the cost dashboard will disagree until they match.",
    ),
    ExceptionKind(
        "jv.beyond_tolerance", "Difference beyond rounding", "high",
        "A voucher is out by more than the tolerance and was left unadjusted.",
        "Find the mapping error rather than raising the tolerance.",
    ),
    ExceptionKind(
        "jv.missing_account_code", "Rule has no account code", "medium",
        "A posting rule names no account, so the line cannot be imported.",
        "Fill in the account code from the chart of accounts.",
    ),
    ExceptionKind(
        "jv.unassigned_cost_centre", "Cost centre not assigned", "low",
        "Some cost posts to Unassigned because those employees carry no value for the "
        "grouping dimension.",
        "Complete the employee master and re-upload the register.",
    ),
    ExceptionKind(
        "jv.no_register", "No register for the month", "high",
        "There is no stored salary register to build a voucher from.",
        "Upload and validate the register first.",
    ),
    ExceptionKind(
        "jv.no_rules", "Template has no rules", "high",
        "The template contains no active posting rules.",
        "Add rules, or start from one of the supplied templates.",
    ),
    ExceptionKind(
        "jv.rule_maps_nothing", "Rule maps no measures", "medium",
        "A posting rule names no cost measures, so it posts nothing.",
        "Map the measures this account should carry, or remove the rule.",
    ),
    ExceptionKind(
        "jv.no_rounding_account", "No rounding account set", "medium",
        "The template rounds to an account but none is named.",
        "Name the account, or switch the rounding mode to reporting the difference.",
    ),
    ExceptionKind(
        "jv.rounding_absorbed", "Rounding absorbed into a line", "low",
        "A difference was forced into the largest line to make the voucher balance.",
        "Check the amount is rounding and not a mapping error.",
    ),
)

KIND_BY_CODE = {k.code: k for k in EXCEPTION_KINDS}
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def exception_catalogue() -> list[dict[str, str]]:
    return [
        {"code": k.code, "label": k.label, "severity": k.severity,
         "meaning": k.meaning, "action": k.action}
        for k in EXCEPTION_KINDS
    ]


@dataclass
class ReconItem:
    """One thing that did not reconcile."""

    code: str
    title: str
    severity: str = "medium"
    detail: str | None = None
    employee_id: str | None = None
    employee_name: str | None = None
    scope: str | None = None
    expected: Decimal | None = None
    actual: Decimal | None = None
    difference: Decimal | None = None
    context: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        kind = KIND_BY_CODE.get(self.code)
        return {
            "code": self.code,
            "label": kind.label if kind else self.code,
            "severity": self.severity,
            "title": self.title,
            "detail": self.detail,
            "meaning": kind.meaning if kind else None,
            "action": kind.action if kind else None,
            "employee_id": self.employee_id,
            "employee_name": self.employee_name,
            "scope": self.scope,
            "expected": None if self.expected is None else float(self.expected),
            "actual": None if self.actual is None else float(self.actual),
            "difference": None if self.difference is None else float(self.difference),
            "context": dict(self.context),
        }


def _flag(
    out: list[ReconItem],
    code: str,
    title: str,
    **kwargs: Any,
) -> None:
    kind = KIND_BY_CODE.get(code)
    kwargs.setdefault("severity", kind.severity if kind else "medium")
    out.append(ReconItem(code=code, title=title, **kwargs))


# ---------------------------------------------------------------------------
# What the register says is due
# ---------------------------------------------------------------------------
@dataclass
class RegisterNet:
    employee_id: str
    employee_name: str | None
    computed_net: Decimal
    stated_net: Decimal | None
    dimensions: dict[str, Any]

    @property
    def expected(self) -> Decimal:
        """
        What the bank should have paid.

        The register's own stated net where it has one: that is the figure the
        payroll system instructed the bank with, and reconciling the bank file
        against anything else would report a difference the client cannot act
        on. Where the register states none, the taxonomy's net stands in, and
        the reconciliation says so rather than implying an exact comparison.
        """
        return self.stated_net if self.stated_net is not None else self.computed_net


def register_net(db: Session, entity_id: uuid.UUID, period_month: date) -> list[RegisterNet]:
    """Net pay per employee for one month, from the stored register."""
    from app.services.analytics import _Costing, _register_rows

    period = period_month.replace(day=1)
    rows, _ = _register_rows(db, entity_id, period, period)
    if not rows:
        return []

    costing = _Costing(db, entity_id)
    out: list[RegisterNet] = []
    for row in rows:
        values = with_derived(costing.cost(row).measures)
        stated = getattr(row, "net_pay", None)
        out.append(
            RegisterNet(
                employee_id=str(row.employee_id),
                employee_name=row.employee_name,
                computed_net=_q(values.get("net", Decimal("0"))),
                stated_net=None if stated is None else _q(_dec(stated)),
                dimensions=row.dimensions or {},
            )
        )
    return out


# ---------------------------------------------------------------------------
# Bank reconciliation
# ---------------------------------------------------------------------------
_RETURNED_WORDS = ("reject", "return", "fail", "unsuccessful", "bounce", "declin")


def _looks_returned(status: str | None) -> bool:
    text = (status or "").strip().lower()
    return bool(text) and any(word in text for word in _RETURNED_WORDS)


def _same_account(left: str | None, right: str | None) -> bool:
    """
    Two account numbers, compared the way a bank would.

    Leading zeros and separators differ between a master and a bank file for
    the same account, so both sides are reduced to their digits. Where that
    leaves nothing on either side, the comparison is refused rather than
    reported as a match.
    """
    def digits(value: str | None) -> str:
        return "".join(c for c in str(value or "") if c.isdigit())

    a, b = digits(left), digits(right)
    if not a or not b:
        return True
    return a.lstrip("0") == b.lstrip("0")


def _name_matches(left: str | None, right: str | None) -> bool:
    def key(value: str | None) -> str:
        return "".join(c for c in str(value or "").lower() if c.isalnum())

    a, b = key(left), key(right)
    if not a or not b:
        return True
    # One containing the other covers initials, middle names and the order a
    # bank writes them in. A shared prefix alone is not enough.
    return a == b or a in b or b in a


def bank_reconciliation(
    db: Session,
    entity_id: uuid.UUID,
    period_month: date,
    bank_file: BankFile,
    *,
    tolerance: Decimal = DEFAULT_TOLERANCE,
    id_transform: str = "trim",
) -> dict[str, Any]:
    """
    The bank file against the register, line by line.

    Returns both the summary a reviewer reads first and every exception behind
    it, so the headline difference can always be traced to the employees that
    make it up.
    """
    period = period_month.replace(day=1)
    exceptions: list[ReconItem] = []

    register = register_net(db, entity_id, period)
    by_key: dict[str, RegisterNet] = {}
    for entry in register:
        key = match_key(entry.employee_id, id_transform)
        if key:
            by_key[key] = entry

    rows = (
        db.query(BankFileRow)
        .filter(BankFileRow.file_id == bank_file.id)
        .order_by(BankFileRow.row_number)
        .all()
    )

    master = _master_accounts(db, entity_id, period)

    matched_keys: set[str] = set()
    seen_keys: dict[str, int] = {}
    by_account: dict[str, set[str]] = {}
    paid_total = Decimal("0")
    matched_total = Decimal("0")

    for row in rows:
        amount = _q(_dec(row.amount))
        paid_total += amount
        key = match_key(row.employee_id, id_transform)

        if _looks_returned(row.status):
            _flag(
                exceptions, "bank.returned",
                f"Payment to {row.employee_id or 'an unidentified line'} was "
                f"{(row.status or 'returned').strip()}.",
                employee_id=row.employee_id, employee_name=row.employee_name,
                actual=amount, context={"status": row.status, "row": row.row_number},
            )

        if amount <= 0:
            _flag(
                exceptions, "bank.non_positive_amount",
                f"Row {row.row_number} carries an amount of ₹{amount:,.2f}.",
                employee_id=row.employee_id, employee_name=row.employee_name,
                actual=amount, context={"row": row.row_number},
            )

        if not key:
            _flag(
                exceptions, "bank.unidentified_row",
                f"Row {row.row_number} pays ₹{amount:,.2f} with no employee code.",
                actual=amount,
                context={"row": row.row_number, "account": row.account_number},
            )
            continue

        seen_keys[key] = seen_keys.get(key, 0) + 1
        if row.account_number:
            by_account.setdefault(
                "".join(c for c in row.account_number if c.isdigit()) or row.account_number,
                set(),
            ).add(key)

        entry = by_key.get(key)
        if entry is None:
            _flag(
                exceptions, "bank.not_in_register",
                f"₹{amount:,.2f} is being paid to employee code {row.employee_id}, which "
                f"is not in the {period.strftime('%B %Y')} register.",
                employee_id=row.employee_id, employee_name=row.employee_name,
                actual=amount,
                context={"row": row.row_number, "account": row.account_number},
            )
            continue

        matched_keys.add(key)
        matched_total += amount
        expected = entry.expected
        difference = _q(amount - expected)
        if abs(difference) > tolerance:
            _flag(
                exceptions, "bank.amount_mismatch",
                f"{entry.employee_name or entry.employee_id} is due ₹{expected:,.2f} "
                f"and is being paid ₹{amount:,.2f}.",
                detail=f"A difference of ₹{difference:,.2f}.",
                employee_id=entry.employee_id, employee_name=entry.employee_name,
                expected=expected, actual=amount, difference=difference,
                context={"row": row.row_number,
                         "basis": "stated" if entry.stated_net is not None else "computed"},
            )

        account_on_master = master.get(key, {}).get("bank_account")
        if not account_on_master:
            _flag(
                exceptions, "bank.account_missing_on_master",
                f"No bank account is held on the master for "
                f"{entry.employee_name or entry.employee_id}, so the account paid was "
                "not checked.",
                employee_id=entry.employee_id, employee_name=entry.employee_name,
                context={"paid_to": row.account_number},
            )
        elif row.account_number and not _same_account(account_on_master, row.account_number):
            _flag(
                exceptions, "bank.account_differs_from_master",
                f"₹{amount:,.2f} for {entry.employee_name or entry.employee_id} is going "
                "to an account that is not the one on the employee master.",
                employee_id=entry.employee_id, employee_name=entry.employee_name,
                actual=amount,
                context={"paid_to": row.account_number, "on_master": account_on_master,
                         "row": row.row_number},
            )

        if row.employee_name and not _name_matches(entry.employee_name, row.employee_name):
            _flag(
                exceptions, "bank.name_mismatch",
                f"The payment for {entry.employee_id} names "
                f"'{row.employee_name}' where the register says "
                f"'{entry.employee_name or 'no name'}'.",
                employee_id=entry.employee_id, employee_name=entry.employee_name,
                context={"in_file": row.employee_name, "in_register": entry.employee_name},
            )

    for key, count in seen_keys.items():
        if count > 1:
            entry = by_key.get(key)
            _flag(
                exceptions, "bank.duplicate_payment",
                f"Employee code {entry.employee_id if entry else key} appears on {count} "
                "lines of this file.",
                employee_id=entry.employee_id if entry else key,
                employee_name=entry.employee_name if entry else None,
                context={"lines": count},
            )

    for account, keys in by_account.items():
        if len(keys) > 1:
            names = sorted(
                (by_key[k].employee_name or by_key[k].employee_id) for k in keys if k in by_key
            )
            _flag(
                exceptions, "bank.shared_account",
                f"Account ending {account[-4:] if len(account) > 4 else account} is being "
                f"paid for {len(keys)} employees.",
                detail=", ".join(names) if names else None,
                context={"employees": sorted(keys)},
            )

    due_total = Decimal("0")
    for entry in register:
        due_total += entry.expected
        key = match_key(entry.employee_id, id_transform)
        if key and key not in matched_keys and entry.expected != 0:
            _flag(
                exceptions, "bank.not_in_file",
                f"{entry.employee_name or entry.employee_id} is due ₹{entry.expected:,.2f} "
                "and has no payment in this file.",
                employee_id=entry.employee_id, employee_name=entry.employee_name,
                expected=entry.expected, actual=Decimal("0"),
                difference=_q(-entry.expected),
            )

    stated_missing = sum(1 for e in register if e.stated_net is None)
    if register and stated_missing == len(register):
        _flag(
            exceptions, "net.no_stated_net",
            "The register carries no net pay column, so payments are compared against "
            "net computed from the cost taxonomy.",
            context={"employees": len(register)},
        )
    else:
        for entry in register:
            if entry.stated_net is None:
                continue
            difference = _q(entry.stated_net - entry.computed_net)
            if abs(difference) > tolerance:
                _flag(
                    exceptions, "net.stated_vs_computed",
                    f"{entry.employee_name or entry.employee_id}: the register states net "
                    f"₹{entry.stated_net:,.2f} where gross less deductions is "
                    f"₹{entry.computed_net:,.2f}.",
                    employee_id=entry.employee_id, employee_name=entry.employee_name,
                    expected=entry.computed_net, actual=entry.stated_net,
                    difference=difference,
                )

    paid_total = _q(paid_total)
    due_total = _q(due_total)
    total_difference = _q(paid_total - due_total)
    if abs(total_difference) > tolerance:
        _flag(
            exceptions, "bank.total_mismatch",
            f"The file pays ₹{paid_total:,.2f} against ₹{due_total:,.2f} of net pay due "
            f"for {period.strftime('%B %Y')}.",
            detail=f"A difference of ₹{total_difference:,.2f}.",
            expected=due_total, actual=paid_total, difference=total_difference,
        )

    stated = bank_file.stated_total
    if stated is not None and abs(_q(_dec(stated)) - paid_total) > tolerance:
        _flag(
            exceptions, "bank.stated_total_mismatch",
            f"The file's own control total is ₹{_dec(stated):,.2f} but its lines add up "
            f"to ₹{paid_total:,.2f}.",
            expected=_q(_dec(stated)), actual=paid_total,
            difference=_q(paid_total - _dec(stated)),
        )

    exceptions.sort(
        key=lambda e: (SEVERITY_ORDER.get(e.severity, 3), e.code, e.employee_id or "")
    )

    return {
        "period": period.isoformat(),
        "period_label": period.strftime("%b %Y"),
        "file": {
            "id": str(bank_file.id), "filename": bank_file.filename,
            "kind": bank_file.kind, "row_count": len(rows),
            "total": float(paid_total),
            "stated_total": None if stated is None else float(_dec(stated)),
        },
        "summary": {
            "register_employees": len(register),
            "bank_rows": len(rows),
            "matched": len(matched_keys),
            "unmatched_in_register": len([
                e for e in register
                if (match_key(e.employee_id, id_transform) or "") not in matched_keys
                and e.expected != 0
            ]),
            "unmatched_in_file": len([
                r for r in rows
                if (match_key(r.employee_id, id_transform) or "") not in by_key
            ]),
            "due_total": float(due_total),
            "paid_total": float(paid_total),
            "matched_total": float(_q(matched_total)),
            "difference": float(total_difference),
            "reconciled": abs(total_difference) <= tolerance and not any(
                e.severity == "high" for e in exceptions
            ),
            "tolerance": float(tolerance),
        },
        "counts": _counts(exceptions),
        "exceptions": [e.as_dict() for e in exceptions],
    }


def _master_accounts(
    db: Session, entity_id: uuid.UUID, period: date
) -> dict[str, dict[str, Any]]:
    """
    Bank details from the employee master as it stood at this period.

    As at the period, not as at today: an account changed in September must not
    make June's payment look correct in hindsight.
    """
    from app.services.workforce import master_as_of

    out: dict[str, dict[str, Any]] = {}
    for employee_id, record in (master_as_of(db, entity_id, period) or {}).items():
        key = match_key(employee_id, "trim")
        if not key:
            continue
        out[key] = {
            "bank_account": getattr(record, "bank_account", None),
            "ifsc": getattr(record, "ifsc", None),
            "employee_name": getattr(record, "employee_name", None),
        }
    return out


def _counts(exceptions: list[ReconItem]) -> dict[str, Any]:
    by_severity: dict[str, int] = {"high": 0, "medium": 0, "low": 0}
    by_code: dict[str, int] = {}
    for item in exceptions:
        by_severity[item.severity] = by_severity.get(item.severity, 0) + 1
        by_code[item.code] = by_code.get(item.code, 0) + 1
    return {"total": len(exceptions), "by_severity": by_severity, "by_code": by_code}


# ---------------------------------------------------------------------------
# Ledger reconciliation
# ---------------------------------------------------------------------------
def jv_reconciliation(
    db: Session,
    entity_id: uuid.UUID,
    period_month: date,
    template: Any,
    *,
    rules: list[Any] | None = None,
) -> dict[str, Any]:
    """
    The voucher this template produces, and everything wrong with it.

    The voucher is built from the same costing pass as the cost dashboard, so
    "the ledger does not agree with the dashboard" is always a mapping problem
    and never a data one — which is what makes it worth reporting in rupees.
    """
    from app.services.jv_builder import build_jv

    document = build_jv(db, entity_id, period_month.replace(day=1), template, rules=rules)

    exceptions: list[ReconItem] = []
    for issue in document.issues:
        code = issue["code"]
        kind = KIND_BY_CODE.get(code)
        exceptions.append(
            ReconItem(
                code=code,
                title=issue["title"],
                severity=issue.get("severity") or (kind.severity if kind else "medium"),
                detail=issue.get("detail"),
                scope=issue.get("scope"),
                expected=None if issue.get("expected") is None else Decimal(str(issue["expected"])),
                actual=None if issue.get("actual") is None else Decimal(str(issue["actual"])),
                difference=(
                    None if issue.get("difference") is None
                    else Decimal(str(issue["difference"]))
                ),
                context=issue.get("context") or {},
            )
        )
    exceptions.sort(key=lambda e: (SEVERITY_ORDER.get(e.severity, 3), e.code))

    payload = document.as_dict()
    payload["counts"] = _counts(exceptions)
    payload["exceptions"] = [e.as_dict() for e in exceptions]
    payload["summary"] = {
        "vouchers": len(document.vouchers),
        "lines": sum(len(v.lines) for v in document.vouchers),
        "total_debit": float(document.total_debit),
        "total_credit": float(document.total_credit),
        "difference": float(document.difference),
        "payroll_cost": float(document.cost_totals.get("ctc", Decimal("0"))),
        "employee_count": document.employee_count,
        "reconciled": not any(e.severity == "high" for e in exceptions),
    }
    return payload


# ---------------------------------------------------------------------------
# Keeping the result
# ---------------------------------------------------------------------------
def save_run(
    db: Session,
    entity_id: uuid.UUID,
    period_month: date,
    *,
    kind: str,
    result: dict[str, Any],
    user: Any,
    bank_file_id: uuid.UUID | None = None,
    jv_template_id: uuid.UUID | None = None,
) -> ReconRun:
    """
    Store a reconciliation and its exceptions.

    Stored rather than recomputed on demand because a reconciliation is
    evidence: the register, the bank file or the template can all change
    afterwards, and "what did it say when it was signed off" has to survive
    that. Nothing here is updated in place.
    """
    run = ReconRun(
        entity_id=entity_id,
        period_month=period_month.replace(day=1),
        kind=kind,
        bank_file_id=bank_file_id,
        jv_template_id=jv_template_id,
        state="open",
        summary={
            "summary": result.get("summary", {}),
            "counts": result.get("counts", {}),
            "file": result.get("file"),
            "options": result.get("options"),
        },
        created_by_user_id=getattr(user, "id", None),
        created_by_email=getattr(user, "email", None),
    )
    db.add(run)
    db.flush()

    for item in result.get("exceptions", []):
        db.add(
            ReconException(
                run_id=run.id,
                entity_id=entity_id,
                code=item["code"],
                severity=item.get("severity") or "medium",
                title=item["title"][:255],
                detail=item.get("detail"),
                employee_id=item.get("employee_id"),
                employee_name=item.get("employee_name"),
                scope=item.get("scope"),
                expected=None if item.get("expected") is None else Decimal(str(item["expected"])),
                actual=None if item.get("actual") is None else Decimal(str(item["actual"])),
                difference=(
                    None if item.get("difference") is None
                    else Decimal(str(item["difference"]))
                ),
                context=item.get("context") or {},
            )
        )
    return run
