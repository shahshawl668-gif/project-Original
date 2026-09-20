"""
What kind of problem a finding is.

Severity says how much a finding matters. It does not say what to *do* with it,
and those are different questions. Three categories map to three different
actions, and to three different people:

* **missing** — something the tool needed was not supplied. Nobody can judge
  whether the payroll is right until it is. Fixed by sending a column, a master
  record or a configuration value. Often the largest category on a first run, and
  the one that silently disables other checks.
* **mismatch** — a figure in the register disagrees with what the rules compute.
  Fixed by correcting the register, or by correcting the configuration if the
  register is right.
* **issue** — the arithmetic holds but something is wrong, risky or unusual:
  paid after exit, below minimum wage, an unexplained spike. Fixed by a decision,
  not a recalculation.

Every rule that can be emitted must be classified here. An unclassified rule
fails the test suite rather than defaulting quietly — a finding filed under the
wrong action is worse than an uncategorised one, because the reader acts on it.
"""
from __future__ import annotations

MISSING = "missing"
MISMATCH = "mismatch"
ISSUE = "issue"

CATEGORY_ORDER = (MISSING, MISMATCH, ISSUE)

CATEGORY_LABELS = {
    MISSING: "Missing",
    MISMATCH: "Mismatch",
    ISSUE: "Issue",
}

CATEGORY_MEANING = {
    MISSING: "Data the validation needed but did not receive. Supply it and re-run — "
             "until then, the checks that depend on it are not being performed.",
    MISMATCH: "A figure in the register disagrees with what the rules compute. "
              "Correct the register, or the configuration if the register is right.",
    ISSUE: "The arithmetic holds, but something needs a decision: a risk, an "
           "anomaly, or a payment that should not have been made.",
}

# Rules whose whole purpose is to report absent input.
_MISSING_RULES = {
    "DATA-001",              # employee id absent
    "COMP-001", "COMP-002",  # unmapped column / configured component with no column
    "MST-001",               # absent from the employee master
    "MST-004", "MST-005",    # UAN / ESIC IP not on file
    "ATT-003",               # no attendance row for a paid employee
    "MW-003",                # no minimum wage rate, or no classification
    "GRAT-004",              # gratuity paid, joining date unknown
    "ARR-001",               # arrears paid, period not stated
}

# Rules that compare a computed figure against the register.
_MISMATCH_PREFIXES = ("STAT-", "AGG-", "PF-", "ESI-", "PT-", "LOP-", "TDS-")
_MISMATCH_RULES = {
    "ATT-001", "ATT-002",    # paid days / LOP against attendance
    "MOM-006",               # increment arrear against the CTC delta
    "ARR-002",               # arrear period resolves to something impossible
}

# Everything else is a judgement call rather than a correction.
_ISSUE_PREFIXES = ("STRUCT-", "MOM-", "ADV-", "ID-", "BON-", "GRAT-", "MST-", "ATT-", "MW-", "ARR-")
_ISSUE_RULES = {"DATA-002", "DATA-003", "DATA-004", "DATA-005",
                "DATA-006", "DATA-007", "DATA-008", "DATA-009"}


def categorise(rule_id: str, actual_value: str | None = None) -> str:
    """
    The category for one rule.

    ``actual_value`` is consulted only as a fallback: several rules report an
    absent column by writing "(missing)" into the actual value, and reporting
    those as a mismatch would send the reader looking for a wrong number that
    does not exist.
    """
    rule_id = (rule_id or "").strip().upper()

    if rule_id in _MISSING_RULES:
        return MISSING
    if actual_value and str(actual_value).strip().lower() in {"(missing)", "(none)", "(absent)"}:
        return MISSING

    if rule_id in _MISMATCH_RULES:
        return MISMATCH
    if rule_id in _ISSUE_RULES:
        return ISSUE

    if rule_id.startswith(_MISMATCH_PREFIXES):
        return MISMATCH
    if rule_id.startswith(_ISSUE_PREFIXES):
        return ISSUE
    if rule_id.startswith("DATA-"):
        return ISSUE

    return ISSUE


def is_classified(rule_id: str) -> bool:
    """Whether ``rule_id`` matches a declared rule or prefix, rather than the fallback."""
    rule_id = (rule_id or "").strip().upper()
    return (
        rule_id in _MISSING_RULES
        or rule_id in _MISMATCH_RULES
        or rule_id in _ISSUE_RULES
        or rule_id.startswith(_MISMATCH_PREFIXES)
        or rule_id.startswith(_ISSUE_PREFIXES)
        or rule_id.startswith("DATA-")
    )
