"""Curated PT slab defaults per state, importable into a tenant's slab_rules.

Sourced from the Simpliance e-Library (https://www.simpliance.in/India/LEI/
professional_tax) and verified per state in late 2025 / early 2026.

Three slab frequencies are used:

  * `monthly`     — bracket compares against monthly wage; amount is per month.
  * `half-yearly` — bracket compares against half-yearly wage; amount is per
                    half-year (validator divides by 6 for monthly equivalent).
  * `yearly`      — bracket compares against annual wage; amount is per year
                    (validator divides by 12 for monthly equivalent).

Slabs may also carry:
  * `gender`            — "ALL" | "MALE" | "FEMALE"
  * `applicable_months` — list[int] (1..12) for month-specific rows
                          (e.g. Maharashtra / Karnataka February top-up); None
                          means the row applies in every month.

Special cases:
  * **Maharashtra** — male and female slabs differ; in February employers
    deduct ₹300 instead of ₹200 so the annual cap of ₹2 500 is hit.
  * **Karnataka** — Apr-2025 Amendment Act (exemption raised to ₹25,000);
    Feb +₹100 surcharge encoded as a Feb-only row.
  * **Punjab / Tripura** — statutory text expresses the amount as a per-month
    figure even though the income bracket is annualized. To make the engine's
    `yearly` frequency math come out right, these rows store the *annualised*
    amount (e.g. ₹200/month → ₹2400/year) so deduction ÷ 12 = correct monthly.
  * States with no PT (Delhi, Haryana, Rajasthan, UP, Uttarakhand, HP, J&K,
    Ladakh, Goa, Arunachal Pradesh, Chandigarh, A&N, D&D, DNH, Lakshadweep)
    are intentionally absent.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Literal, TypedDict

Frequency = Literal["monthly", "yearly", "half-yearly", "quarterly"]
Gender = Literal["ALL", "MALE", "FEMALE"]


class DefaultSlab(TypedDict, total=False):
    min_salary: Decimal
    max_salary: Decimal
    deduction_amount: Decimal
    frequency: Frequency
    gender: Gender
    applicable_months: list[int] | None


def _row(
    lo: float,
    hi: float,
    amt: float,
    freq: Frequency = "monthly",
    gender: Gender = "ALL",
    months: list[int] | None = None,
) -> DefaultSlab:
    return {
        "min_salary": Decimal(str(lo)),
        "max_salary": Decimal(str(hi)),
        "deduction_amount": Decimal(str(amt)),
        "frequency": freq,
        "gender": gender,
        "applicable_months": months,
    }


# Open-ended top brackets are capped at this monetary value so the validator
# never falls off the end of the catalog for very high earners.
_TOP = 99_999_999


PT_DEFAULTS: dict[str, list[DefaultSlab]] = {
    # ---------- Monthly basis ----------
    "Andhra Pradesh": [
        _row(0, 15000, 0),
        _row(15001, 20000, 150),
        _row(20001, _TOP, 200),
    ],
    "Assam": [
        _row(0, 15000, 0),
        _row(15001, 25000, 180),
        _row(25001, _TOP, 208),
    ],
    "Chhattisgarh": [
        _row(0, 15000, 0),
        _row(15001, 20000, 150),
        _row(20001, _TOP, 208),
    ],
    "Gujarat": [
        _row(0, 12000, 0),
        _row(12001, _TOP, 200),
    ],
    "Karnataka": [
        # Karnataka PT (Amendment) Act, 2025 — exemption raised to ₹25,000/month.
        _row(0, 24999, 0),
        _row(25000, _TOP, 200),
        # February top-up so annual cap of ₹2,500 is reached
        # (₹200 × 11 + ₹300 × 1 = ₹2,500).
        _row(25000, _TOP, 300, months=[2]),
    ],
    "Maharashtra": [
        # --- Male employees ---
        _row(0, 7500, 0, gender="MALE"),
        _row(7501, 10000, 175, gender="MALE"),
        _row(10001, _TOP, 200, gender="MALE"),
        # February top-up for males above ₹10,000 → ₹300 once a year
        # (₹200 × 11 + ₹300 = ₹2,500 annual cap).
        _row(10001, _TOP, 300, gender="MALE", months=[2]),
        # --- Female employees ---
        _row(0, 25000, 0, gender="FEMALE"),
        _row(25001, _TOP, 200, gender="FEMALE"),
        _row(25001, _TOP, 300, gender="FEMALE", months=[2]),
    ],
    "Mizoram": [
        _row(1, 5000, 0),
        _row(5001, 8000, 75),
        _row(8001, 10000, 120),
        _row(10001, 12000, 150),
        _row(12001, 15000, 180),
        _row(15001, 20000, 195),
        _row(20001, _TOP, 208),
    ],
    "Nagaland": [
        _row(0, 4000, 0),
        _row(4001, 5000, 35),
        _row(5001, 7000, 75),
        _row(7001, 9000, 110),
        _row(9001, 12000, 180),
        _row(12001, _TOP, 208),
    ],
    "Sikkim": [
        _row(0, 20000, 0),
        _row(20001, 30000, 125),
        _row(30001, 40000, 150),
        _row(40001, _TOP, 200),
    ],
    "Telangana": [
        _row(0, 15000, 0),
        _row(15001, 20000, 150),
        _row(20001, _TOP, 200),
    ],
    "West Bengal": [
        _row(0, 8500, 0),
        _row(8501, 10000, 0),
        _row(10001, 15000, 110),
        _row(15001, 25000, 130),
        _row(25001, 40000, 150),
        _row(40001, _TOP, 200),
    ],

    # ---------- Half-yearly basis ----------
    "Kerala": [
        _row(0, 11999, 0, "half-yearly"),
        _row(12000, 17999, 320, "half-yearly"),
        _row(18000, 29999, 450, "half-yearly"),
        _row(30000, 44999, 600, "half-yearly"),
        _row(45000, 99999, 750, "half-yearly"),
        _row(100000, 124999, 1000, "half-yearly"),
        _row(125000, _TOP, 1250, "half-yearly"),
    ],
    "Puducherry": [
        _row(0, 99999, 0, "half-yearly"),
        _row(100000, 200000, 250, "half-yearly"),
        _row(200001, 300000, 500, "half-yearly"),
        _row(300001, 400000, 750, "half-yearly"),
        _row(400001, 500000, 1000, "half-yearly"),
        _row(500001, _TOP, 1250, "half-yearly"),
    ],
    "Tamil Nadu": [
        _row(1, 21000, 0, "half-yearly"),
        _row(21001, 30000, 180, "half-yearly"),
        _row(30001, 45000, 425, "half-yearly"),
        _row(45001, 60000, 930, "half-yearly"),
        _row(60001, 75000, 1025, "half-yearly"),
        _row(75001, _TOP, 1250, "half-yearly"),
    ],

    # ---------- Yearly basis ----------
    "Bihar": [
        _row(0, 300000, 0, "yearly"),
        _row(300001, 500000, 1000, "yearly"),
        _row(500001, 1000000, 2000, "yearly"),
        _row(1000001, _TOP, 2500, "yearly"),
    ],
    "Jharkhand": [
        _row(0, 300000, 0, "yearly"),
        _row(300001, 500000, 1200, "yearly"),
        _row(500001, 800000, 1800, "yearly"),
        _row(800001, 1000000, 2100, "yearly"),
        _row(1000001, _TOP, 2500, "yearly"),
    ],
    "Madhya Pradesh": [
        _row(0, 225000, 0, "yearly"),
        _row(225001, 300000, 1500, "yearly"),
        _row(300001, 400000, 2000, "yearly"),
        _row(400001, _TOP, 2500, "yearly"),
    ],
    "Manipur": [
        _row(0, 50000, 0, "yearly"),
        _row(50001, 75000, 1200, "yearly"),
        _row(75001, 100000, 2000, "yearly"),
        _row(100001, 125000, 2400, "yearly"),
        _row(125001, _TOP, 2500, "yearly"),
    ],
    "Meghalaya": [
        _row(0, 50000, 0, "yearly"),
        _row(50001, 75000, 200, "yearly"),
        _row(75001, 100000, 300, "yearly"),
        _row(100001, 150000, 500, "yearly"),
        _row(150001, 200000, 750, "yearly"),
        _row(200001, 250000, 1000, "yearly"),
        _row(250001, 300000, 1250, "yearly"),
        _row(300001, 350000, 1500, "yearly"),
        _row(350001, 400000, 1800, "yearly"),
        _row(400001, 450000, 2100, "yearly"),
        _row(450001, 500000, 2400, "yearly"),
        _row(500001, _TOP, 2500, "yearly"),
    ],
    "Odisha": [
        _row(0, 160000, 0, "yearly"),
        _row(160001, 300000, 1500, "yearly"),
        _row(300001, _TOP, 2400, "yearly"),
    ],
    "Punjab": [
        # Punjab State Development Tax: ₹200/month for those above the IT
        # threshold. Stored as annualised so 2400 ÷ 12 = 200/month (Old Regime).
        _row(0, 250000, 0, "yearly"),
        _row(250001, _TOP, 2400, "yearly"),
    ],
    "Tripura": [
        # Brackets are monthly salary; deductions are per month. (Simpliance
        # surfaces the annualised totals ₹1800/₹2496 in its rate column but
        # the underlying statute is per-month at ₹150 / ₹208.)
        _row(0, 7500, 0),
        _row(7501, 15000, 150),
        _row(15001, _TOP, 208),
    ],
}


def list_default_states() -> list[str]:
    return sorted(PT_DEFAULTS.keys())


def get_defaults(state: str) -> list[DefaultSlab] | None:
    return PT_DEFAULTS.get(state)
