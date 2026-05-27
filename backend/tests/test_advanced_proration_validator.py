"""Unit tests for `AdvancedProrationValidator`.

The validator emits these flags:
  * PRORATION_ERROR          (HIGH for DOJ joiners, MEDIUM for partial-month bonus)
  * FNF_LEAVE_ENCASHMENT_ERROR (HIGH)
  * LOP_MISMATCH             (MEDIUM)
  * NEGATIVE_LOP             (CRITICAL)

All tests use April 2026 (30 days).
"""
from __future__ import annotations

import pandas as pd
import pytest

from app.utils.constants import Severity, ValidationFlag
from app.validators.advanced_proration import AdvancedProrationValidator
from app.validators.base import ValidatorConfig

MONTH = 4
YEAR = 2026
TOTAL_DAYS = 30


def _validator(tol: float = 1.0) -> AdvancedProrationValidator:
    return AdvancedProrationValidator(config=ValidatorConfig(tolerance_rupees=tol))


def _flags(result, flag: ValidationFlag) -> list:
    return [i for i in result.issues if i.flag == flag]


class TestDojJoiner:
    """DOJ within payroll month → component proration must be `monthly × payable/total`."""

    def _base_row(self) -> dict:
        # Joined Apr 15 → payable_days = 30 - 15 + 1 = 16
        return {
            "Employee_ID": "E1",
            "Employee_Name": "Test Joiner",
            "Date_of_Joining": "2026-04-15",
            "Basic": 30000.0,
            "HRA": 12000.0,
            "Payable_Days": 30.0,  # validator will overwrite to 16
            "LOP_Days": 0.0,
        }

    def test_clean_proration_emits_no_proration_issue(self):
        row = self._base_row()
        # 30000 * 16/30 = 16000.00, 12000 * 16/30 = 6400.00
        row["Paid_Basic"] = 16000.00
        row["Paid_HRA"] = 6400.00
        df = pd.DataFrame([row])
        result = _validator().validate(df, payroll_month=MONTH, payroll_year=YEAR)
        assert _flags(result, ValidationFlag.PRORATION_ERROR) == [] or all(
            # Bonus warning is allowed (no Bonus column here), but no DOJ proration HIGH.
            i.severity != Severity.HIGH
            for i in _flags(result, ValidationFlag.PRORATION_ERROR)
        )

    def test_wrong_basic_proration_emits_high_proration_error(self):
        row = self._base_row()
        row["Paid_Basic"] = 20000.00  # should be 16000 → diff +4000
        row["Paid_HRA"] = 6400.00
        df = pd.DataFrame([row])
        result = _validator().validate(df, payroll_month=MONTH, payroll_year=YEAR)
        basic_issues = [
            i
            for i in _flags(result, ValidationFlag.PRORATION_ERROR)
            if i.component == "Basic"
        ]
        assert len(basic_issues) == 1
        issue = basic_issues[0]
        assert issue.severity == Severity.HIGH
        assert issue.expected_value == pytest.approx(16000.0, abs=0.01)
        assert issue.actual_value == pytest.approx(20000.0, abs=0.01)
        assert issue.difference == pytest.approx(4000.0, abs=0.01)

    def test_under_tolerance_is_ignored(self):
        row = self._base_row()
        # 30000 * 16/30 = 16000 exact; pay 16000.50 (within ₹1 tol)
        row["Paid_Basic"] = 16000.50
        df = pd.DataFrame([row])
        result = _validator(tol=1.0).validate(df, payroll_month=MONTH, payroll_year=YEAR)
        basic_issues = [
            i
            for i in _flags(result, ValidationFlag.PRORATION_ERROR)
            if i.component == "Basic"
        ]
        assert basic_issues == []


class TestFnfLeaveEncashment:
    """Exiter in payroll month → Leave_Encashment must be `pending_leaves × Basic/26`."""

    def _base_row(self) -> dict:
        # LWD Apr 20, Basic 26000 → daily 1000, 5 pending leaves → 5000 expected.
        return {
            "Employee_ID": "E2",
            "Employee_Name": "Test Exiter",
            "Last_Working_Day": "2026-04-20",
            "Basic": 26000.0,
            "Pending_Leaves": 5,
            "Payable_Days": 20.0,
            "LOP_Days": 0.0,
        }

    def test_correct_leave_encashment_no_issue(self):
        row = self._base_row()
        row["Leave_Encashment"] = 5000.00
        df = pd.DataFrame([row])
        result = _validator().validate(df, payroll_month=MONTH, payroll_year=YEAR)
        assert _flags(result, ValidationFlag.FNF_LEAVE_ENCASHMENT_ERROR) == []

    def test_wrong_leave_encashment_emits_high_issue(self):
        row = self._base_row()
        row["Leave_Encashment"] = 3000.00  # expected 5000, diff = -2000
        df = pd.DataFrame([row])
        result = _validator().validate(df, payroll_month=MONTH, payroll_year=YEAR)
        issues = _flags(result, ValidationFlag.FNF_LEAVE_ENCASHMENT_ERROR)
        assert len(issues) == 1
        i = issues[0]
        assert i.severity == Severity.HIGH
        assert i.expected_value == pytest.approx(5000.0, abs=0.01)
        assert i.actual_value == pytest.approx(3000.0, abs=0.01)
        assert i.difference == pytest.approx(-2000.0, abs=0.01)


class TestLopMismatch:
    """Regular (non-joiner, non-exiter) employees: Payable_Days must equal total_days - LOP."""

    def _row(self, lop: float, payable: float) -> dict:
        return {
            "Employee_ID": "E3",
            "Employee_Name": "Regular",
            "Basic": 30000.0,
            "LOP_Days": lop,
            "Payable_Days": payable,
        }

    def test_consistent_lop_no_issue(self):
        df = pd.DataFrame([self._row(lop=2, payable=28)])
        result = _validator().validate(df, payroll_month=MONTH, payroll_year=YEAR)
        assert _flags(result, ValidationFlag.LOP_MISMATCH) == []

    def test_payable_days_one_short_emits_medium_issue(self):
        df = pd.DataFrame([self._row(lop=2, payable=27)])
        result = _validator().validate(df, payroll_month=MONTH, payroll_year=YEAR)
        issues = _flags(result, ValidationFlag.LOP_MISMATCH)
        assert len(issues) == 1
        assert issues[0].severity == Severity.MEDIUM
        assert issues[0].expected_value == pytest.approx(28.0)
        assert issues[0].actual_value == pytest.approx(27.0)

    def test_sub_half_day_diff_is_ignored(self):
        df = pd.DataFrame([self._row(lop=2.0, payable=28.4)])
        result = _validator().validate(df, payroll_month=MONTH, payroll_year=YEAR)
        assert _flags(result, ValidationFlag.LOP_MISMATCH) == []


class TestNegativeLop:
    def test_negative_lop_is_critical(self):
        df = pd.DataFrame(
            [
                {
                    "Employee_ID": "E4",
                    "Employee_Name": "Bad LOP",
                    "Basic": 30000.0,
                    "LOP_Days": -1.5,
                    "Payable_Days": 31.5,
                }
            ]
        )
        result = _validator().validate(df, payroll_month=MONTH, payroll_year=YEAR)
        issues = _flags(result, ValidationFlag.NEGATIVE_LOP)
        assert len(issues) == 1
        assert issues[0].severity == Severity.CRITICAL
        assert issues[0].actual_value == pytest.approx(-1.5)


class TestPartialMonthBonus:
    def test_bonus_with_full_month_no_warning(self):
        df = pd.DataFrame(
            [
                {
                    "Employee_ID": "E5",
                    "Employee_Name": "Full Month",
                    "Basic": 30000.0,
                    "Bonus": 5000.0,
                    "LOP_Days": 0,
                    "Payable_Days": 30,
                }
            ]
        )
        result = _validator().validate(df, payroll_month=MONTH, payroll_year=YEAR)
        bonus_warnings = [
            i
            for i in _flags(result, ValidationFlag.PRORATION_ERROR)
            if i.component == "Bonus"
        ]
        assert bonus_warnings == []

    def test_bonus_with_heavy_lop_emits_medium_warning(self):
        df = pd.DataFrame(
            [
                {
                    "Employee_ID": "E6",
                    "Employee_Name": "Partial Bonus",
                    "Basic": 30000.0,
                    "Bonus": 5000.0,
                    "LOP_Days": 10,
                    "Payable_Days": 20,  # < 30 - 2 = 28
                }
            ]
        )
        result = _validator().validate(df, payroll_month=MONTH, payroll_year=YEAR)
        bonus_warnings = [
            i
            for i in _flags(result, ValidationFlag.PRORATION_ERROR)
            if i.component == "Bonus"
        ]
        assert len(bonus_warnings) == 1
        assert bonus_warnings[0].severity == Severity.MEDIUM


class TestEmployeeMasterMerge:
    """Master can supplement payroll with columns it lacks (e.g. Pending_Leaves)."""

    def test_master_supplies_pending_leaves_for_fnf_check(self):
        payroll = pd.DataFrame(
            [
                {
                    "Employee_ID": "E7",
                    "Employee_Name": "Master Exiter",
                    "Last_Working_Day": "2026-04-20",
                    "Basic": 26000.0,
                    "Leave_Encashment": 3000.0,
                    "Payable_Days": 20.0,
                    "LOP_Days": 0.0,
                }
            ]
        )
        # Pending_Leaves only lives on the master.
        master = pd.DataFrame([{"Employee_ID": "E7", "Pending_Leaves": 5}])
        result = _validator().validate(
            payroll, employee_master=master, payroll_month=MONTH, payroll_year=YEAR
        )
        issues = _flags(result, ValidationFlag.FNF_LEAVE_ENCASHMENT_ERROR)
        assert len(issues) == 1
        # Basic/26 * 5 = 5000 expected, paid 3000 → diff -2000.
        assert issues[0].expected_value == pytest.approx(5000.0, abs=0.01)
        assert issues[0].actual_value == pytest.approx(3000.0, abs=0.01)


class TestResultEnvelope:
    def test_records_processed_and_validator_name(self):
        df = pd.DataFrame(
            [
                {"Employee_ID": "A", "Employee_Name": "A", "LOP_Days": 0, "Payable_Days": 30},
                {"Employee_ID": "B", "Employee_Name": "B", "LOP_Days": 0, "Payable_Days": 30},
            ]
        )
        result = _validator().validate(df, payroll_month=MONTH, payroll_year=YEAR)
        assert result.validator_name == "AdvancedProrationValidator"
        assert result.records_processed == 2
        assert result.issue_count == 0

    def test_issue_to_dict_serialises_enums(self):
        df = pd.DataFrame(
            [
                {
                    "Employee_ID": "X",
                    "Employee_Name": "X",
                    "LOP_Days": -3,
                    "Payable_Days": 33,
                }
            ]
        )
        result = _validator().validate(df, payroll_month=MONTH, payroll_year=YEAR)
        assert result.issues, "expected a negative-LOP issue"
        d = result.issues[0].to_dict()
        assert d["flag"] == "NEGATIVE_LOP"
        assert d["severity"] == "CRITICAL"
        assert d["component"] == "LOP_Days"
