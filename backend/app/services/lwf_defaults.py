"""Curated Labour Welfare Fund (LWF) defaults per state.

Sourced from the Simpliance e-Library
(https://www.simpliance.in/India/LEI/labour_welfare_fund) and the underlying
state LWF Acts. Verified late-2025 / early-2026.

Each row carries:
  * `min_salary` / `max_salary`  — the wage band the slab applies to.
                                    Most states have a single all-wage band;
                                    Goa, Maharashtra, West Bengal etc. split
                                    by a wage threshold.
  * `deduction_amount`           — *employee* contribution per period.
  * `employer_amount`            — *employer* contribution per period.
  * `frequency`                  — `monthly`, `half-yearly`, or `yearly`. The
                                    validator scales wage to the same period
                                    and divides amounts by the same factor to
                                    produce a per-month equivalent.
  * `applicable_months`          — list[int] for the months in which a full
                                    contribution is due. A missing list keeps
                                    monthly-equivalent behavior for states
                                    whose collection month is unverified.

States with NO statutory LWF (Bihar, Jharkhand, Uttar Pradesh, Uttarakhand,
Himachal Pradesh, Jammu & Kashmir, Ladakh, Sikkim, all North-East states
except Tripura, and the smaller UTs) are intentionally absent.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal, TypedDict

Frequency = Literal["monthly", "yearly", "half-yearly", "quarterly"]


class DefaultLwfSlab(TypedDict, total=False):
    min_salary: Decimal
    max_salary: Decimal
    deduction_amount: Decimal
    employer_amount: Decimal
    frequency: Frequency
    applicable_months: list[int] | None
    effective_from: date | None
    source_reference: str | None


def _row(
    lo: float,
    hi: float,
    employee: float,
    employer: float,
    freq: Frequency = "half-yearly",
    months: list[int] | None = None,
    effective_from: date | None = None,
    source_reference: str | None = None,
) -> DefaultLwfSlab:
    return {
        "min_salary": Decimal(str(lo)),
        "max_salary": Decimal(str(hi)),
        "deduction_amount": Decimal(str(employee)),
        "employer_amount": Decimal(str(employer)),
        "frequency": freq,
        "applicable_months": months,
        "effective_from": effective_from,
        "source_reference": source_reference,
    }


_TOP = 99_999_999


LWF_DEFAULTS: dict[str, list[DefaultLwfSlab]] = {
    # ---------- Yearly contributions (Dec / Jan) ----------
    "Andhra Pradesh": [
        # Deducted in December; remitted by 31 Jan.
        _row(0, _TOP, 30, 70, freq="yearly"),
    ],
    "Karnataka": [
        # Karnataka Act 05 of 2025, published 10 Jan 2025, amended section 7A(2).
        # Employee ₹50 and employer ₹100 for the 31 December roster.
        # Employer remits by 15 January; validate the December payroll deduction.
        # https://klwb.karnataka.gov.in/storage/pdf-files/brouchernew.pdf
        _row(0, _TOP, 50, 100, freq="yearly", months=[12],
             effective_from=date(2025, 1, 10),
             source_reference="https://klwb.karnataka.gov.in/storage/pdf-files/brouchernew.pdf"),
    ],
    "Tamil Nadu": [
        # Annual contribution remitted by 31 Jan.
        _row(0, _TOP, 20, 40, freq="yearly"),
    ],
    "Telangana": [
        _row(0, _TOP, 2, 5, freq="yearly"),
    ],

    # ---------- Half-yearly contributions (Jun & Dec) ----------
    "Chhattisgarh": [
        _row(0, _TOP, 15, 45, freq="half-yearly"),
    ],
    "Delhi": [
        _row(0, _TOP, 0.75, 2.25, freq="half-yearly"),
    ],
    "Goa": [
        # Threshold ₹6500 splits the rate.
        _row(0, 6500, 60, 180, freq="half-yearly"),
        _row(6501, _TOP, 120, 360, freq="half-yearly"),
    ],
    "Gujarat": [
        _row(0, _TOP, 6, 12, freq="half-yearly"),
    ],
    "Madhya Pradesh": [
        _row(0, _TOP, 10, 30, freq="half-yearly"),
    ],
    "Maharashtra": [
        # Maharashtra Act XXV of 2024, section 6BB(2), gazetted 18 Mar 2024.
        # ₹25 employee and 3× employer for each June/December period; no wage band.
        # https://bombayhighcourt.gov.in/bhc/libweb/legislation/acts/Stateact/2024acts/2024.25.pdf
        _row(0, _TOP, 25, 75, freq="half-yearly", months=[6, 12],
             effective_from=date(2024, 3, 18),
             source_reference="https://bombayhighcourt.gov.in/bhc/libweb/legislation/acts/Stateact/2024acts/2024.25.pdf"),
    ],
    "Odisha": [
        _row(0, _TOP, 20, 40, freq="half-yearly"),
    ],
    "West Bengal": [
        _row(0, 3500, 3, 15, freq="half-yearly"),
        _row(3501, _TOP, 6, 18, freq="half-yearly"),
    ],

    # ---------- Monthly contributions ----------
    "Haryana": [
        # Revised vide notification dated 1 Jan 2024 (₹31 / ₹62 per month).
        _row(0, _TOP, 31, 62, freq="monthly"),
    ],
    "Kerala": [
        # Kerala Shops & Commercial Establishments Workers Welfare Fund.
        _row(0, _TOP, 50, 50, freq="monthly"),
    ],
    "Punjab": [
        _row(0, _TOP, 5, 20, freq="monthly"),
    ],
}


def list_default_states() -> list[str]:
    return sorted(LWF_DEFAULTS.keys())


def get_defaults(state: str) -> list[DefaultLwfSlab] | None:
    return LWF_DEFAULTS.get(state)
