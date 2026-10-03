"""
The disbursement checks, the bridge, and the verdict.

Order matters, and it is the design:

1. **Row checks** decide which employees come out of the file (HOLD_ROW), which
   are paid with a note (FLAG), and which make the whole file unsafe (any check
   a company has set to STOP_FILE).
2. **File checks** (DSB-01, DSB-02, DSB-04) then judge what is left. They do not
   re-count the row problems: a duplicate row or a wrong amount is already held,
   and stopping the whole file for it would punish every other employee for one
   bad line. A file check stops the file when the file disagrees with *itself*
   (its own control total or count), when the clean file would not reconcile to
   the register for the people it pays, when nothing would be left to pay, or
   when so much is held that the file is more likely the wrong file than a file
   with a few wrong lines (``max_hold_share_pct``).
3. **The bridge** walks from the register's total due to the file's total, one
   named line at a time, so the approver sees where every rupee of difference
   went: who is missing, who was paid but not due, duplicates, amount
   differences. It is arithmetic, not a check, and is shown as such.

What the bank should pay
------------------------
Not net pay. After net pay come reimbursements (paid with salary, outside it)
and salary held this period (withheld, paid later), and later still the held
salary released. The amount a payment line must equal is the **total salary
payable**: the register's own figure when it gives one; otherwise net pay plus
reimbursements and released holds, less salary held, from whichever of those
columns the register has; otherwise net pay, and the checks say so, because
reimbursements and holds then cannot be allowed for.

A check whose input was not supplied reports NOT_RUN with the reason. A check a
company switched off reports DISABLED. Neither is ever reported as passed.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.services.disbursement import values
from app.services.disbursement.config import (
    CLEAR, DISABLED, DO_NOT_RELEASE, FLAG, HOLD_ROW, NOT_APPLICABLE, NOT_RUN, RAN, RULES,
    STOP_FILE, WITH_HOLDS, Settings,
)
from app.services.disbursement.model import BankRow, Finding, Inputs, Note, RegisterRow, RuleResult

ZERO = Decimal("0")
CENT = Decimal("0.01")

_HOLD_WORDS = ("hold",)
_FF_WORDS = ("f&f", "fnf", "f & f", "full and final", "full & final", "settled")
_SEPARATED = {"separated", "resigned", "terminated", "exited", "inactive", "left", "absconding",
              "retired", "deceased", "relieved", "exit", "separation"}


def _money(value: Decimal | None) -> str:
    return "" if value is None else f"{value.quantize(CENT):,.2f}"


def status_kind(status: str | None) -> str | None:
    if not status:
        return None
    s = status.strip().lower()
    if any(w in s for w in _FF_WORDS):
        return "ff"
    if any(w in s for w in _HOLD_WORDS):
        return "hold"
    if s in _SEPARATED or any(s.startswith(w) for w in ("separat", "resign", "terminat")):
        return "separated"
    return "active"


@dataclass
class Result:
    verdict: str
    findings: list[Finding]
    rules: list[RuleResult]
    held_lines: set[int]
    kept_lines: set[int]
    totals: dict[str, Any]
    bridge: list[dict[str, Any]]
    notes: list[Note] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "totals": {k: (str(v) if isinstance(v, Decimal) else v) for k, v in self.totals.items()},
            "bridge": [{**b, "amount": str(b["amount"]) if b.get("amount") is not None else None}
                       for b in self.bridge],
            "rules": [r.as_dict() for r in self.rules],
            "not_run": [r.as_dict() for r in self.rules if r.status == NOT_RUN],
        }


class _Run:
    def __init__(self, inputs: Inputs, settings: Settings):
        if inputs.bank_file is None:
            raise ValueError("A bank payment file is required.")
        if inputs.register is None:
            raise ValueError("The current period's payroll register is required: without it no "
                             "payment can be confirmed as due.")
        self.inp, self.s = inputs, settings
        self.bank = inputs.bank_file
        self.findings: list[Finding] = []
        self.notes: list[Note] = list(inputs.notes)
        self.rules: dict[str, RuleResult] = {
            r.rule_id: RuleResult(r.rule_id, r.title, settings.severity(r.rule_id),
                                  RAN if settings.is_enabled(r.rule_id) else DISABLED,
                                  "" if settings.is_enabled(r.rule_id) else "Switched off in this company's settings.")
            for r in RULES
        }
        self._index()

    # -- inputs -----------------------------------------------------------
    def _payable(self, row: RegisterRow) -> Decimal | None:
        if self.basis == "total":
            return row.total_payable
        if row.net_pay is None:
            return None
        if self.basis == "computed":
            return row.net_pay + (row.reimbursement or ZERO) + (row.hold_release or ZERO) - (row.salary_hold or ZERO)
        return row.net_pay

    def _index(self) -> None:
        cols = self.inp.register.columns
        self.adjustments = cols & {"reimbursement", "salary_hold", "hold_release"}
        if "total_payable" in cols:
            self.basis = "total"
            self.basis_text = "total salary payable in the register"
        elif self.adjustments and "net_pay" in cols:
            self.basis = "computed"
            self.basis_text = "net pay plus reimbursements and released holds, less salary held"
        else:
            self.basis = "net"
            self.basis_text = "net pay"
        reg: dict[str, RegisterRow] = {}
        self.reg_net: dict[str, Decimal | None] = {}
        self.reg_pay: dict[str, Decimal | None] = {}
        counts: dict[str, int] = defaultdict(int)

        def add(store: dict[str, Decimal | None], key: str, value: Decimal | None, first: bool) -> None:
            if first:
                store[key] = value
            elif value is not None and store.get(key) is not None:
                store[key] = store[key] + value
            else:
                store[key] = None

        for row in self.inp.register.rows:
            counts[row.key] += 1
            first = row.key not in reg
            if first:
                reg[row.key] = row
            add(self.reg_net, row.key, row.net_pay, first)
            add(self.reg_pay, row.key, self._payable(row), first)
        for key, n in counts.items():
            if n > 1:
                self.notes.append(Note("register", f"appears {n} times in the register; pay is the sum "
                                       "of its rows", employee_id=reg[key].employee_id))
        self.reg = reg
        self.master = self._first(self.inp.bank_master, "bank master")
        self.previous = self._first(self.inp.previous, "previous period")
        self.holds: dict[str, list[Any]] = defaultdict(list)
        for row in (self.inp.hold_list.rows if self.inp.hold_list else []):
            self.holds[row.key].append(row)
        self.changes: dict[str, list[Any]] = defaultdict(list)
        for row in (self.inp.change_log.rows if self.inp.change_log else []):
            self.changes[row.key].append(row)
        self.offcycle: dict[str, list[Any]] = defaultdict(list)
        outside = 0
        for row in (self.inp.offcycle.rows if self.inp.offcycle else []):
            if row.payment_date and not (self.s.period_start <= row.payment_date <= self.s.period_end):
                outside += 1
                continue
            self.offcycle[row.key].append(row)
        if outside:
            self.notes.append(Note("off-cycle payments", f"{outside} off-cycle payment(s) dated outside "
                                   f"{self.s.period_start:%b %Y} were not counted against this period"))
        self.rows_by_key: dict[str, list[BankRow]] = defaultdict(list)
        for row in self.bank.rows:
            if row.key:
                self.rows_by_key[row.key].append(row)
        self.line_of = {r.row: r.line for r in self.bank.rows}
        self.key_of = {r.row: r.key for r in self.bank.rows}
        self._due: dict[str, Decimal] | None = None

    def _first(self, table, label: str) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if table is None:
            return out
        for row in table.rows:
            if row.key in out:
                self.notes.append(Note(label, "appears more than once; the first row is used",
                                       row=row.row, employee_id=row.employee_id))
                continue
            out[row.key] = row
        return out

    def _parts(self, key: str, total: bool = True) -> str:
        """' (net 40,000.00 + reimbursements 2,500.00 − held 5,000.00)' — how a payable figure is made up."""
        r = self.reg.get(key)
        if r is None or (total and self.basis == "net") or r.net_pay is None:
            return ""
        bits = [f"net {_money(r.net_pay)}"]
        if r.reimbursement:
            bits.append(f"+ reimbursements {_money(r.reimbursement)}")
        if r.hold_release:
            bits.append(f"+ released hold {_money(r.hold_release)}")
        if r.salary_hold:
            bits.append(f"− held {_money(r.salary_hold)}")
        return f" ({' '.join(bits)})" if len(bits) > 1 or not total else ""

    def _lines(self, key: str) -> list[int]:
        """The payment lines for an employee: what a hold on them removes."""
        return [r.row for r in self.rows_by_key.get(key, [])]

    def _paid(self, key: str) -> Decimal:
        return sum((r.amount or ZERO for r in self.rows_by_key.get(key, [])), ZERO)

    def _name(self, key: str | None) -> str | None:
        r = self.reg.get(key) if key else None
        return r.employee_name if r else None

    # -- bookkeeping --------------------------------------------------------
    def active(self, rule_id: str) -> bool:
        return self.rules[rule_id].status == RAN

    def not_run(self, rule_id: str, reason: str, status: str = NOT_RUN) -> None:
        if self.rules[rule_id].status == DISABLED:
            return
        self.rules[rule_id].status = status
        self.rules[rule_id].reason = reason

    def emit(self, rule_id: str, reason: str, key: str | None = None, **kw: Any) -> None:
        employee_id = kw.pop("employee_id", None)
        if employee_id is None and key:
            r = self.reg.get(key) or self.master.get(key)
            employee_id = r.employee_id if r else key
        self.findings.append(Finding(rule_id, self.s.severity(rule_id), reason, employee_id=employee_id,
                                     employee_name=kw.pop("employee_name", None) or self._name(key), **kw))
        self.rules[rule_id].findings += 1

    # -- who is expected to be paid ------------------------------------------
    def status_columns(self) -> bool:
        cols = self.inp.register.columns
        return bool(cols & {"status", "date_of_exit", "ff_processed", "on_hold"})

    def exclusion(self, key: str) -> str | None:
        """Why this employee is not expected in the file, or None."""
        for h in self.holds.get(key, []):
            what = (h.category or "on the hold list").strip()
            return f"on the hold list ({what}{': ' + h.reason if h.reason else ''})"
        r = self.reg.get(key)
        if r is None:
            return None
        kind = status_kind(r.status)
        if r.on_hold or kind == "hold":
            return "on hold in the register"
        if r.ff_processed or kind == "ff":
            return "full and final settlement already processed"
        if r.date_of_exit and r.date_of_exit < self.s.period_start:
            return f"separated on {r.date_of_exit:%d %b %Y}, before the period began"
        if kind == "separated" and r.date_of_exit is None:
            return f"status is '{r.status}' and no exit date is given"
        return None

    def due(self) -> dict[str, Decimal]:
        """
        Who the file should pay, and how much: a positive total payable, not
        excluded, not already paid off-cycle. Salary held in full leaves nothing
        payable, so that employee is not expected in the file.
        """
        if self._due is None:
            self._due = {}
            for key in self.reg:
                pay = self.reg_pay.get(key)
                if pay is not None and pay > 0 and not self.exclusion(key) and key not in self.offcycle:
                    self._due[key] = pay
        return self._due

    # -- the checks ------------------------------------------------------------
    def row_checks(self) -> None:
        s, bank = self.s, self.bank
        cols = bank.columns
        dup_keys = {k for k, rows in self.rows_by_key.items() if len(rows) > 1}

        if self.active("DSB-03"):
            for row in bank.rows:
                if row.key is None:
                    self.emit("DSB-03", "the payment line has no employee code, so it cannot be matched to "
                              "anyone in the register", field="employee_id", actual="(blank)",
                              rows=[row.row], amount=row.amount, employee_name=row.beneficiary_name)
                elif row.key not in self.reg:
                    self.emit("DSB-03", f"{row.employee_id} is paid {_money(row.amount)} but is not in this "
                              "period's register", key=row.key, field="employee_id", expected="in the register",
                              actual=row.employee_id, rows=[row.row], amount=row.amount,
                              employee_id=row.employee_id, employee_name=row.beneficiary_name)

        if self.active("DSB-10"):
            for key in sorted(dup_keys):
                rows = self.rows_by_key[key]
                amounts = ", ".join(_money(r.amount) for r in rows)
                self.emit("DSB-10", f"appears {len(rows)} times in the file ({amounts}); every line is held "
                          "until it is clear which, if any, is right", key=key, field="employee_id",
                          expected="1 line", actual=f"{len(rows)} lines", rows=[r.row for r in rows],
                          amount=sum((r.amount or ZERO) for r in rows))

        if self.active("DSB-07"):
            for row in bank.rows:
                if row.amount is None:
                    self.emit("DSB-07", f"the amount '{row.amount_raw or ''}' cannot be read as a number",
                              key=row.key, field="amount", expected="a positive amount",
                              actual=row.amount_raw or "(blank)", rows=[row.row], employee_id=row.employee_id)
                elif row.amount <= 0:
                    self.emit("DSB-07", f"the amount is {_money(row.amount)}; a salary payment must be positive",
                              key=row.key, field="amount", expected="more than 0.00",
                              actual=_money(row.amount), rows=[row.row], amount=row.amount,
                              employee_id=row.employee_id)

        if self.active("DSB-08"):
            if self.basis == "net":
                self.rules["DSB-08"].reason = ("Compared with net pay: the register has no total salary, "
                                               "reimbursement or salary hold column, so those cannot be allowed for.")
            elif self.basis == "computed":
                self.rules["DSB-08"].reason = ("The register has no total salary column; the amount due was taken "
                                               f"as {self.basis_text}.")
            for key, rows in self.rows_by_key.items():
                if key in dup_keys or key not in self.reg:
                    continue
                row = rows[0]
                if row.amount is None or row.amount <= 0:
                    continue                      # DSB-07 already holds it
                pay = self.reg_pay.get(key)
                if pay is None:
                    r = self.reg[key]
                    raw = r.total_raw if self.basis == "total" else r.net_raw
                    what = "total salary" if self.basis == "total" else "net pay"
                    self.emit("DSB-08", f"the register's {what} for this employee is blank or unreadable"
                              f"{' (' + repr(raw) + ')' if raw else ''}, so the amount cannot be confirmed",
                              key=key, field="amount", expected="(missing in register)",
                              actual=_money(row.amount), rows=[row.row], amount=row.amount)
                elif abs(row.amount - pay) > s.amount_tolerance:
                    self.emit("DSB-08", f"the file pays {_money(row.amount)} but the {self.basis_text} is "
                              f"{_money(pay)}{self._parts(key)} (difference {_money(row.amount - pay)})",
                              key=key, field="amount", expected=_money(pay), actual=_money(row.amount),
                              rows=[row.row], amount=row.amount)

        if self.active("DSB-17"):
            reg_cols = self.inp.register.columns
            if "total_payable" not in reg_cols:
                self.not_run("DSB-17", "The register has no total salary column, so there is no stated total to "
                             "check against its parts.")
            elif "net_pay" not in reg_cols:
                self.not_run("DSB-17", "The register has no net pay column to build the total from.")
            elif not self.adjustments:
                self.not_run("DSB-17", "The register gives total salary but no reimbursement, salary hold or hold "
                             "release column, so a difference from net pay cannot be explained or checked.")
            else:
                for key in self.rows_by_key:
                    r = self.reg.get(key)
                    if r is None or r.total_payable is None or r.net_pay is None:
                        continue
                    built = r.net_pay + (r.reimbursement or ZERO) + (r.hold_release or ZERO) - (r.salary_hold or ZERO)
                    if abs(r.total_payable - built) > s.amount_tolerance:
                        self.emit("DSB-17", f"total salary is {_money(r.total_payable)} but its parts make "
                                  f"{_money(built)}{self._parts(key, total=False)} (difference "
                                  f"{_money(r.total_payable - built)}); the bank pays the total, so check it",
                                  key=key, field="total_payable", expected=_money(built),
                                  actual=_money(r.total_payable), rows=self._lines(key), amount=self._paid(key))

        if self.active("DSB-05"):
            by_account: dict[str, set[str]] = defaultdict(set)
            for row in bank.rows:
                if row.key and row.account_number:
                    by_account[row.account_number].add(row.key)
            for number, keys in sorted(by_account.items()):
                if len(keys) < 2:
                    continue
                for key in sorted(keys):
                    others = ", ".join(self.rows_by_key[k][0].employee_id or k for k in sorted(keys) if k != key)
                    rows = self.rows_by_key[key]
                    self.emit("DSB-05", f"account {number} is also paid to {others}; every employee on it is "
                              "held", key=key, field="account_number", expected="an account of their own",
                              actual=number, rows=[r.row for r in rows], amount=sum((r.amount or ZERO) for r in rows))

        if self.active("DSB-12"):
            for row in bank.rows:
                problem = values.ifsc_problem(row.ifsc)
                if problem:
                    self.emit("DSB-12", problem, key=row.key, field="ifsc", expected="e.g. ABCD0123456",
                              actual=row.ifsc or "(blank)", rows=[row.row], amount=row.amount,
                              employee_id=row.employee_id)
                problem = values.account_problem(row.account_number, s.account_length_min, s.account_length_max)
                if problem:
                    self.emit("DSB-12", problem, key=row.key, field="account_number",
                              expected=f"{s.account_length_min}-{s.account_length_max} digits",
                              actual=row.account_number or "(blank)", rows=[row.row], amount=row.amount,
                              employee_id=row.employee_id)

        if self.active("DSB-14"):
            if "beneficiary_name" not in cols:
                self.not_run("DSB-14", "The bank file has no beneficiary name column.")
            elif "employee_name" not in self.inp.register.columns:
                self.not_run("DSB-14", "The register has no employee name column.")
            else:
                threshold = float(s.name_similarity)
                for row in bank.rows:
                    if not row.key or row.key not in self.reg:
                        continue
                    ours = self.reg[row.key].employee_name
                    if not row.beneficiary_name:
                        self.emit("DSB-14", "the beneficiary name in the file is blank", key=row.key,
                                  field="beneficiary_name", expected=ours or "", actual="(blank)", rows=[row.row])
                    elif not ours:
                        self.emit("DSB-14", "the register has no name for this employee to compare with",
                                  key=row.key, field="beneficiary_name", expected="(blank in register)",
                                  actual=row.beneficiary_name, rows=[row.row])
                    else:
                        score = values.name_similarity(row.beneficiary_name, ours, s.salutations)
                        if score < threshold:
                            self.emit("DSB-14", f"the beneficiary '{row.beneficiary_name}' does not match "
                                      f"'{ours}' (similarity {score:.2f}, threshold {threshold:.2f})",
                                      key=row.key, field="beneficiary_name", expected=ours,
                                      actual=row.beneficiary_name, rows=[row.row])

        self._master_checks()
        self._status_checks()

    def _master_checks(self) -> None:
        bank, s = self.bank, self.s
        master_table = self.inp.bank_master
        if self.active("DSB-16"):
            if master_table is None:
                self.not_run("DSB-16", "No bank master was supplied, so the accounts in the file cannot be "
                             "compared with the accounts on record.")
            elif not master_table.columns & {"account_number", "ifsc"}:
                self.not_run("DSB-16", "The bank master has neither an account number nor an IFSC column.")
            else:
                for row in bank.rows:
                    if not row.key:
                        continue
                    m = self.master.get(row.key)
                    if m is None:
                        self.emit("DSB-16", "this employee has no record in the bank master, so the account "
                                  "being paid cannot be confirmed", key=row.key, field="account_number",
                                  expected="(no master record)", actual=row.account_number or "", rows=[row.row],
                                  amount=row.amount)
                        continue
                    if "account_number" in master_table.columns:
                        ok, form = values.same_account(row.account_number, m.account_number)
                        if not ok:
                            self.emit("DSB-16", form or "the account in the file is not the account on the bank "
                                      "master", key=row.key, field="account_number",
                                      expected=m.account_number or "(blank on master)",
                                      actual=row.account_number or "(blank)", rows=[row.row], amount=row.amount)
                        elif form:
                            self.notes.append(Note("bank master", form, row=m.row, employee_id=m.employee_id))
                    if "ifsc" in master_table.columns and (row.ifsc or "") != (m.ifsc or ""):
                        self.emit("DSB-16", "the IFSC in the file is not the IFSC on the bank master",
                                  key=row.key, field="ifsc", expected=m.ifsc or "(blank on master)",
                                  actual=row.ifsc or "(blank)", rows=[row.row], amount=row.amount)

        if self.active("DSB-06"):
            prev_table = self.inp.previous
            if master_table is None:
                self.not_run("DSB-06", "No bank master was supplied, so verification status is unknown.")
                return
            if "verification_status" not in master_table.columns:
                self.not_run("DSB-06", "The bank master has no verification status column, so a change "
                             "cannot be confirmed as verified.")
                return
            prev_has_bank = bool(prev_table and prev_table.columns & {"account_number", "ifsc"})
            if self.inp.change_log is None and not prev_has_bank:
                self.not_run("DSB-06", "Neither a bank change log nor a previous period with account or IFSC "
                             "was supplied, so a change since the previous period cannot be seen.")
                return
            seen: set[str] = set()
            for row in bank.rows:
                key = row.key
                if not key or key in seen or key not in self.master:
                    continue
                seen.add(key)
                m = self.master[key]
                evidence: list[str] = []
                change_status = None
                for c in self.changes.get(key, []):
                    what = (c.field_changed or "").lower()
                    if what and not any(w in what for w in ("account", "ifsc", "bank")):
                        continue
                    if c.changed_on and c.changed_on < s.previous_start:
                        continue
                    evidence.append(f"change log: {c.field_changed or 'bank details'} changed"
                                    f"{' on ' + format(c.changed_on, '%d %b %Y') if c.changed_on else ''}")
                    if c.verification_status:
                        change_status = c.verification_status
                p = self.previous.get(key)
                if p is not None and prev_has_bank:
                    if p.account_number and m.account_number and \
                            p.account_number.lstrip("0") != m.account_number.lstrip("0"):
                        evidence.append(f"account was {p.account_number} in the previous period")
                    if p.ifsc and m.ifsc and p.ifsc != m.ifsc:
                        evidence.append(f"IFSC was {p.ifsc} in the previous period")
                if evidence and m.last_changed and m.last_changed >= s.previous_start:
                    evidence.append(f"master last changed {m.last_changed:%d %b %Y}")
                if not evidence:
                    continue
                status = change_status or m.verification_status
                if not values.is_verified(status, s.verified_values):
                    shown = f"'{status}'" if status else "blank"
                    self.emit("DSB-06", f"bank details changed ({'; '.join(evidence)}) and verification is "
                              f"{shown}", key=key, field="verification_status", expected="verified",
                              actual=status or "(blank)", rows=[r.row for r in self.rows_by_key[key]],
                              amount=sum((r.amount or ZERO) for r in self.rows_by_key[key]))

    def _status_checks(self) -> None:
        s = self.s
        if self.active("DSB-09"):
            if self.inp.hold_list is None and not self.status_columns():
                self.not_run("DSB-09", "Neither a hold list nor register status columns (status, exit date, "
                             "F&F, hold) were supplied.")
            else:
                for key, rows in self.rows_by_key.items():
                    why = self.exclusion(key)
                    if why:
                        self.emit("DSB-09", f"is in the file but {why}", key=key, field="status",
                                  expected="not paid", actual="in the file", rows=[r.row for r in rows],
                                  amount=sum((r.amount or ZERO) for r in rows))

        if self.active("DSB-11"):
            if self.inp.offcycle is None:
                self.not_run("DSB-11", "No off-cycle payments file was supplied.")
            else:
                for key, rows in self.rows_by_key.items():
                    paid = self.offcycle.get(key)
                    if paid:
                        detail = "; ".join(f"{_money(p.amount)}"
                                           f"{' on ' + format(p.payment_date, '%d %b %Y') if p.payment_date else ''}"
                                           f"{' ref ' + p.reference if p.reference else ''}" for p in paid)
                        self.emit("DSB-11", f"was already paid off-cycle this period ({detail})", key=key,
                                  field="employee_id", expected="not already paid", actual=detail,
                                  rows=[r.row for r in rows], amount=sum((r.amount or ZERO) for r in rows))

        if self.active("DSB-13"):
            prev_table = self.inp.previous
            if prev_table is None:
                self.not_run("DSB-13", "No previous period file was supplied.")
            elif not prev_table.columns & {"net_pay", "total_payable"}:
                self.not_run("DSB-13", "The previous period file has neither a net pay nor a total salary column.")
            else:
                cols = self.inp.register.columns
                # Like with like. Net pay against net pay when both periods give it: it moves
                # less than total salary, which swings with reimbursements and held salary.
                by_net = "net_pay" in prev_table.columns and "net_pay" in cols
                measure = "net pay" if by_net else "total salary"
                caveats = [] if by_net else ["compared on total salary, which moves with reimbursements and holds"]
                if "date_of_joining" not in cols:
                    caveats.append("no joining date column: only employees absent last period are treated as joiners")
                if not cols & {"arrears", "increment"}:
                    caveats.append("no arrears or increment column: those employees may be flagged")
                if caveats:
                    self.rules["DSB-13"].reason = "Ran with gaps — " + "; ".join(caveats) + "."
                limit = s.variance_pct
                for key in self.rows_by_key:
                    r = self.reg.get(key)
                    cur = self.reg_net.get(key) if by_net else self.reg_pay.get(key)
                    if r is None or cur is None or cur <= 0:
                        continue
                    p = self.previous.get(key)
                    before = (p.net_pay if by_net else p.total_payable) if p is not None else None
                    if before is None:
                        continue                          # not paid last period: a joiner
                    if r.date_of_joining and r.date_of_joining >= s.previous_start:
                        continue
                    if (r.date_of_exit and r.date_of_exit >= s.period_start) or status_kind(r.status) == "separated":
                        continue
                    if (r.arrears or ZERO) > 0 or r.increment:
                        continue
                    field = "net_pay" if by_net else "total_payable"
                    if before <= 0:
                        self.emit("DSB-13", f"{measure} is {_money(cur)}; the previous period's was {_money(before)}",
                                  key=key, field=field, expected=_money(before), actual=_money(cur),
                                  rows=self._lines(key), amount=self._paid(key))
                        continue
                    change = (cur - before) / before * 100
                    if abs(change) > limit:
                        self.emit("DSB-13", f"{measure} changed {change:+.1f}% against the previous period "
                                  f"({_money(before)} → {_money(cur)}); the threshold is {limit}%",
                                  key=key, field=field, expected=_money(before), actual=_money(cur),
                                  rows=self._lines(key), amount=self._paid(key))

        if self.active("DSB-15"):
            for key, net in self.due().items():
                if key not in self.rows_by_key:
                    self.emit("DSB-15", f"is due {_money(net)} in the register but is not in the bank file and "
                              "is not on the hold list", key=key, field="employee_id", expected="in the file",
                              actual="missing", amount=net)
            for key, r in self.reg.items():
                if self.reg_pay.get(key) is None and key not in self.rows_by_key and not self.exclusion(key) \
                        and key not in self.offcycle:
                    raw = r.total_raw if self.basis == "total" else r.net_raw
                    self.emit("DSB-15", f"the register's {'total salary' if self.basis == 'total' else 'net pay'} "
                              "is blank or unreadable and the employee is not in the file; confirm they are not "
                              "due", key=key, field="amount_due", expected="an amount", actual=raw or "(blank)")

    # -- file checks -------------------------------------------------------------
    def held(self) -> tuple[set[int], set[str]]:
        """Bank lines held, and the employees they belong to."""
        keys: set[str] = set()
        rows: set[int] = set()
        for f in self.findings:
            if f.severity != HOLD_ROW:
                continue
            ks = {self.key_of[x] for x in f.rows if self.key_of.get(x)}
            if ks:
                keys |= ks
            else:
                rows |= set(f.rows)
        for key in keys:
            rows |= {r.row for r in self.rows_by_key.get(key, [])}
        return rows, keys

    def file_checks(self) -> None:
        s, bank = self.s, self.bank
        header, footer = bank.header or {}, bank.footer or {}

        if self.active("DSB-04"):
            if not bank.has_header_record:
                self.not_run("DSB-04", "This file format has no header record, so there is no debit account "
                             "or value date to check.", status=NOT_APPLICABLE)
            elif not s.debit_account and not s.value_date:
                self.not_run("DSB-04", "No debit account is configured and no value date was given for this run.")
            else:
                gaps = []
                if s.debit_account:
                    stated = values.text(header.get("debit_account"))
                    if (stated or "").replace(" ", "") != s.debit_account.replace(" ", ""):
                        self.emit("DSB-04", "the header's debit account is not the configured salary account",
                                  field="debit_account", expected=s.debit_account, actual=stated or "(blank)")
                else:
                    gaps.append("the debit account was not checked: none is configured")
                if s.value_date:
                    stated_date = values.when(header.get("value_date"))
                    if stated_date != s.value_date:
                        self.emit("DSB-04", "the header's value date is not the value date given for this run",
                                  field="value_date", expected=f"{s.value_date:%d %b %Y}",
                                  actual=f"{stated_date:%d %b %Y}" if stated_date else
                                  values.text(header.get("value_date")) or "(blank)")
                else:
                    gaps.append("the value date was not checked: none was given for this run")
                if gaps:
                    self.rules["DSB-04"].reason = "Ran with gaps — " + "; ".join(gaps) + "."

        held_rows, _ = self.held()
        readable = [r for r in bank.rows if r.amount is not None]
        file_total = sum((r.amount for r in readable), ZERO)
        unreadable = len(bank.rows) - len(readable)
        held_amount = sum((r.amount for r in readable if r.row in held_rows), ZERO)
        clean = [r for r in bank.rows if r.row not in held_rows]
        cap = s.max_hold_share_pct
        due = self.due()

        if self.active("DSB-01"):
            for where, rec in (("header", header), ("footer", footer)):
                stated = rec.get("total_amount")
                if stated is None:
                    continue
                if abs(stated - file_total) > s.total_tolerance or unreadable:
                    self.emit("DSB-01", f"the {where} states a total of {_money(stated)} but the payment lines "
                              f"add up to {_money(file_total)}"
                              f"{f' ({unreadable} line(s) unreadable)' if unreadable else ''}; the file "
                              "disagrees with itself", field=f"{where}.total_amount", expected=_money(file_total),
                              actual=_money(stated))
            pays = [r for r in clean if r.key and r.key in self.reg and r.amount is not None]
            paid = sum((r.amount for r in pays), ZERO)
            owed = sum((self.reg_pay.get(r.key) or ZERO for r in pays), ZERO)
            if abs(paid - owed) > s.total_tolerance:
                self.emit("DSB-01", f"after the held lines are removed the file pays {_money(paid)}, but the "
                          f"{self.basis_text} for the same employees is {_money(owed)}", field="total",
                          expected=_money(owed), actual=_money(paid))
            if cap > 0 and file_total > 0 and held_amount * 100 / file_total > cap:
                self.emit("DSB-01", f"{_money(held_amount)} of {_money(file_total)} "
                          f"({held_amount * 100 / file_total:.1f}%) would be held — more than "
                          f"{cap}%; a file this wrong is more likely the wrong file than a few wrong lines",
                          field="held_amount_share", expected=f"at most {cap}%",
                          actual=f"{held_amount * 100 / file_total:.1f}%")

        if self.active("DSB-02"):
            for where, rec in (("header", header), ("footer", footer)):
                stated = rec.get("record_count")
                if stated is not None and stated != len(bank.rows):
                    self.emit("DSB-02", f"the {where} states {stated} payment line(s) but the file has "
                              f"{len(bank.rows)}; the file disagrees with itself", field=f"{where}.record_count",
                              expected=str(len(bank.rows)), actual=str(stated))
            if bank.rows and not clean:
                self.emit("DSB-02", "every line in the file would be held, so there is nothing to release",
                          field="clean_rows", expected="at least 1", actual="0")
            elif cap > 0 and bank.rows and len(held_rows) * 100 / len(bank.rows) > cap:
                share = len(held_rows) * 100 / len(bank.rows)
                self.emit("DSB-02", f"{len(held_rows)} of {len(bank.rows)} lines ({share:.1f}%) would be held — "
                          f"more than {cap}%; the file is more likely wrong as a whole",
                          field="held_row_share", expected=f"at most {cap}%", actual=f"{share:.1f}%")
            missing = [k for k in due if k not in self.rows_by_key]
            if cap > 0 and due and len(missing) * 100 / len(due) > cap:
                share = len(missing) * 100 / len(due)
                self.emit("DSB-02", f"{len(missing)} of the {len(due)} employees due ({share:.1f}%) are not in "
                          f"the file — more than {cap}%; the file looks incomplete",
                          field="missing_share", expected=f"at most {cap}%", actual=f"{share:.1f}%")

    # -- the walk from register to file ---------------------------------------
    def bridge(self, held_rows: set[int]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        due = self.due()
        first_seen: set[str] = set()
        not_in_register = duplicate_extra = not_due = differences = ZERO
        n_not_in_register = n_duplicate = n_not_due = 0
        unreadable = 0
        for row in self.bank.rows:
            if row.amount is None:
                unreadable += 1
            amount = row.amount or ZERO
            if not row.key or row.key not in self.reg:
                not_in_register += amount
                n_not_in_register += 1
            elif row.key in first_seen:
                duplicate_extra += amount
                n_duplicate += 1
            else:
                first_seen.add(row.key)
                if row.key in due:
                    differences += amount - due[row.key]
                else:
                    not_due += amount
                    n_not_due += 1
        missing = [k for k in due if k not in self.rows_by_key]
        missing_total = sum((due[k] for k in missing), ZERO)
        due_total = sum(due.values(), ZERO)
        file_total = sum((r.amount for r in self.bank.rows if r.amount is not None), ZERO)
        held_total = sum((r.amount for r in self.bank.rows if r.row in held_rows and r.amount is not None), ZERO)
        clean_rows = [r for r in self.bank.rows if r.row not in held_rows]
        clean_total = sum((r.amount for r in clean_rows if r.amount is not None), ZERO)
        lines = [
            {"label": f"Due per the register ({self.basis_text})", "amount": due_total, "count": len(due)},
            {"label": "Due but not in the bank file (DSB-15)", "amount": -missing_total, "count": -len(missing)},
            {"label": "Paid but not in the register (DSB-03)", "amount": not_in_register, "count": n_not_in_register},
            {"label": "Paid but not due: on hold, separated, F&F, already paid off-cycle, nothing payable "
                      "(DSB-09, DSB-11, DSB-07, DSB-08)",
             "amount": not_due, "count": n_not_due},
            {"label": "Extra lines for employees already paid once (DSB-10)", "amount": duplicate_extra,
             "count": n_duplicate},
            {"label": "Amount differences against the register (DSB-08)", "amount": differences, "count": 0},
            {"label": "Bank file total", "amount": file_total, "count": len(self.bank.rows), "total": True},
            {"label": "Held lines removed", "amount": -held_total, "count": -len(held_rows)},
            {"label": "Clean file to release", "amount": clean_total, "count": len(clean_rows), "total": True},
        ]
        employees_paid = len({r.key for r in clean_rows if r.key})
        prev_field = None
        if self.inp.previous:
            prev_field = "total_payable" if "total_payable" in self.inp.previous.columns else \
                "net_pay" if "net_pay" in self.inp.previous.columns else None
        prev_total = sum((getattr(p, prev_field) for p in self.previous.values()
                          if getattr(p, prev_field) is not None), ZERO) if prev_field else None
        totals = {
            "due_total": due_total, "due_count": len(due),
            "file_total": file_total, "file_rows": len(self.bank.rows), "unreadable_amounts": unreadable,
            "held_amount": held_total, "held_rows": len(held_rows),
            "held_employees": len({r.key for r in self.bank.rows if r.row in held_rows and r.key}),
            "release_amount": clean_total, "release_rows": len(clean_rows), "release_employees": employees_paid,
            "flags": sum(1 for f in self.findings if f.severity == FLAG),
            "previous_total": prev_total,
            "previous_total_basis": {"total_payable": "total salary", "net_pay": "net pay"}.get(prev_field or ""),
            "amount_basis": self.basis_text,
            "variance_vs_previous": (clean_total - prev_total) if prev_total is not None else None,
            "variance_pct_vs_previous": (round(float((clean_total - prev_total) * 100 / prev_total), 2)
                                         if prev_total else None),
        }
        return lines, totals


def run(inputs: Inputs, settings: Settings) -> Result:
    r = _Run(inputs, settings)
    r.row_checks()
    r.file_checks()
    held_rows, _ = r.held()
    stopped = any(f.severity == STOP_FILE for f in r.findings)
    if stopped:
        verdict = DO_NOT_RELEASE
    elif held_rows:
        verdict = WITH_HOLDS
    else:
        verdict = CLEAR
    lines, totals = r.bridge(held_rows)
    for rule in r.rules.values():
        if rule.status == NOT_RUN:
            r.findings.append(Finding(rule.rule_id, NOT_RUN, rule.reason))
    order = {STOP_FILE: 0, HOLD_ROW: 1, FLAG: 2, NOT_RUN: 3}
    r.findings.sort(key=lambda f: (order.get(f.severity, 9), f.rule_id, f.employee_id or "", f.rows[:1]))
    kept = set() if stopped else {r.line_of[row.row] for row in r.bank.rows if row.row not in held_rows}
    held_lines = {r.line_of[x] for x in held_rows}
    return Result(verdict, r.findings, list(r.rules.values()), held_lines, kept, totals, lines, r.notes)
