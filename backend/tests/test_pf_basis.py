"""
Per-employee PF restriction.

Two people on one payroll can sit on different bases — one capped at the
statutory ceiling, one contributing on full wage. Applying a single employer-wide
switch to both mis-states PF for whoever is on the other basis, every month.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.schemas.statutory_config import PFConfig
from app.services.pf_basis import parse_flag, resolve
from app.services.pf_engine import compute_pf

CEILING = Decimal("15000")
WAGE = Decimal("40000")          # comfortably above the ceiling
RATE = Decimal("0.12")


# ── flag parsing ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", ["Y", "yes", "TRUE", 1, True, "Restricted", "capped", "ceiling"])
def test_restricted_spellings(value):
    assert parse_flag(value) is True


@pytest.mark.parametrize("value", ["N", "no", "FALSE", 0, False, "Unrestricted", "uncapped", "full"])
def test_unrestricted_spellings(value):
    assert parse_flag(value) is False


@pytest.mark.parametrize("value", [None, "", "  ", "N/A", "-", "maybe", "nan"])
def test_unstated_is_not_false(value):
    """"Not stated" must fall through to the next source, never mean unrestricted."""
    assert parse_flag(value) is None


# ── precedence ───────────────────────────────────────────────────────────────

def test_register_row_wins():
    """The row describes the month being validated, so it is the most specific."""
    basis = resolve({"PF Restricted": "No"}, master_flag=True, entity_default=True)
    assert basis.restricted is False
    assert basis.source == "register"


def test_master_used_when_the_row_is_silent():
    basis = resolve({"Basic": 40000}, master_flag=False, entity_default=True)
    assert basis.restricted is False
    assert basis.source == "master"


def test_entity_default_is_the_last_resort():
    basis = resolve({"Basic": 40000}, master_flag=None, entity_default=True)
    assert basis.restricted is True
    assert basis.source == "entity default"


def test_an_unreadable_row_value_falls_through():
    """A row saying "maybe" must not override a master that says something."""
    basis = resolve({"PF Restricted": "maybe"}, master_flag=True, entity_default=False)
    assert basis.restricted is True
    assert basis.source == "master"


# ── the computation actually differs ────────────────────────────────────────

def _pf(restricted: bool | None) -> Decimal:
    cfg = PFConfig()
    cfg.wage.wage_ceiling = CEILING
    cfg.wage.restrict_to_ceiling = True          # entity default is restricted
    out = compute_pf(WAGE, cfg, restrict_override=restricted)
    return Decimal(str(out["pf_employee"]))


def test_restricted_caps_at_the_ceiling():
    assert _pf(True) == (CEILING * RATE).quantize(Decimal("0.01"))   # 1,800.00


def test_unrestricted_uses_the_full_wage():
    assert _pf(False) == (WAGE * RATE).quantize(Decimal("0.01"))     # 4,800.00


def test_two_employees_on_one_payroll_differ():
    """The whole point: the same wage, two correct answers."""
    assert _pf(True) != _pf(False)
    assert _pf(False) - _pf(True) == Decimal("3000.00")


def test_override_absent_uses_the_entity_default():
    assert _pf(None) == _pf(True)


def test_eps_stays_capped_even_when_unrestricted():
    """EPS is capped at the ceiling regardless of the employee's PF basis."""
    cfg = PFConfig()
    cfg.wage.wage_ceiling = CEILING
    cfg.wage.restrict_to_ceiling = False
    out = compute_pf(WAGE, cfg, restrict_override=False)
    expected_eps = (CEILING * Decimal(str(cfg.rates.eps_rate))).quantize(Decimal("0.01"))
    assert Decimal(str(out["pf_eps"])) == expected_eps


def test_below_the_ceiling_both_bases_agree():
    """No employee is disadvantaged by the setting when they earn under it."""
    cfg = PFConfig()
    cfg.wage.wage_ceiling = CEILING
    low = Decimal("12000")
    assert compute_pf(low, cfg, restrict_override=True)["pf_employee"] == \
           compute_pf(low, cfg, restrict_override=False)["pf_employee"]


def test_the_engine_reports_which_basis_it_used():
    cfg = PFConfig()
    cfg.wage.wage_ceiling = CEILING
    assert compute_pf(WAGE, cfg, restrict_override=True)["_restrict"] is True
    assert compute_pf(WAGE, cfg, restrict_override=False)["_restrict"] is False
    # And the uncapped wage, so a rule can test the opposite basis.
    assert Decimal(str(compute_pf(WAGE, cfg, restrict_override=True)["_pf_wage_full"])) == WAGE


# ── PF-009: the finding that makes the setting actionable ───────────────────

def _findings_for(actual_pf: Decimal, restricted: bool, source: str = "master"):
    from app.services.rule_engine_v2 import build_findings

    cfg = PFConfig()
    cfg.wage.wage_ceiling = CEILING
    pf_calc = compute_pf(WAGE, cfg, restrict_override=restricted)
    pf_calc["_basis_source"] = source

    return build_findings(
        employee_id="E1", employee_name="Test", 
        row={"pf_employee": float(actual_pf), "basic": float(WAGE)},
        comp_by_key={}, regular={"basic": WAGE}, arrear_by_base={},
        inc_arrear_total=Decimal("0"), paid_days=Decimal("30"), lop_days=Decimal("0"),
        days_in_month=30, pf_calc=pf_calc,
        esic_calc={"esic_eligible": False, "esic_employee": 0, "esic_employer": 0},
        pt_due=Decimal("0"), lwf_eamt=Decimal("0"), lwf_oamt=Decimal("0"),
        prior_components=None, prior_is_joiner=False, lop_diffs=[],
        inc_info={}, tds_risk=[],
    )


def _ids(findings) -> set[str]:
    return {f.rule_id for f in findings if f.status == "FAIL"}


def test_pf_deducted_on_the_wrong_basis_is_named_as_such():
    """
    An employee set to restricted, whose PF was deducted on full wage.

    The useful finding is "wrong basis", not "wrong by ₹3,000" — the fix is a
    configuration decision, not a recalculation.
    """
    unrestricted_amount = (WAGE * RATE).quantize(Decimal("0.01"))
    findings = _findings_for(unrestricted_amount, restricted=True)

    assert "PF-009" in _ids(findings)
    assert "STAT-001" not in _ids(findings)

    pf009 = next(f for f in findings if f.rule_id == "PF-009")
    assert "unrestricted" in pf009.reason
    assert "master" in pf009.reason          # names where the basis came from
    assert pf009.financial_impact == 3000.0


def test_the_mirror_case_is_caught_too():
    """Set to unrestricted, deducted at the ceiling."""
    restricted_amount = (CEILING * RATE).quantize(Decimal("0.01"))
    findings = _findings_for(restricted_amount, restricted=False)

    assert "PF-009" in _ids(findings)
    pf009 = next(f for f in findings if f.rule_id == "PF-009")
    assert "restricted to the ceiling" in pf009.reason


def test_an_ordinary_miscalculation_is_still_ordinary():
    """An amount matching neither basis stays STAT-001, not PF-009."""
    findings = _findings_for(Decimal("2222.00"), restricted=True)
    assert "STAT-001" in _ids(findings)
    assert "PF-009" not in _ids(findings)


def test_a_correct_deduction_raises_neither():
    correct = (CEILING * RATE).quantize(Decimal("0.01"))
    assert not ({"PF-009", "STAT-001"} & _ids(_findings_for(correct, restricted=True)))
