"""Builds the September 2026 QA month: a payroll processor's test of one register.

    cd backend && PYTHONPATH=. python ../testdata/payroll-qa-sep2026/generate.py

A dummy retail company with staff in Karnataka and Maharashtra, every case a
payroll processor checks in a month, worked out here by hand-rules:

* increments: one effective mid-month (paid right, and paid wrong), arrears for
  two and three earlier months (right), and an arrear forgotten;
* loss of pay, a mid-month joiner and a leaver, PF below and above the ceiling,
  PF and ESIC on arrears, ESIC coverage at the boundary and on a part month;
* PT by state and gender, LWF only in its contribution months;
* minimum wage measured on the CTC break-up.

Files, loaded in this order:

    1_configuration.csv              components, PF/ESIC, PT/LWF slabs, minimum wage rates
    2_employee_master.csv            joining/exit dates, gender, state, skill category
    3_ctc_report.csv                 CTC break-up, with the increment revisions as dated rows
    4_attendance_report.csv          September attendance
    5_previous_month_register_aug.csv  August, paid at the old rates
    6_salary_register_sep.csv        September -- one register: regular pay, increments and arrears

Deterministic: running it twice writes byte-identical files.
"""
from __future__ import annotations

import csv
import json
from decimal import ROUND_CEILING, ROUND_HALF_UP
from decimal import Decimal as D
from pathlib import Path

from app.services.config_files import tables_to_csv

HERE = Path(__file__).parent
PERIOD = "2026-09-01"
DAYS = 30
PF_CEILING = 15000


def rnd(x) -> int:
    return int(D(str(x)).quantize(D("1"), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------- configuration
COMPONENTS = [  # name, pf, esic, pt, lwf
    ("Basic", True, True, True, True),
    ("HRA", False, True, True, True),
    ("Special Allowance", False, True, True, True),
    ("Conveyance", False, True, True, True),
    ("Other Allowance", False, True, True, True),
    ("Overtime", False, False, True, False),
]


def _slab(state, typ, lo, hi, amt, order, gender="ALL", months="", employer=""):
    return {"state": state, "rule_type": typ, "min_salary": str(lo), "max_salary": str(hi),
            "deduction_amount": str(amt), "employer_amount": str(employer),
            # typed the way people type it; the upload accepts "half_yearly" as well as "half-yearly"
            "frequency": "monthly" if typ == "PT" else "half_yearly", "gender": gender,
            "applicable_months": months, "effective_from": "2024-04-01", "effective_to": "",
            "source_reference": "QA test values - verify before real use", "sort_order": str(order)}


def configuration_tables() -> dict[str, list[dict[str, str]]]:
    yn = lambda v: "Yes" if v else "No"  # noqa: E731
    return {
        "components": [
            {"component_name": n, "pf_applicable": yn(pf), "esic_applicable": yn(es), "pt_applicable": yn(pt),
             "lwf_applicable": yn(lw), "bonus_applicable": yn(n == "Basic"), "included_in_wages": "Yes",
             "taxable": "Yes", "tax_exemption_type": "none"} for n, pf, es, pt, lw in COMPONENTS],
        "statutory": [{
            "pf_employee_rate": "0.12", "pf_wage_ceiling": str(PF_CEILING), "pf_restrict_to_ceiling": "Yes",
            "esic_employee_rate": "0.0075", "esic_wage_ceiling": "21000", "esic_rounding": "up",
            "esic_full_month_on_entry": "Yes", "esic_continue_month_on_exit": "Yes",
            "pt_states": "Karnataka, Maharashtra", "lwf_states": "Maharashtra",
        }],
        "pt_lwf_slabs": [
            _slab("Karnataka", "PT", 0, 24999, 0, 1), _slab("Karnataka", "PT", 25000, 99999999, 200, 2),
            _slab("Maharashtra", "PT", 0, 7500, 0, 3, "MALE"), _slab("Maharashtra", "PT", 7501, 10000, 175, 4, "MALE"),
            _slab("Maharashtra", "PT", 10001, 99999999, 200, 5, "MALE"),
            _slab("Maharashtra", "PT", 0, 25000, 0, 6, "FEMALE"),
            _slab("Maharashtra", "PT", 25001, 99999999, 200, 7, "FEMALE"),
            _slab("Maharashtra", "LWF", 0, 99999999, 25, 8, months="6,12", employer=75),
        ],
        "minimum_wage_rates": [
            {"state": "Karnataka", "zone": "*", "scheduled_employment": "*", "skill_category": cat,
             "basic_per_month": basic, "vda_per_month": vda, "working_days_basis": "26",
             "effective_from": "2026-04-01", "effective_to": "", "source_reference": "QA test rate"}
            for cat, basic, vda in (("Unskilled", "12000", "2000"), ("Skilled", "14000", "2500"))
        ],
        "minimum_wage_applicability": [{"effective_from": "2026-04-01", "applicable": "Yes",
                                        "reason": "Retail shops are a scheduled employment", "source_reference": "QA"}],
    }


# --------------------------------------------------------------------------- people
P: dict[str, dict] = {}


def person(eid, name, state, gender, skill, basic, hra=None, special=0, conv=0, other=0, doj="2022-04-01", dox="",
           revision=None, note=""):
    P[eid] = dict(id=eid, name=name, state=state, gender=gender, skill=skill, doj=doj, dox=dox, note=note,
                  s={"Basic": basic, "HRA": hra if hra is not None else rnd(basic * 0.4), "Special Allowance": special,
                     "Conveyance": conv, "Other Allowance": other}, revision=revision)


person("C01", "Anil Kumar", "Karnataka", "Male", "Skilled", 30000, special=18000, conv=1600, note="above both ceilings")
person("C02", "Bhavana Rao", "Karnataka", "Female", "Unskilled", 9000, hra=3600, conv=1600, other=3000)
person("C03", "Chetan Gowda", "Karnataka", "Male", "Unskilled", 10000, hra=4000, other=4000,
       note="exactly at the minimum wage, with an 'Other Allowance' that counts towards it")
person("C04", "Deepa Shetty", "Karnataka", "Female", "Unskilled", 9000, hra=3000, special=2000)
person("C05", "Eshwar Naik", "Karnataka", "Male", "Skilled", 20000, special=6000, conv=1600, note="4 days LOP, prorated")
person("C06", "Farah Khan", "Karnataka", "Female", "Skilled", 22000, special=5000)
person("C07", "Ganesh Bhat", "Karnataka", "Male", "Skilled", 20000, special=4000, revision=("2026-09-16", 24000),
       note="increment from 16 Sep, paid 15 days old + 15 days new")
person("C08", "Harini Iyer", "Karnataka", "Female", "Skilled", 20000, special=4000, revision=("2026-09-16", 24000))
person("C09", "Imran Sheikh", "Karnataka", "Male", "Skilled", 18000, special=3000, revision=("2026-07-01", 21000),
       note="increment from 1 Jul, July and August arrear paid; PF already at the ceiling")
person("C10", "Jyothi Pai", "Karnataka", "Female", "Skilled", 12000, special=4000, revision=("2026-06-16", 14000),
       note="increment from 16 Jun, arrear for half of June, July and August; PF on the arrear")
person("C11", "Kiran Hegde", "Karnataka", "Male", "Skilled", 25000, special=5000, revision=("2026-08-01", 28000))
person("C12", "Latha Murthy", "Karnataka", "Female", "Skilled", 30000, special=10000)
person("C13", "Mohan Das", "Karnataka", "Male", "Skilled", 15000, hra=4000, special=1500)
person("C14", "Nisha Patil", "Maharashtra", "Female", "Skilled", 15000, special=1000)
person("C15", "Omkar Jadhav", "Maharashtra", "Male", "Unskilled", 6000, hra=2400, other=500,
       note="Maharashtra PT 175 for a man earning 7,501-10,000")
person("C16", "Pallavi Joshi", "Karnataka", "Female", "Skilled", 16000, special=2000, doj="2026-09-11",
       note="joined 11 Sep, paid 20 days; rate 24,400 so outside ESIC")
person("C17", "Rajesh Kamath", "Karnataka", "Male", "Skilled", 26000, special=4000, dox="2026-09-20",
       note="left 20 Sep, paid 20 days")
person("C18", "Sunita Pawar", "Maharashtra", "Female", "Skilled", 28000, special=6000)
person("C19", "Tarun Reddy", "Karnataka", "Male", "Skilled", 35000, special=15000)
person("C20", "Usha Nair", "Karnataka", "Female", "Skilled", 40000, special=10000, note="high earner, clean")
person("C21", "Vinod Kumar", "Karnataka", "Male", "Skilled", 13000, hra=3000, special=1000,
       revision=("2026-08-01", 14000), note="ESIC-covered, August arrear carries ESIC")
person("C22", "Waheeda Begum", "Karnataka", "Female", "Skilled", 16000, special=10000,
       note="6 days LOP: earned basic 12,800, so PF is below the ceiling")
person("C23", "Yash Shetty", "Karnataka", "Male", "Skilled", 12000, hra=4800, special=1200, doj="2026-09-16",
       note="joined 16 Sep, ESIC-covered")
person("C24", "Zoya Mirza", "Karnataka", "Female", "Skilled", 15000, hra=6000, special=4000,
       note="gross exactly 25,000: Karnataka PT 200")
person("C25", "Aarav Menon", "Karnataka", "Male", "Skilled", 15000, hra=4000, special=2000,
       note="ESIC wage exactly 21,000: covered")

LOP = {"C05": 4, "C22": 6}
ATT_LOP = {"C05": 4, "C06": 3, "C22": 6}
PAID_DAYS = {"C16": 20, "C17": 20, "C23": 15}

# employee -> (rule ids the tool must report, the mistake in words)
EXPECTED: dict[str, tuple[set[str], str]] = {
    "C02": ({"MW-001"}, "CTC break-up 13,600 (Basic + Conveyance + Other Allowance, HRA excluded) is below the "
                        "Karnataka unskilled minimum of 14,000"),
    "C04": ({"MW-001"}, "CTC break-up 11,000 (HRA excluded) is below the Karnataka unskilled minimum of 14,000"),
    "C06": ({"ATT-001", "ATT-002", "ATT-020"}, "3 days of LOP in attendance, but the full month was paid"),
    "C08": ({"INC-002"}, "Increment effective 16 Sep paid at the full new rate for the whole month"),
    "C11": ({"MOM-006"}, "Increment effective 1 Aug: September paid at the new rate but the August arrear "
                         "(3,000 Basic + 1,200 HRA) was not paid"),
    "C12": ({"PF-009"}, "PF 3,600 deducted on the full Basic, but PF is restricted to the 15,000 ceiling (1,800)"),
    "C13": ({"STAT-006"}, "ESIC not deducted although the ESIC wage of 20,500 is within 21,000"),
    "C14": ({"STAT-008"}, "Maharashtra PT of 200 charged to a woman earning 22,000 (nil up to 25,000 for women)"),
    "C18": ({"STAT-009"}, "Maharashtra LWF deducted in September; it is due only in June and December"),
    "C19": ({"AGG-001"}, "Gross is 2,000 more than the sum of the earnings"),
    "C21": ({"MW-001"}, "New CTC 15,000 excluding HRA is below the Karnataka skilled minimum of 16,500 "
                        "(the arrear itself is correct)"),
    "C23": ({"MW-001"}, "CTC 13,200 excluding HRA is below the Karnataka skilled minimum of 16,500"),
}
# A policy view, not a mistake: wages under the Code on Wages are taken as the PF-applicable components
# unless the company names its wage components, and Special Allowance is not PF-applicable here.
BACKGROUND = {"LC-001"}


def month_structure(p, month_days=DAYS, period=PERIOD):
    """(due this month, old, new) -- an increment inside the month blended by days."""
    s = dict(p["s"])
    if p["revision"]:
        eff, nb = p["revision"]
        new = dict(s, Basic=nb, HRA=rnd(nb * 0.4))
        if eff <= period:
            return new, s, new
        day = int(eff[8:])
        old_days, new_days = day - 1, month_days - (day - 1)
        blend = {k: round(s[k] * old_days / month_days + new[k] * new_days / month_days, 2) for k in s}
        return blend, s, new
    return s, s, s


def arrears(p) -> dict[str, float]:
    """Arrear due in September for the months before it, per component; the first month part-month."""
    if not p["revision"] or p["revision"][0] >= PERIOD:
        return {}
    eff, nb = p["revision"]
    old = p["s"]
    new = dict(old, Basic=nb, HRA=rnd(nb * 0.4))
    diff = {k: new[k] - old[k] for k in old if new[k] != old[k]}
    total = {k: D(0) for k in diff}
    for month, month_days in (("2026-06", 30), ("2026-07", 31), ("2026-08", 31)):
        if eff[:7] > month:
            continue
        frac = D(1) if eff <= f"{month}-01" else D(month_days - int(eff[8:]) + 1) / D(month_days)
        for k in diff:
            total[k] += D(diff[k]) * frac
    return {k: float(round(v, 2)) for k, v in total.items()}


def pt_for(p, gross):
    if p["state"] == "Karnataka":
        return 200 if gross >= 25000 else 0
    if p["gender"] == "Female":
        return 200 if gross > 25000 else 0
    return 0 if gross <= 7500 else 175 if gross <= 10000 else 200


HEAD = ["Employee ID", "Employee Name", "State", "UAN", "ESI Number", "PAN", "Date of Joining", "Total Days",
        "Paid Days", "LOP Days", "Basic", "HRA", "Special Allowance", "Conveyance", "Other Allowance", "Overtime",
        "Basic Arrear", "HRA Arrear", "Gross", "PF Employee", "ESIC Employee", "PT", "LWF Employee", "TDS",
        "Total Deductions", "Net"]


def payslip(p, *, days=DAYS, paid=None, lop=0, structure=None, arr=None) -> dict:
    """What payroll should pay, by the rules in the configuration."""
    paid = paid if paid is not None else days - lop
    st = structure or p["s"]
    earn = {k: float(round(D(str(v)) * D(paid) / D(days), 2)) for k, v in st.items()}
    arr = arr or {}
    gross = round(sum(earn.values()) + sum(arr.values()), 2)
    pf = rnd(D(str(min(earn["Basic"], PF_CEILING))) * D("0.12"))
    if arr.get("Basic"):
        # PF on an arrear: each month it relates to is taken to the ceiling on its own
        _, nb = p["revision"]
        ob = p["s"]["Basic"]
        months = D(str(arr["Basic"])) / D(nb - ob)
        pf += rnd(months * (min(nb, PF_CEILING) - min(ob, PF_CEILING)) * D("0.12"))
    # ESIC coverage follows the full-month rate; the contribution is on what is paid, arrears included
    esic_wage = sum(earn[k] for k in ("Basic", "HRA", "Special Allowance", "Conveyance", "Other Allowance"))
    esic_wage += sum(arr.values())
    covered = sum(st.values()) <= 21000
    esic = int((D(str(esic_wage)) * D("0.0075")).to_integral_value(rounding=ROUND_CEILING)) if covered else 0
    pt = pt_for(p, gross)
    ded = pf + esic + pt
    n = int(p["id"][1:])
    return {"Employee ID": p["id"], "Employee Name": p["name"], "State": p["state"], "UAN": f"10099900{n:04d}",
            "ESI Number": f"52000{n:05d}", "PAN": f"AAQPQ{n:04d}C", "Date of Joining": p["doj"], "Total Days": days,
            "Paid Days": paid, "LOP Days": lop, **earn, "Overtime": 0, "Basic Arrear": arr.get("Basic", 0),
            "HRA Arrear": arr.get("HRA", 0), "Gross": gross, "PF Employee": pf, "ESIC Employee": esic, "PT": pt,
            "LWF Employee": 0, "TDS": 0, "Total Deductions": ded, "Net": round(gross - ded, 2)}


def _totals(r):
    r["Gross"] = round(sum(r[k] for k in ("Basic", "HRA", "Special Allowance", "Conveyance", "Other Allowance",
                                          "Overtime", "Basic Arrear", "HRA Arrear")), 2)
    r["Total Deductions"] = r["PF Employee"] + r["ESIC Employee"] + r["PT"] + r["LWF Employee"] + r["TDS"]
    r["Net"] = round(r["Gross"] - r["Total Deductions"], 2)


def build():
    september = []
    for eid, p in P.items():
        blend, _, new = month_structure(p)
        r = payslip(p, lop=LOP.get(eid, 0), paid=PAID_DAYS.get(eid), structure=blend, arr=arrears(p))
        if eid == "C08":
            r = payslip(p, structure=new)
        elif eid == "C11":
            r = payslip(p, structure=new)
        elif eid == "C12":
            r["PF Employee"] = rnd(30000 * 0.12)
            _totals(r)
        elif eid == "C13":
            r["ESIC Employee"] = 0
            _totals(r)
        elif eid == "C14":
            r["PT"] = 200
            _totals(r)
        elif eid == "C18":
            r["LWF Employee"] = 25
            _totals(r)
        elif eid == "C19":
            r["Gross"] += 2000
            r["Net"] = round(r["Gross"] - r["Total Deductions"], 2)
        september.append(r)

    # August: everyone at the old rate -- the revisions were approved in September
    august = [payslip(p, days=31) for eid, p in P.items() if eid not in ("C16", "C23")]

    master = [{"Employee ID": p["id"], "Employee Name": p["name"], "Date of Joining": p["doj"],
               "Date of Exit": p["dox"], "Gender": p["gender"], "State": p["state"], "Department": "Stores",
               "Designation": "Associate", "Employment Type": "Permanent", "Skill Category": p["skill"],
               "UAN": f"10099900{int(p['id'][1:]):04d}", "ESIC IP Number": f"52000{int(p['id'][1:]):05d}"}
              for p in P.values()]

    ctc = []
    for p in P.values():
        s = p["s"]
        ctc.append({"Employee ID": p["id"], "Employee Name": p["name"], "Effective From": "2026-04-01",
                    **{k: v * 12 for k, v in s.items()}, "Annual CTC": sum(s.values()) * 12})
        if p["revision"]:
            eff, nb = p["revision"]
            n = dict(s, Basic=nb, HRA=rnd(nb * 0.4))
            ctc.append({"Employee ID": p["id"], "Employee Name": p["name"], "Effective From": eff,
                        **{k: v * 12 for k, v in n.items()}, "Annual CTC": sum(n.values()) * 12})

    attendance = []
    for eid, p in P.items():
        lop = ATT_LOP.get(eid, 0)
        paid = PAID_DAYS.get(eid, DAYS - lop)
        weekly_off, holiday = (3, 0) if eid in PAID_DAYS else (4, 1)
        attendance.append({"Employee ID": eid, "Employee Name": p["name"], "Total Days": DAYS,
                           "Present Days": paid - weekly_off - holiday, "Paid Leave Days": 0,
                           "Weekly Off Days": weekly_off, "Holiday Days": holiday, "LOP Days": lop,
                           "Paid Days": paid, "Overtime Hours": 0})
    return september, august, master, ctc, attendance


def write(name: str, rows: list[dict], headers: list[str] | None = None) -> None:
    with open(HERE / name, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=headers or list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def readme() -> str:
    mistakes = "\n".join(f"| {eid} | {why} | {', '.join(sorted(rules))} |" for eid, (rules, why) in EXPECTED.items())
    clean = "\n".join(f"| {p['id']} | {p['note']} |" for p in P.values() if p["note"] and p["id"] not in EXPECTED)
    return f"""# Payroll QA month (September 2026)

A payroll processor's test of one month, for a dummy retail company with staff in Karnataka and
Maharashtra. Nothing here is real. Regenerate with
`cd backend && PYTHONPATH=. python ../testdata/payroll-qa-sep2026/generate.py`.

One register holds everything for the month: regular pay, a mid-month increment, arrears for earlier
months, joiners and leavers. It is uploaded once and validated once.

## Load order

| Step | Where | File |
| --- | --- | --- |
| 1 | Setup -> **Configuration upload** (preview, then apply) | `1_configuration.csv` |
| 2 | Data & imports -> **Employee master** (effective 2022-04-01) | `2_employee_master.csv` |
| 3 | Data & imports -> **CTC upload** (default effective 2026-04-01; revisions carry their own date) | `3_ctc_report.csv` |
| 4 | Data & imports -> **Attendance** (September 2026) | `4_attendance_report.csv` |
| 5 | Control Centre -> **Check a register**, **August 2026**, validate | `5_previous_month_register_aug.csv` |
| 6 | Control Centre -> **Check a register**, **September 2026**, validate, open Results | `6_salary_register_sep.csv` |

## Rules in the configuration (test values)

* PF 12% of Basic, restricted to the 15,000 ceiling. PF on an arrear: each month the arrear relates
  to is taken to the ceiling on its own.
* ESIC 0.75% rounded up. Coverage follows the full-month rate of wages (21,000 or less), so loss of
  pay or a part month does not bring someone under ESIC; the contribution is on what is paid,
  arrears included.
* PT: Karnataka 200 from 25,000. Maharashtra men 175 from 7,501 and 200 above 10,000; women nil up to
  25,000.
* LWF: Maharashtra only, 25 (employer 75) in June and December.
* Minimum wage applies: Karnataka unskilled 14,000 and skilled 16,500 a month, measured on the CTC
  break-up excluding HRA.

## Answer key -- what the tool must report

| Employee | Mistake | Rule |
| --- | --- | --- |
{mistakes}

Everyone else is correct and must produce no warning or critical finding. The ones that prove the
tool does not over-report:

| Employee | Why it is correct |
| --- | --- |
{clean}

### Expected background (not mistakes)

* `LC-001` (warning) for C01 and C22: the Code on Wages test takes wages as the PF-applicable
  components unless the company names its wage components; Special Allowance is not PF-applicable
  here. It is a structure review point, not a payroll error.
* `ARR-004` (info) for C09: the arrear carries no further PF because the wage was already at the
  ceiling.
* `MOM-001` (info) for the September joiners; `MW-003` (info) for Maharashtra staff, where no minimum
  wage rate is loaded.
"""


if __name__ == "__main__":
    september, august, master, ctc, attendance = build()
    (HERE / "1_configuration.csv").write_bytes(tables_to_csv(configuration_tables()))
    write("2_employee_master.csv", master)
    write("3_ctc_report.csv", ctc)
    write("4_attendance_report.csv", attendance)
    write("5_previous_month_register_aug.csv", august, HEAD)
    write("6_salary_register_sep.csv", september, HEAD)
    (HERE / "README.md").write_text(readme(), encoding="utf-8")
    key = {eid: {"rules": sorted(rules), "mistake": why} for eid, (rules, why) in EXPECTED.items()}
    (HERE / "answer_key.json").write_text(json.dumps(key, indent=1) + "\n", encoding="utf-8")
    print(f"{len(september)} employees, {len(EXPECTED)} planted mistakes")
