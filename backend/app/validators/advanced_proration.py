"""Advanced proration validator for the Phase 2 audit engine.

Catches:
  * DOJ mid-month joiners whose component-wise prorated amounts are wrong
  * F&F leave-encashment mismatch against Basic/26
  * Regular employees where Payable_Days ≠ month_days - LOP_Days
  * Negative LOP_Days (data-entry error)
  * Bonus paid alongside a partial-month payable count (warning to verify)

Adapted from the original Phase 2 spec; uses the shared `BaseValidator`
framework and emits structured `ValidationIssue`s.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import pandas as pd

from app.utils.constants import Severity, ValidationFlag
from app.utils.helpers import get_month_days, parse_date_column
from app.validators.base import BaseValidator, ValidationIssue, ValidationResult


class AdvancedProrationValidator(BaseValidator):
    def validate(
        self,
        payroll: pd.DataFrame,
        employee_master: Optional[pd.DataFrame] = None,
        payroll_month: int = 1,
        payroll_year: int = 2024,
    ) -> ValidationResult:
        result = ValidationResult(validator_name="AdvancedProrationValidator")
        df = payroll.copy()
        result.records_processed = len(df)
        tol = self.config.tolerance_rupees

        total_days = get_month_days(payroll_year, payroll_month)
        weekends_count = self._count_weekends(payroll_year, payroll_month)
        working_days = total_days - weekends_count  # noqa: F841 — reserved for future weekend-aware checks

        if "Date_of_Joining" in df.columns:
            df["Date_of_Joining"] = parse_date_column(df["Date_of_Joining"])
        if "Last_Working_Day" in df.columns:
            df["Last_Working_Day"] = parse_date_column(df["Last_Working_Day"])

        if employee_master is not None:
            em_cols = [
                c
                for c in [
                    "Employee_ID",
                    "Date_of_Joining",
                    "Last_Working_Day",
                    "Pending_Leaves",
                    "Leave_Encashment_Rate",
                ]
                if c in employee_master.columns
            ]
            if em_cols:
                df = df.merge(
                    employee_master[em_cols],
                    on="Employee_ID",
                    how="left",
                    suffixes=("", "_master"),
                )

        if "Date_of_Joining" in df.columns:
            doj_mask = (df["Date_of_Joining"].dt.month == payroll_month) & (
                df["Date_of_Joining"].dt.year == payroll_year
            )
            doj_df = df[doj_mask].copy()

            if not doj_df.empty:
                for idx, row in doj_df.iterrows():
                    doj = row["Date_of_Joining"].date()
                    doj_payable_days = total_days - doj.day + 1

                    if "Payable_Days" in df.columns:
                        df.at[idx, "Payable_Days"] = float(doj_payable_days)

                    component_cols = ["Basic", "HRA", "Special_Allowance", "Bonus", "Incentive"]
                    for comp_col in component_cols:
                        if comp_col not in df.columns:
                            continue
                        monthly_amt = (
                            df.at[idx, comp_col] if pd.notna(df.at[idx, comp_col]) else 0
                        )
                        if monthly_amt == 0:
                            continue

                        expected_prorated = round(
                            monthly_amt * (doj_payable_days / total_days), 2
                        )
                        paid_col = f"Paid_{comp_col}"
                        if paid_col in df.columns:
                            paid_amt = (
                                df.at[idx, paid_col]
                                if pd.notna(df.at[idx, paid_col])
                                else 0
                            )
                            if abs(paid_amt - expected_prorated) > tol:
                                result.add_issue(
                                    ValidationIssue(
                                        employee_id=str(df.at[idx, "Employee_ID"]),
                                        employee_name=str(df.at[idx, "Employee_Name"]),
                                        flag=ValidationFlag.PRORATION_ERROR,
                                        severity=Severity.HIGH,
                                        description=(
                                            f"DOJ Joiner: {comp_col} ₹{paid_amt:.2f} ≠ expected "
                                            f"₹{expected_prorated:.2f} "
                                            f"({monthly_amt:.2f} × {doj_payable_days}/{total_days})"
                                        ),
                                        expected_value=expected_prorated,
                                        actual_value=paid_amt,
                                        difference=round(paid_amt - expected_prorated, 2),
                                        component=comp_col,
                                    )
                                )

        if "Last_Working_Day" in df.columns:
            lwd_mask = (df["Last_Working_Day"].dt.month == payroll_month) & (
                df["Last_Working_Day"].dt.year == payroll_year
            )
            lwd_df = df[lwd_mask].copy()

            if not lwd_df.empty:
                for idx, row in lwd_df.iterrows():
                    if "Leave_Encashment" in df.columns and "Pending_Leaves" in df.columns:
                        pending_leaves = (
                            df.at[idx, "Pending_Leaves"]
                            if pd.notna(df.at[idx, "Pending_Leaves"])
                            else 0
                        )
                        if pending_leaves > 0 and "Basic" in df.columns:
                            basic = df.at[idx, "Basic"] if pd.notna(df.at[idx, "Basic"]) else 0
                            daily_rate = basic / 26
                            expected_le = round(daily_rate * pending_leaves, 2)
                            actual_le = (
                                df.at[idx, "Leave_Encashment"]
                                if pd.notna(df.at[idx, "Leave_Encashment"])
                                else 0
                            )

                            if abs(actual_le - expected_le) > tol:
                                result.add_issue(
                                    ValidationIssue(
                                        employee_id=str(df.at[idx, "Employee_ID"]),
                                        employee_name=str(df.at[idx, "Employee_Name"]),
                                        flag=ValidationFlag.FNF_LEAVE_ENCASHMENT_ERROR,
                                        severity=Severity.HIGH,
                                        description=(
                                            f"Leave Encashment ₹{actual_le:.2f} ≠ expected "
                                            f"₹{expected_le:.2f} ({pending_leaves} leaves × Basic/26 "
                                            f"₹{daily_rate:.2f})"
                                        ),
                                        expected_value=expected_le,
                                        actual_value=actual_le,
                                        difference=round(actual_le - expected_le, 2),
                                        component="Leave_Encashment",
                                    )
                                )

        if all(c in df.columns for c in ["LOP_Days", "Payable_Days"]):
            df["LOP_Days"] = df["LOP_Days"].fillna(0)
            df["Payable_Days"] = df["Payable_Days"].fillna(total_days)

            is_regular = pd.Series(True, index=df.index)
            if "Date_of_Joining" in df.columns:
                is_joiner = (df["Date_of_Joining"].dt.month == payroll_month) & (
                    df["Date_of_Joining"].dt.year == payroll_year
                )
                is_regular = is_regular & ~is_joiner.fillna(False)
            if "Last_Working_Day" in df.columns:
                is_exiter = (df["Last_Working_Day"].dt.month == payroll_month) & (
                    df["Last_Working_Day"].dt.year == payroll_year
                )
                is_regular = is_regular & ~is_exiter.fillna(False)

            regular_df = df[is_regular].copy()
            regular_df["_expected_payable"] = (
                total_days - regular_df["LOP_Days"]
            ).clip(lower=0)

            payable_mismatch = (
                regular_df["Payable_Days"] - regular_df["_expected_payable"]
            ).abs() > 0.5
            for idx, row in regular_df[payable_mismatch].iterrows():
                result.add_issue(
                    ValidationIssue(
                        employee_id=str(row["Employee_ID"]),
                        employee_name=str(row["Employee_Name"]),
                        flag=ValidationFlag.LOP_MISMATCH,
                        severity=Severity.MEDIUM,
                        description=(
                            f"Payable days {row['Payable_Days']} ≠ {total_days} - "
                            f"LOP({row['LOP_Days']}) = {row['_expected_payable']}"
                        ),
                        expected_value=row["_expected_payable"],
                        actual_value=row["Payable_Days"],
                        difference=round(row["Payable_Days"] - row["_expected_payable"], 2),
                        component="Payable_Days",
                    )
                )

            negative_lop = df["LOP_Days"] < 0
            for idx, row in df[negative_lop].iterrows():
                result.add_issue(
                    ValidationIssue(
                        employee_id=str(row["Employee_ID"]),
                        employee_name=str(row["Employee_Name"]),
                        flag=ValidationFlag.NEGATIVE_LOP,
                        severity=Severity.CRITICAL,
                        description=f"Negative LOP days: {row['LOP_Days']}",
                        actual_value=row["LOP_Days"],
                        component="LOP_Days",
                    )
                )

        if "Bonus" in df.columns:
            df["Bonus"] = df["Bonus"].fillna(0)
            bonus_non_zero = df["Bonus"] > 0
            if bonus_non_zero.any() and "Payable_Days" in df.columns:
                bonus_with_proration = bonus_non_zero & (df["Payable_Days"] < total_days - 2)
                for idx, row in df[bonus_with_proration].iterrows():
                    result.add_issue(
                        ValidationIssue(
                            employee_id=str(row["Employee_ID"]),
                            employee_name=str(row["Employee_Name"]),
                            flag=ValidationFlag.PRORATION_ERROR,
                            severity=Severity.MEDIUM,
                            description=(
                                f"Bonus ₹{row['Bonus']:.2f} paid with partial month "
                                f"({row['Payable_Days']} days). Verify if pro-rated."
                            ),
                            actual_value=row["Bonus"],
                            component="Bonus",
                        )
                    )

        return result

    def _count_weekends(self, year: int, month: int) -> int:
        count = 0
        last_day = get_month_days(year, month)
        for day in range(1, last_day + 1):
            d = date(year, month, day)
            if d.weekday() in (5, 6):
                count += 1
        return count

    def _count_weekends_from(self, start_date: date, year: int, month: int) -> int:
        count = 0
        last_day = get_month_days(year, month)
        for day in range(start_date.day, last_day + 1):
            d = date(year, month, day)
            if d.weekday() in (5, 6):
                count += 1
        return count
