"""Builds the manual-test pack for the payroll validation module.

    cd backend && PYTHONPATH=. python ../testdata/payroll-validation/generate.py

Writes five files next to this script, for the period August 2026 (31 days):

    1_configuration.csv      one file that sets up the whole entity (Configuration upload)
    2_employee_master.csv    who works here, joining/exit dates, state, gender
    3_ctc_report.csv         annual CTC per employee, by salary component
    4_attendance_report.csv  days present / leave / LOP for the month
    5_salary_register.csv    what payroll paid -- with deliberate mistakes
    6_previous_month_register_july.csv   last month's clean register, for month-on-month checks

The mistakes are listed in ANSWER_KEY (also written to README.md), so a tester
knows exactly what the tool should and should not report. Everything is
deterministic: running this twice produces byte-identical files.
"""
from __future__ import annotations

import csv
import json
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from pathlib import Path

from app.routers.config_bundle import _to_csv
from app.services.identity_checks import _verhoeff_valid
from app.services.income_tax_engine import compute_income_tax
from app.services.tax_year_defaults import default_tax_years

HERE = Path(__file__).parent
PERIOD = "2026-08-01"
DAYS = 31
D = Decimal


def rnd(x) -> int:
    return int(D(x).quantize(D("1"), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------- configuration
COMPONENTS = [
    # name, pf, esic, pt
    ("Basic", True, True, True),
    ("HRA", False, True, True),
    ("Special Allowance", True, True, True),
    ("Conveyance", False, True, True),
    ("Overtime", False, False, True),
]


def configuration_csv() -> str:
    sections = {
        "components": [
            {"component_name": n, "pf_applicable": pf, "esic_applicable": es, "pt_applicable": pt,
             "lwf_applicable": False, "bonus_applicable": n == "Basic", "included_in_wages": True,
             "taxable": True, "tax_exemption_type": "none"}
            for n, pf, es, pt in COMPONENTS
        ],
        "statutory_settings": [{
            "pf_wage_ceiling": 25000, "pf_employee_rate": 0.12, "pf_employer_rate": 0.12,
            "pf_eps_rate": 0.0833, "pf_edli_rate": 0.005, "pf_admin_rate": 0.005,
            "pf_restrict_to_ceiling": True, "esic_wage_ceiling": 21000,
            "esic_employee_rate": 0.0075, "esic_employer_rate": 0.0325, "esic_round_mode": "up",
            "pt_states": ["Karnataka", "Maharashtra"], "lwf_states": [],
        }],
        "statutory_engine": [{
            "pf_config": {"wage": {"wage_ceiling": "25000", "restrict_to_ceiling": True,
                                   "use_pf_applicable_flag": True}},
            "esic_config": {"wage": {"wage_ceiling": "21000", "use_esic_applicable_flag": True},
                            "rounding": {"mode": "up"}},
            "component_mapping_config": None, "income_tax_config": None,
            "rule_thresholds_config": None, "exposure_config": None,
        }],
        "formulas": [
            {"rule_type": "PF", "name": "Lower-paid employees use Basic + Special Allowance",
             "expression": "IF(basic <= 25000, MIN((basic + special_allowance) * 12%, 3000), basic * 12%)",
             "conditions": [], "version": 1, "is_active": True},
            {"rule_type": "ESIC", "name": "0.75% of ESIC wage, rounded up",
             "expression": "IF(esic_wage <= 21000, ROUNDUP(esic_wage * 0.75%, 0), 0)",
             "conditions": [], "version": 1, "is_active": True},
        ],
        # Test values only -- check the governing notification before using real ones.
        "pt_lwf_slabs": [
            _slab("Karnataka", 0, 24999, 0, 1),
            _slab("Karnataka", 25000, 99999999, 200, 2),
            _slab("Maharashtra", 0, 7500, 0, 3),
            _slab("Maharashtra", 7501, 10000, 175, 4),
            _slab("Maharashtra", 10001, 99999999, 200, 5),
        ],
        "minimum_wage_rates": [], "rule_preferences": [],
        "minimum_wage_applicability": [{
            "effective_from": "2024-04-01", "applicable": False,
            "reason": "Test data: treated as not a scheduled employment", "source_reference": "test pack"}],
        "salary_import_profiles": [{
            "name": "Test payroll export",
            "column_mapping": {"Emp Code": "employee_id", "Emp Name": "employee_name"},
        }],
        "bank_file_profiles": [], "jv_templates": [], "jv_rules": [],
    }
    # The sections the validation module does not use are written empty-by-omission:
    # leaving a section out leaves the entity's existing setting untouched.
    for unused in ("minimum_wage_rates", "rule_preferences",
                   "bank_file_profiles", "jv_templates", "jv_rules", "salary_import_profiles"):
        sections.pop(unused)
    return _to_csv({"sections": sections})


def _slab(state, lo, hi, amount, order):
    return {"state": state, "rule_type": "PT", "min_salary": lo, "max_salary": hi,
            "deduction_amount": amount, "employer_amount": None, "frequency": "monthly",
            "gender": "ALL", "applicable_months": None, "effective_from": "2024-04-01",
            "effective_to": None, "source_reference": "TEST DATA - verify before real use",
            "sort_order": order}


# --------------------------------------------------------------------------- people
FIRST = ["Asha", "Rahul", "Priya", "Vikram", "Neha", "Arjun", "Sneha", "Karthik", "Divya", "Rohan",
         "Meera", "Sanjay", "Pooja", "Aditya", "Kavya", "Manish", "Anita", "Suresh", "Lakshmi", "Nikhil"]
LAST = ["Menon", "Verma", "Nair", "Singh", "Patil", "Reddy", "Iyer", "Gupta", "Shetty", "Kulkarni"]

# basic by position; spread across the PF ceiling (25,000) and the ESIC ceiling (21,000 gross)
BASICS = [7000, 8000, 9000, 10000, 11000, 12000, 13000, 14000, 15000, 16000, 17000, 18000,
          20000, 22000, 24000, 25000, 26000, 28000, 30000, 32000, 35000, 38000, 40000, 45000,
          50000, 55000, 60000, 65000, 70000, 80000]


def people() -> list[dict]:
    out = []
    for i in range(1, 41):
        basic = BASICS[(i - 1) % len(BASICS)] + (i // len(BASICS)) * 500
        out.append({
            "id": f"E{i:03d}",
            "name": f"{FIRST[(i - 1) % 20]} {LAST[(i * 3) % 10]}",
            "state": "Karnataka" if i % 3 else "Maharashtra",
            "gender": "Female" if i % 2 == 0 else "Male",
            "doj": f"{2018 + i % 7}-0{1 + i % 9}-15",
            "dept": ["Finance", "Operations", "Sales", "Engineering"][i % 4],
            "basic": basic,
            "hra": rnd(D(basic) * D("0.4")),
            "special": rnd(D(basic) * D("0.35")),
            "conv": 1600 if basic >= 10000 else 0,
            "lop": 0, "ot_hours": 0,
        })
    return out


# a few people have realistic variety
def tweak(p: dict[str, dict]) -> None:
    p["E003"]["lop"] = 2
    p["E007"]["lop"] = 1.5
    p["E012"]["lop"] = 4
    p["E018"]["ot_hours"] = 10
    p["E022"]["ot_hours"] = 12
    p["E036"]["ot_hours"] = 8
    p["E031"]["doj"] = "2026-08-20"        # joined this month
    p["E030"]["dox"] = "2026-07-31"        # left last month


def statutory(row: dict, p: dict) -> dict:
    """What payroll *should* have deducted for a person, given the pack's configuration."""
    paid = DAYS - D(str(p["lop"]))
    ratio = paid / DAYS
    e = {k: rnd(D(p[k]) * ratio) for k in ("basic", "hra", "special", "conv")}
    e["ot"] = rnd(D(2 * p["ot_hours"]) * D(sum(e.values())) / DAYS / 8 + D("0.5")) if p["ot_hours"] else 0
    gross = sum(e.values())
    pf_wage = min(e["basic"] + e["special"], 25000)
    pf = rnd(D(pf_wage) * D("0.12"))
    esic_wage = e["basic"] + e["hra"] + e["special"] + e["conv"]
    esic = int((D(esic_wage) * D("0.0075")).to_integral_value(rounding=ROUND_CEILING)) if esic_wage <= 21000 else 0
    pt_amount = (200 if gross >= 25000 else 0) if p["state"] == "Karnataka" else (
        0 if gross <= 7500 else 175 if gross <= 10000 else 200)
    return {"paid": paid, "earn": e, "gross": gross, "pf": pf, "esic": esic, "pt": pt_amount}


def aadhaar(n: int) -> str:
    """A syntactically valid Aadhaar (starts 2-9, Verhoeff check digit) -- not a real person's."""
    base = f"2345{n:07d}"
    return next(base + str(d) for d in range(10) if _verhoeff_valid(base + str(d)))


def monthly_tds(gross: int) -> int:
    """What the product's own Section 192 projection expects (new regime, FY 2026-27)."""
    year = default_tax_years()["2026-27"]
    return rnd(compute_income_tax(annual_gross=float(gross) * 12, regime="new", year_cfg=year).monthly_tds)


HEADERS = ["Employee ID", "Employee Name", "UAN", "ESI Number", "PAN", "Aadhaar", "Date of Birth",
           "Date of Joining", "State", "Total Days", "Paid Days", "LOP Days", "Basic", "HRA",
           "Special Allowance", "Conveyance", "Overtime", "Gross", "PF Employee", "ESIC Employee", "PT",
           "TDS", "Total Deductions", "Net"]


def register_row(p: dict, s: dict) -> dict:
    e = s["earn"]
    tds = monthly_tds(s["gross"])
    ded = s["pf"] + s["esic"] + s["pt"] + tds
    return {
        "Employee ID": p["id"], "Employee Name": p["name"], "State": p["state"], "Total Days": DAYS,
        "UAN": f"1012026{int(p['id'][1:]):05d}", "ESI Number": f"3100{int(p['id'][1:]):06d}",
        "PAN": f"ABCPK{int(p['id'][1:]):04d}Z", "Aadhaar": aadhaar(int(p["id"][1:])),
        "Date of Birth": f"{1980 + int(p['id'][1:]) % 15}-0{1 + int(p['id'][1:]) % 9}-10",
        "Date of Joining": p["doj"],
        "Paid Days": float(s["paid"]) if s["paid"] % 1 else int(s["paid"]), "LOP Days": p["lop"],
        "Basic": e["basic"], "HRA": e["hra"], "Special Allowance": e["special"], "Conveyance": e["conv"],
        "Overtime": e["ot"], "Gross": s["gross"], "PF Employee": s["pf"], "ESIC Employee": s["esic"],
        "PT": s["pt"], "TDS": tds, "Total Deductions": ded, "Net": s["gross"] - ded,
    }


def build():
    ppl = {p["id"]: p for p in people()}
    tweak(ppl)
    rows, ctc, att, master = [], [], [], []
    key: list[tuple[str, str]] = []
    gaps: list[tuple[str, str]] = []
    for pid, p in ppl.items():
        s = statutory(None, p)
        r = register_row(p, s)

        def mistake(why, **changes):
            r.update(changes)
            r["Total Deductions"] = r["PF Employee"] + r["ESIC Employee"] + r["PT"] + r["TDS"]
            if "Net" not in changes:
                r["Net"] = r["Gross"] - r["Total Deductions"]
            key.append((pid, why))

        if pid == "E005":
            mistake("PF not deducted at all (PF Employee = 0)", **{"PF Employee": 0})
        elif pid == "E021":
            mistake("PF deducted on full Basic above the ceiling (12% of the whole wage, not capped at 25,000)",
                    **{"PF Employee": rnd(D(p["basic"] + p["special"]) * D("0.12"))})
        elif pid == "E004":
            mistake("ESIC not deducted although ESIC wage is within 21,000", **{"ESIC Employee": 0})
        elif pid == "E019":
            mistake("ESIC deducted although ESIC wage is above 21,000", **{"ESIC Employee": 180})
        elif pid == "E015":
            mistake("Professional tax missing for a Karnataka employee earning above 25,000", **{"PT": 0})
        elif pid == "E024":
            mistake("Professional tax is 150, the Karnataka slab says 200", **{"PT": 150})
        elif pid == "E026":
            mistake("Gross does not equal the sum of the earnings", **{"Gross": r["Gross"] + 1500})
            r["Net"] = r["Gross"] - r["Total Deductions"]
        elif pid == "E027":
            mistake("Net does not equal Gross minus Total Deductions", **{"Net": r["Net"] + 900})
        elif pid == "E028":
            mistake("Paid days (31) disagree with the attendance report (28)", **{"Paid Days": 31, "LOP Days": 0})
        elif pid == "E029":
            mistake("Basic is 5,000 higher than the CTC letter allows",
                    **{"Basic": r["Basic"] + 5000, "Gross": r["Gross"] + 5000})
            r["Net"] = r["Gross"] - r["Total Deductions"]
        elif pid == "E030":
            key.append((pid, "Paid in August after the exit date of 31 Jul 2026"))
        elif pid == "E031":
            gaps.append((pid, "Joined 20 Aug 2026 but paid a full month of 31 days"))
        elif pid == "E033":
            key.append((pid, "Salary lines appear twice in the register (duplicate row)"))
        elif pid == "E036":
            mistake("8 overtime hours in attendance but no overtime paid", Overtime=0,
                    Gross=r["Gross"] - r["Overtime"])
            r["Net"] = r["Gross"] - r["Total Deductions"]

        rows.append(r)
        if pid == "E033":
            rows.append(dict(r))

        master.append({
            "Employee ID": pid, "Employee Name": p["name"], "Date of Joining": p["doj"],
            "Date of Exit": p.get("dox", ""), "Gender": p["gender"], "State": p["state"],
            "Department": p["dept"], "Employment Type": "Permanent",
            "UAN": f"1012026{int(pid[1:]):05d}", "ESIC IP Number": f"3100{int(pid[1:]):06d}",
        })

        full = {k: p[k] * 12 for k in ("basic", "hra", "special", "conv")}
        ctc.append({
            "Employee ID": pid, "Employee Name": p["name"], "Effective From": "2026-04-01",
            "Basic": full["basic"], "HRA": full["hra"], "Special Allowance": full["special"],
            "Conveyance": full["conv"], "Annual CTC": sum(full.values()),
        })

        lop = D(str(p["lop"]))
        present = DAYS - lop - 4 - 1       # 4 weekly offs, 1 holiday
        arow = {"Employee ID": pid, "Employee Name": p["name"], "Total Days": DAYS, "Present Days": float(present),
                "Paid Leave Days": 0, "Weekly Off Days": 4, "Holiday Days": 1,
                "LOP Days": float(lop), "Paid Days": float(DAYS - lop),
                "Overtime Hours": p["ot_hours"]}
        if pid == "E028":
            arow.update({"Present Days": 23, "LOP Days": 3, "Paid Days": 28})
        if pid == "E037":                                       # attendance that does not add up
            arow.update({"Present Days": 20, "Paid Days": 31, "LOP Days": 0})
            key.append((pid, "Attendance file contradicts itself: 20 present + 4 off + 1 holiday does not reach 31"))
        if pid == "E040":
            key.append((pid, "On the attendance report and in the register, but NOT in the employee master"))
        att.append(arow)

    previous = []
    for pid, p in ppl.items():
        if pid in ("E031", "E040"):          # E031 joined in August; E040 is not an employee
            continue
        q = dict(p, lop=0, ot_hours=0)
        previous.append(register_row(q, statutory(None, q)))
    # E040 is in register + attendance but missing from the master (a ghost)
    master[:] = [m for m in master if m["Employee ID"] != "E040"]
    # E038 is in the master and attendance but missing from the register
    rows = [r for r in rows if r["Employee ID"] != "E038"]
    key.append(("E038", "On the attendance report and master, but missing from the salary register"))
    return rows, master, ctc, att, key, gaps, previous


def write(name: str, rows: list[dict], headers: list[str] | None = None) -> None:
    with open(HERE / name, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=headers or list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def readme(key, gaps) -> str:
    gap_rows = "\n".join(f"| {pid} | {why} |" for pid, why in gaps)
    rows = "\n".join(f"| {pid} | {why} |" for pid, why in sorted(key))
    return f"""# Payroll validation manual-test pack (August 2026)

Dummy data for testing the Payroll Validation module end to end. Nothing here is real.
Regenerate with `cd backend && PYTHONPATH=. python ../testdata/payroll-validation/generate.py`.

## Load order (about 5 minutes)

| Step | Where | File |
| --- | --- | --- |
| 1 | Configuration & admin -> **Configuration upload** (preview, then apply) | `1_configuration.csv` |
| 2 | Data & imports -> **Employee master** (effective 2026-04-01) | `2_employee_master.csv` |
| 3 | Data & imports -> **CTC upload** (effective 2026-04-01) | `3_ctc_report.csv` |
| 4 | Data & imports -> **Attendance** (period August 2026) | `4_attendance_report.csv` |
| 5 | Data & imports -> **Salary register**, period **July 2026**, then Run validation (this is last month, so August can be compared with it) | `6_previous_month_register_july.csv` |
| 6 | Data & imports -> **Salary register**, period **August 2026**, then Run validation. Open Results | `5_salary_register.csv` |

Step 1 is the *one-file* setup: salary components and their PF/ESIC/PT flags, PF ceiling 25,000,
ESIC ceiling 21,000, PT states and slabs, and the PF/ESIC formulas in Excel style. It replaces only
the sections it contains.

## Rules in the configuration

* PF: employee 12% of (Basic + Special Allowance), wage capped at 25,000 (so at most 3,000).
* ESIC: 0.75% of ESIC wage (Basic, HRA, Special Allowance, Conveyance) rounded up, only while that wage is 21,000 or less.
* PT: Karnataka 200 from 25,000 gross; Maharashtra 175 from 7,501 and 200 above 10,000 (test values).
* The saved PF/ESIC *formulas* are stored for the Formula builder; validation currently uses the PF/ESIC settings above.

## Answer key -- what the tool should report

Everyone not listed here is correct and should produce **no** finding for the issues named below.

| Employee | Planted problem |
| --- | --- |
{rows}

Employees E003, E007 and E012 have loss of pay, and E018 and E022 have overtime that is
supported by attendance; they are correct and are there to prove the tool does not over-report.

Attendance file only (shown when you validate/commit the attendance report, not in the salary run):
E037 -- present + weekly off + holiday days do not add up to the 31 calendar days.

### Expected background findings (not mistakes)

* `STAT-005` ESIC ineligible (INFO) for everyone above the ESIC ceiling -- it confirms the rule was applied.
* `MOM-001` new joiner for E031 (joined in August) and E040 (not in July) -- correct, they have no July payslip.
* `TDS-002` for E029 -- a knock-on of the higher Basic, the TDS was worked out on the correct salary.
* About 95% coverage. "Cannot validate" remains for the PF employer, EPS and ESIC employer columns on purpose:
  employer contributions belong in the PF reports, not the salary register.

### Behaviour worth a look (found while building this pack)

| Employee | What happens |
| --- | --- |
{gap_rows}
| E015-E030 (everyone with a high income) | `STAT-011` "TDS slab not applied" is raised even though TDS **was** deducted correctly (the amounts equal the product's own Section 192 projection). The rule only looks at the size of the month's income. |
"""


if __name__ == "__main__":
    rows, master, ctc, att, key, gaps, previous = build()
    write("6_previous_month_register_july.csv", previous, HEADERS)
    (HERE / "1_configuration.csv").write_text(configuration_csv(), encoding="utf-8")
    write("2_employee_master.csv", master)
    write("3_ctc_report.csv", ctc)
    write("4_attendance_report.csv", att)
    write("5_salary_register.csv", rows, HEADERS)
    (HERE / "README.md").write_text(readme(key, gaps), encoding="utf-8")
    json.dump(sorted(key), open(HERE / "answer_key.json", "w"), indent=1)
    print(f"{len(rows)} register rows, {len(master)} master, {len(ctc)} ctc, {len(att)} attendance; {len(key)} planted problems")
