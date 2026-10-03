"""
The disbursement checks, and the settings a company can change.

Every threshold and every severity is configuration with a stated default. A
company switches a check off or changes how hard it bites here, never in code,
and the run records the settings it used.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

STOP_FILE = "STOP_FILE"
HOLD_ROW = "HOLD_ROW"
FLAG = "FLAG"
NOT_RUN = "NOT_RUN"
SEVERITIES = (STOP_FILE, HOLD_ROW, FLAG)

CLEAR = "CLEAR_TO_RELEASE"
WITH_HOLDS = "RELEASE_WITH_HOLDS"
DO_NOT_RELEASE = "DO_NOT_RELEASE"

# Rule outcomes, beside the findings themselves.
RAN = "RAN"
NOT_APPLICABLE = "NOT_APPLICABLE"
DISABLED = "DISABLED"

FILE = "file"
ROW = "row"
MISSING_ROW = "missing_row"   # about an employee who is not in the file at all


@dataclass(frozen=True)
class Rule:
    rule_id: str
    title: str
    level: str
    default_severity: str
    needs: str
    allowed: tuple[str, ...]


RULES: tuple[Rule, ...] = (
    Rule("DSB-01", "Bank file total does not reconcile to the register", FILE, STOP_FILE,
         "bank file, register", (STOP_FILE, FLAG)),
    Rule("DSB-02", "Bank file row count does not reconcile to the employees due", FILE, STOP_FILE,
         "bank file, register", (STOP_FILE, FLAG)),
    Rule("DSB-03", "Paid in the bank file but not in the register", ROW, STOP_FILE,
         "bank file, register", (STOP_FILE, HOLD_ROW, FLAG)),
    Rule("DSB-04", "Header debit account or value date is not the configured one", FILE, STOP_FILE,
         "bank file with a header record, configured debit account / value date", (STOP_FILE, FLAG)),
    Rule("DSB-05", "Same account number on two or more employees", ROW, HOLD_ROW,
         "bank file", (STOP_FILE, HOLD_ROW, FLAG)),
    Rule("DSB-06", "Bank details changed since the previous period and not verified", ROW, HOLD_ROW,
         "bank master with a verification column, plus change log or previous period", (STOP_FILE, HOLD_ROW, FLAG)),
    Rule("DSB-07", "Amount is zero, negative or unreadable", ROW, HOLD_ROW,
         "bank file", (STOP_FILE, HOLD_ROW, FLAG)),
    Rule("DSB-08", "Amount differs from net pay in the register", ROW, HOLD_ROW,
         "bank file, register", (STOP_FILE, HOLD_ROW, FLAG)),
    Rule("DSB-09", "Separated before the period, F&F processed, or on hold", ROW, HOLD_ROW,
         "bank file, plus hold list or register status columns", (STOP_FILE, HOLD_ROW, FLAG)),
    Rule("DSB-10", "Employee appears more than once in the bank file", ROW, HOLD_ROW,
         "bank file", (STOP_FILE, HOLD_ROW, FLAG)),
    Rule("DSB-11", "Already paid through an off-cycle payment this period", ROW, HOLD_ROW,
         "bank file, off-cycle payments", (STOP_FILE, HOLD_ROW, FLAG)),
    Rule("DSB-12", "IFSC or account number is not valid", ROW, HOLD_ROW,
         "bank file", (STOP_FILE, HOLD_ROW, FLAG)),
    Rule("DSB-13", "Net pay changed more than the variance threshold", ROW, FLAG,
         "register, previous period", (STOP_FILE, HOLD_ROW, FLAG)),
    Rule("DSB-14", "Beneficiary name does not match the employee name", ROW, FLAG,
         "bank file and register, both with names", (STOP_FILE, HOLD_ROW, FLAG)),
    Rule("DSB-15", "Due to be paid but missing from the bank file", MISSING_ROW, FLAG,
         "bank file, register", (STOP_FILE, FLAG)),
    Rule("DSB-16", "Account or IFSC in the file is not the one on the bank master", ROW, HOLD_ROW,
         "bank file, bank master", (STOP_FILE, HOLD_ROW, FLAG)),
    Rule("DSB-17", "Total salary in the register does not equal net pay plus reimbursements and released "
         "holds, less salary held", ROW, FLAG,
         "register with total salary, net pay and a reimbursement or salary hold column", (STOP_FILE, HOLD_ROW, FLAG)),
)
RULE_BY_ID = {r.rule_id: r for r in RULES}


DEFAULTS: dict[str, Any] = {
    # Net pay change against the previous period that is worth a look (DSB-13).
    "variance_pct": "25",
    # 0..1; how alike a beneficiary name must be to the employee name (DSB-14).
    "name_similarity": "0.80",
    "account_length_min": 9,
    "account_length_max": 18,
    # Rupees either way between the file and the register, per employee (DSB-08)
    # and for the whole clean file (DSB-01). Exact by default.
    "amount_tolerance": "0.00",
    "total_tolerance": "0.00",
    # When the rows held add up to more than this share of the file — by count
    # or by amount — the file is more likely wrong as a whole (the wrong run, the
    # wrong month) than wrong in a few places, and is stopped (DSB-01, DSB-02).
    # 0 switches the cap off.
    "max_hold_share_pct": "25",
    # The account the salaries are debited from, as the header must state it (DSB-04).
    "debit_account": None,
    "salutations": ["mr", "mrs", "ms", "miss", "dr", "shri", "sri", "smt", "kum", "km", "mx", "prof"],
    "verified_values": ["verified", "yes", "y", "true", "1", "approved", "validated", "success",
                        "penny drop success", "penny_drop_success", "active"],
    "severities": {},
    "enabled": {},
}


def _dec(value: Any, name: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError) as exc:
        raise ValueError(f"{name} must be a number, not {value!r}") from exc


@dataclass
class Settings:
    """One company's settings, plus the values that belong to a single run."""

    period_start: date
    period_end: date
    previous_start: date
    variance_pct: Decimal
    name_similarity: Decimal
    account_length_min: int
    account_length_max: int
    amount_tolerance: Decimal
    total_tolerance: Decimal
    max_hold_share_pct: Decimal
    debit_account: str | None
    value_date: date | None
    salutations: frozenset[str]
    verified_values: frozenset[str]
    severities: dict[str, str] = field(default_factory=dict)
    enabled: dict[str, bool] = field(default_factory=dict)

    def severity(self, rule_id: str) -> str:
        return self.severities.get(rule_id) or RULE_BY_ID[rule_id].default_severity

    def is_enabled(self, rule_id: str) -> bool:
        return self.enabled.get(rule_id, True)

    def snapshot(self) -> dict[str, Any]:
        """What the run records: enough to show exactly which settings judged the file."""
        return {
            "period_start": self.period_start.isoformat(), "period_end": self.period_end.isoformat(),
            "variance_pct": str(self.variance_pct), "name_similarity": str(self.name_similarity),
            "account_length_min": self.account_length_min, "account_length_max": self.account_length_max,
            "amount_tolerance": str(self.amount_tolerance), "total_tolerance": str(self.total_tolerance),
            "max_hold_share_pct": str(self.max_hold_share_pct), "debit_account": self.debit_account,
            "value_date": self.value_date.isoformat() if self.value_date else None,
            "severities": {r.rule_id: self.severity(r.rule_id) for r in RULES},
            "enabled": {r.rule_id: self.is_enabled(r.rule_id) for r in RULES},
        }


def _month_bounds(period: str) -> tuple[date, date, date]:
    try:
        year, month = (int(x) for x in str(period).split("-")[:2])
        start = date(year, month, 1)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"period must look like 2026-09, not {period!r}") from exc
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    from datetime import timedelta

    end = nxt - timedelta(days=1)
    prev = date(year - (month == 1), (month - 2) % 12 + 1, 1)
    return start, end, prev


def build_settings(period: str, company: dict[str, Any] | None = None,
                   value_date: date | None = None) -> Settings:
    """Company settings over the defaults, checked; a bad value is an error, not a fallback."""
    cfg = {**DEFAULTS, **{k: v for k, v in (company or {}).items() if v is not None}}
    unknown = set(company or {}) - set(DEFAULTS)
    if unknown:
        raise ValueError(f"Unknown setting(s): {', '.join(sorted(unknown))}")
    severities = dict(cfg.get("severities") or {})
    for rule_id, sev in severities.items():
        rule = RULE_BY_ID.get(rule_id)
        if rule is None:
            raise ValueError(f"Unknown rule {rule_id}")
        if sev not in rule.allowed:
            raise ValueError(f"{rule_id} can be {', '.join(rule.allowed)}, not {sev}")
    enabled = {}
    for rule_id, on in dict(cfg.get("enabled") or {}).items():
        if rule_id not in RULE_BY_ID:
            raise ValueError(f"Unknown rule {rule_id}")
        enabled[rule_id] = bool(on)
    start, end, prev = _month_bounds(period)
    lo, hi = int(cfg["account_length_min"]), int(cfg["account_length_max"])
    if not 1 <= lo <= hi <= 34:
        raise ValueError("Account length range must satisfy 1 ≤ min ≤ max ≤ 34")
    similarity = _dec(cfg["name_similarity"], "name_similarity")
    if not Decimal("0") <= similarity <= Decimal("1"):
        raise ValueError("name_similarity must be between 0 and 1")
    settings = Settings(
        period_start=start, period_end=end, previous_start=prev,
        variance_pct=_dec(cfg["variance_pct"], "variance_pct"),
        name_similarity=similarity,
        account_length_min=lo, account_length_max=hi,
        amount_tolerance=abs(_dec(cfg["amount_tolerance"], "amount_tolerance")),
        total_tolerance=abs(_dec(cfg["total_tolerance"], "total_tolerance")),
        max_hold_share_pct=_dec(cfg["max_hold_share_pct"], "max_hold_share_pct"),
        debit_account=(str(cfg["debit_account"]).strip() or None) if cfg.get("debit_account") else None,
        value_date=value_date,
        salutations=frozenset(str(s).lower().strip(".") for s in cfg["salutations"]),
        verified_values=frozenset(str(s).lower().strip() for s in cfg["verified_values"]),
        severities=severities, enabled=enabled,
    )
    if settings.variance_pct < 0 or settings.max_hold_share_pct < 0:
        raise ValueError("Percentages cannot be negative")
    return settings
