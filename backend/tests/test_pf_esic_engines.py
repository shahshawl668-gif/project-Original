"""Smoke tests for PF / ESIC engines (config-driven)."""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.schemas.statutory_config import ESICConfig, PFConfig
from app.services.esic_engine import compute_esic
from app.services.pf_engine import compute_pf


class TestPF:
    def test_below_ceiling_uses_full_wage(self):
        out = compute_pf(pf_wage=Decimal("12000"), pf_cfg=PFConfig())
        # 12% of 12,000 = 1,440 each (employee + employer total)
        assert round(out["pf_employee"]) == 1_440
        assert round(out["pf_employer_total"]) == 1_440

    def test_above_ceiling_caps_to_15k(self):
        out = compute_pf(pf_wage=Decimal("50000"), pf_cfg=PFConfig())
        # 12% of 15,000 = 1,800 each
        assert round(out["pf_employee"]) == 1_800
        assert round(out["pf_employer_total"]) == 1_800
        assert out["pf_type"] == "restricted"
        assert out["pf_wage_capped"] == 15_000

    def test_eps_capped_at_ceiling(self):
        out = compute_pf(pf_wage=Decimal("50000"), pf_cfg=PFConfig())
        # EPS 8.33% of 15,000 = 1,249.5
        assert 1_240 <= out["pf_eps"] <= 1_260
        assert out["pf_epf"] >= 0
        assert abs(out["pf_eps"] + out["pf_epf"] - out["pf_employer_total"]) < 1

    def test_zero_wage(self):
        out = compute_pf(pf_wage=Decimal("0"), pf_cfg=PFConfig())
        assert out["pf_employee"] == 0
        assert out["pf_employer_total"] == 0


class TestESIC:
    def test_under_threshold_eligible(self):
        out = compute_esic(esic_wage=Decimal("20000"), esic_cfg=ESICConfig())
        assert out["esic_eligible"] is True
        # Employee 0.75% of 20,000 = 150, employer 3.25% = 650
        assert out["esic_employee"] == 150
        assert out["esic_employer"] == 650

    def test_at_threshold_inclusive(self):
        out = compute_esic(esic_wage=Decimal("21000"), esic_cfg=ESICConfig())
        assert out["esic_eligible"] is True

    def test_above_threshold_exempt(self):
        out = compute_esic(esic_wage=Decimal("21500"), esic_cfg=ESICConfig())
        assert out["esic_eligible"] is False
        assert out["esic_employee"] == 0
        assert out["esic_employer"] == 0

    @pytest.mark.parametrize("wage", [Decimal("0"), Decimal("-1"), Decimal("-100")])
    def test_zero_or_negative_wage_is_safe(self, wage):
        out = compute_esic(esic_wage=wage, esic_cfg=ESICConfig())
        assert out["esic_eligible"] is False
        assert out["esic_employee"] == 0
