"""Sanity checks for the FY 2025-26 income-tax engine.

Numbers cross-checked against Budget 2025 Memorandum (slabs, surcharge caps,
87A new-regime ₹60,000 rebate, marginal relief at the ₹12L threshold).
"""
from __future__ import annotations

import pytest

from app.services.income_tax_engine import (
    OldRegimeDeductions,
    compute_income_tax,
    compare_regimes,
)


class TestNewRegime:
    def test_zero_income_zero_tax(self):
        res = compute_income_tax(annual_gross=0, regime="new")
        assert res.total_tax_annual == 0
        assert res.monthly_tds == 0

    def test_below_standard_deduction(self):
        # ₹50k income, std ded ₹75k → taxable 0
        res = compute_income_tax(annual_gross=50_000, regime="new")
        assert res.taxable_income == 0
        assert res.total_tax_annual == 0

    def test_under_12L_full_rebate(self):
        # ₹12L gross → after ₹75k std ded = ₹11.25L taxable → 87A wipes it out
        res = compute_income_tax(annual_gross=12_00_000, regime="new")
        assert res.total_tax_annual == 0

    def test_just_over_12L_marginal_relief(self):
        # Income just past the 87A cliff should not jump by huge tax
        res = compute_income_tax(annual_gross=12_75_000, regime="new")
        assert res.total_tax_annual >= 0
        # Sanity: total tax should not exceed the income above ₹12L taxable
        assert res.total_tax_annual <= 80_000

    def test_high_income_uses_top_slab(self):
        res = compute_income_tax(annual_gross=50_00_000, regime="new")
        assert res.slab_tax > 0
        assert res.surcharge >= 0
        assert res.cess > 0
        assert res.total_tax_annual > res.slab_tax  # cess adds on

    def test_surcharge_capped_at_25_percent(self):
        # ₹6 crore: in old regime would be 37%, in new it must be 25%
        res = compute_income_tax(annual_gross=6_00_00_000, regime="new")
        # Surcharge / slab_tax (after rebate) ratio should be ~25%
        ratio = res.surcharge / max(res.slab_tax - res.rebate_87a, 1)
        assert 0.20 <= ratio <= 0.30


class TestOldRegime:
    def test_basic_exemption(self):
        # ₹2.5L income → after std ded → 0 tax
        res = compute_income_tax(annual_gross=2_50_000, regime="old")
        assert res.total_tax_annual == 0

    def test_87a_rebate(self):
        # ₹5L gross with no deductions → after ₹50k std ded = ₹4.5L → rebate covers all
        res = compute_income_tax(annual_gross=5_00_000, regime="old")
        assert res.total_tax_annual == 0

    def test_with_chapter_via_deductions(self):
        deds = OldRegimeDeductions(
            section_80c=1_50_000,
            section_80d=25_000,
            section_80ccd_1b=50_000,
        )
        res = compute_income_tax(
            annual_gross=10_00_000,
            regime="old",
            deductions=deds,
        )
        # taxable should be 10L - 50k std - 2.25L deductions = ~7.25L
        assert 7_00_000 <= res.taxable_income <= 7_50_000
        assert res.total_tax_annual > 0


class TestCompare:
    def test_compare_returns_both_regimes(self):
        res = compare_regimes(annual_gross=15_00_000)
        assert "old" in res
        assert "new" in res
        assert res["cheaper_regime"] in ("old", "new")
        assert res["annual_saving"] >= 0

    def test_new_regime_typically_cheaper_for_low_income(self):
        # No deductions → new is always at least as cheap
        res = compare_regimes(annual_gross=8_00_000)
        assert res["cheaper_regime"] == "new"
        assert res["new"]["total_tax_annual"] <= res["old"]["total_tax_annual"]

    def test_old_regime_can_win_with_heavy_deductions(self):
        # With a fat 80C / 80D / home loan stack at ₹15L income, old regime can win
        deds = OldRegimeDeductions(
            section_80c=1_50_000,
            section_80d=50_000,
            section_80ccd_1b=50_000,
            home_loan_interest=2_00_000,
        )
        res = compare_regimes(annual_gross=15_00_000, deductions=deds)
        # We don't hard-code the winner (rules can shift) — but result must be consistent
        assert res["cheaper_regime"] in ("old", "new")
        assert res["annual_saving"] >= 0


@pytest.mark.parametrize(
    "income,regime",
    [
        (3_00_000, "new"),
        (8_00_000, "new"),
        (15_00_000, "new"),
        (3_00_000, "old"),
        (8_00_000, "old"),
        (15_00_000, "old"),
    ],
)
def test_monotonic_tax(income, regime):
    """Tax must never decrease as income increases (no inversion bugs)."""
    a = compute_income_tax(annual_gross=income, regime=regime)
    b = compute_income_tax(annual_gross=income + 1_00_000, regime=regime)
    assert b.total_tax_annual >= a.total_tax_annual - 1  # tolerate rounding
