"""
Synthetic payroll for load tests and demonstrations.

    python tools/synthetic_payroll.py --employees 8000 --out /tmp/synthetic

Writes an employee master, a June attendance register and a June salary
register for N fictitious employees, plus ``expected.json``: the findings the
planted defects must produce, **computed here from first principles** rather
than by calling the engine. A benchmark that validated its data with the code
under test would only prove the code agrees with itself.

What is planted, and why each expectation holds:

* **PF under-deducted** (every 97th employee, offset 5). Employee PF is 12% of
  PF wages — Basic plus Special Allowance, the components flagged PF-applicable
  — capped at the ₹15,000 ceiling. The register states ₹100 less. The
  shortfall exceeds the ₹1 tolerance, so STAT-001 must fire for exactly these.
* **ESIC over-deducted** (every 89th ESIC-eligible employee, offset 7). ESIC
  applies when ESIC wages — every earning here — are at most ₹21,000; the
  employee share is 0.75%, rounded up. The register states ₹40 more, so
  STAT-006 must fire for exactly these.
* **Paid days that do not add up** (every 101st employee, offset 11). June has
  30 days; the register states 29 paid and 0 LOP, so LOP-001 must fire for
  exactly these.

Everyone else is computed correctly, which is what makes "exactly these" a
testable claim: any extra STAT-001, STAT-006 or LOP-001 is a false positive.

The names, PANs and UANs are generated and belong to nobody. PANs follow the
format with 'P' as the fourth character; UANs are twelve digits.
"""
from __future__ import annotations

import argparse
import json
import math
import random
from dataclasses import dataclass
from datetime import date
from pathlib import Path

PERIOD = date(2026, 6, 1)
PRIOR = date(2026, 5, 1)
DAYS = 30

COMPONENTS = [
    {"component_name": "Basic", "pf_applicable": True, "esic_applicable": True,
     "pt_applicable": True, "lwf_applicable": True, "included_in_wages": True, "taxable": True},
    {"component_name": "HRA", "esic_applicable": True, "pt_applicable": True, "taxable": True},
    {"component_name": "Special Allowance", "pf_applicable": True, "esic_applicable": True,
     "pt_applicable": True, "taxable": True},
    {"component_name": "Conveyance", "esic_applicable": True, "pt_applicable": True,
     "taxable": True},
]

DEPARTMENTS = ["Engineering", "Sales", "Operations", "Finance", "HR", "Support", "Logistics"]
STATES = ["Karnataka", "Maharashtra"]
FIRST = ["Asha", "Rahul", "Priya", "Imran", "Devika", "Sanjay", "Meera", "Vikram", "Fatima",
         "Arjun", "Kavya", "Nikhil", "Sneha", "Farhan", "Lakshmi", "Rohan", "Zara", "Manoj"]
LAST = ["Menon", "Verma", "Nair", "Shaikh", "Rao", "Kulkarni", "Iyer", "Desai", "Khan",
        "Pillai", "Reddy", "Joshi", "Gupta", "Das", "Bose", "Patel", "Singh", "Mehta"]
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


@dataclass
class Employee:
    employee_id: str
    name: str
    gender: str
    state: str
    department: str
    basic: int
    pan: str
    uan: str
    esic_ip: str

    @property
    def hra(self) -> int:
        return round(self.basic * 0.4)

    @property
    def special(self) -> int:
        return round(self.basic * 0.25)

    conveyance = 1600

    @property
    def gross(self) -> int:
        return self.basic + self.hra + self.special + self.conveyance

    @property
    def pf_wage(self) -> int:
        return self.basic + self.special

    def pf_employee(self) -> int:
        return round(min(self.pf_wage, 15000) * 0.12)

    @property
    def esic_eligible(self) -> bool:
        return self.gross <= 21000

    def esic_employee(self) -> int:
        return math.ceil(self.gross * 0.0075) if self.esic_eligible else 0

    def esic_employer(self) -> int:
        return math.ceil(self.gross * 0.0325) if self.esic_eligible else 0


def _pan(rng: random.Random) -> str:
    return (
        "".join(rng.choice(LETTERS) for _ in range(3)) + "P" + rng.choice(LETTERS)
        + f"{rng.randint(0, 9999):04d}" + rng.choice(LETTERS)
    )


def build(n: int, seed: int = 2026) -> list[Employee]:
    rng = random.Random(seed)
    staff = []
    for i in range(n):
        # A quarter are low-paid enough to be ESIC-eligible; the rest spread
        # up to senior salaries, so the PF ceiling is exercised both ways.
        basic = rng.randint(8000, 11500) if i % 4 == 0 else rng.randint(12000, 95000)
        staff.append(Employee(
            employee_id=f"S{i + 1:06d}",
            name=f"{rng.choice(FIRST)} {rng.choice(LAST)}",
            gender=rng.choice("MF"),
            state=STATES[i % len(STATES)],
            department=DEPARTMENTS[i % len(DEPARTMENTS)],
            basic=basic,
            pan=_pan(rng),
            uan=f"{rng.randint(10**11, 10**12 - 1)}",
            esic_ip=f"{rng.randint(10**9, 10**10 - 1)}",
        ))
    return staff


def planted(staff: list[Employee]) -> dict[str, set[str]]:
    eligible = [e for e in staff if e.esic_eligible]
    return {
        "STAT-001": {e.employee_id for i, e in enumerate(staff) if i % 97 == 5},
        "STAT-006": {e.employee_id for i, e in enumerate(eligible) if i % 89 == 7},
        "LOP-001": {e.employee_id for i, e in enumerate(staff) if i % 101 == 11},
    }


def master_csv(staff: list[Employee]) -> str:
    lines = ["employee_id,employee_name,gender,date_of_joining,date_of_exit,work_state,"
             "department,cost_center,designation,employment_type,uan,esic_ip_number"]
    for e in staff:
        lines.append(f"{e.employee_id},{e.name},{e.gender},2022-04-01,,{e.state},"
                     f"{e.department},CC-{e.department[:3].upper()},Associate,Permanent,"
                     f"{e.uan},{e.esic_ip if e.esic_eligible else ''}")
    return "\n".join(lines) + "\n"


def attendance_csv(staff: list[Employee]) -> str:
    lines = ["employee_id,employee_name,calendar_days,present_days,paid_leave_days,"
             "weekly_off_days,holiday_days,lop_days,paid_days,overtime_hours"]
    for e in staff:
        lines.append(f"{e.employee_id},{e.name},{DAYS},{DAYS - 5},0,4,1,0,{DAYS},0")
    return "\n".join(lines) + "\n"


def register_csv(staff: list[Employee], plant: dict[str, set[str]] | None = None) -> str:
    """A month's register. ``plant`` None gives a clean month (used for May)."""
    plant = plant or {"STAT-001": set(), "STAT-006": set(), "LOP-001": set()}
    lines = ["employee_id,employee_name,state,department,paid_days,lop_days,basic,hra,"
             "special allowance,conveyance,pf_employee,pf_employer,esic_employee,esic_employer,"
             "pan,uan,esi_number,net_pay"]
    for e in staff:
        pf = e.pf_employee()
        pf_stated = pf - 100 if e.employee_id in plant["STAT-001"] else pf
        esic_ee = e.esic_employee()
        esic_stated = esic_ee + 40 if e.employee_id in plant["STAT-006"] else esic_ee
        paid = DAYS - 1 if e.employee_id in plant["LOP-001"] else DAYS
        net = e.gross - pf_stated - esic_stated
        lines.append(
            f"{e.employee_id},{e.name},{e.state},{e.department},{paid},0,"
            f"{e.basic},{e.hra},{e.special},{e.conveyance},{pf_stated},{pf},"
            f"{esic_stated},{e.esic_employer()},{e.pan},{e.uan},"
            f"{e.esic_ip if e.esic_eligible else ''},{net}"
        )
    return "\n".join(lines) + "\n"


def generate(n: int, seed: int = 2026) -> dict:
    staff = build(n, seed)
    plant = planted(staff)
    return {
        "period_month": PERIOD.isoformat(),
        "components": COMPONENTS,
        "master_csv": master_csv(staff),
        "attendance_csv": attendance_csv(staff),
        "register_csv": register_csv(staff, plant),
        "prior_period_month": PRIOR.isoformat(),
        "prior_register_csv": register_csv(staff),
        "expected": {rule: sorted(ids) for rule, ids in plant.items()},
        "employees": n,
        "esic_eligible": sum(1 for e in staff if e.esic_eligible),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--employees", type=int, default=8000)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    data = generate(args.employees, args.seed)
    args.out.mkdir(parents=True, exist_ok=True)
    for key in ("master_csv", "attendance_csv", "register_csv"):
        (args.out / key.replace("_csv", ".csv")).write_text(data[key])
    (args.out / "expected.json").write_text(json.dumps(
        {k: data[k] for k in ("period_month", "components", "expected", "employees", "esic_eligible")},
        indent=2,
    ))
    print(f"wrote {args.employees} employees to {args.out}")


if __name__ == "__main__":
    main()
