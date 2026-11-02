"""A full financial year, April 2026 to March 2027, for one dummy company.

    cd backend && PYTHONPATH=. python ../testdata/payroll-fy2026-27/generate.py

Every payslip here is worked out by hand-rules in this file, independently of the
product's engine, so the engine is checked against payroll arithmetic rather than
against itself. Each month is a folder with the files a payroll team would load
that month, in order; README.md says what the tool must report each month.

What the year contains:

* Apr  base month; PF on full basic for one person (planted)
* May  a joiner on 15 May (paid the full month — planted); LOP
* Jun  Maharashtra LWF (one missed — planted)
* Jul  April increments approved late, paid with April-June arrears (one short — planted);
       an ESIC-covered employee crosses Rs 21,000 and stays covered to September
* Aug  a transfer Karnataka -> Maharashtra; an exit on 20 Aug; a promotion on 16 Aug (paid
       the full new rate — planted)
* Sep  the PF ceiling rises to Rs 25,000 on 17 Sep (register worked on the old ceiling: a
       shortfall to recover); an EPS exclusion that is no longer valid; PT missed (planted)
* Oct  the shortfall recovered (twice for one person — planted); new ESIC contribution
       period (one still deducted — planted); minimum-wage VDA revision
* Nov  overtime (paid at single rate — planted); LOP
* Dec  Maharashtra LWF (Rs 12 instead of Rs 25 — planted); an employee on hold, not paid;
       LOP reversal
* Jan  a back-dated promotion (effective 1 Nov) paid with Nov-Dec arrears; gross does not
       add up (planted)
* Feb  Maharashtra February PT Rs 300 (one paid Rs 200 — planted)
* Mar  a LOP reversal for LOP never taken (planted); someone missing without an exit (planted)

Deterministic: running it twice writes byte-identical files.
"""
from __future__ import annotations

import calendar
import csv
import json
import shutil
from datetime import date, timedelta
from decimal import ROUND_CEILING, ROUND_HALF_UP
from decimal import Decimal as D
from pathlib import Path

from app.services.config_files import tables_to_csv

HERE = Path(__file__).parent
MONTHS = [date(2026, m, 1) for m in range(4, 13)] + [date(2027, m, 1) for m in range(1, 4)]
PF_CHANGE = date(2026, 9, 17)


def rnd(x) -> int:
    return int(D(str(x)).quantize(D("1"), rounding=ROUND_HALF_UP))


def money(x) -> float:
    return float(D(str(x)).quantize(D("0.01"), rounding=ROUND_HALF_UP))


def days_in(m: date) -> int:
    return calendar.monthrange(m.year, m.month)[1]


def key(m: date) -> str:
    return m.strftime("%Y-%m")


# ── configuration ─────────────────────────────────────────────────────────────
COMPONENTS = [  # name, pf, esic, pt, lwf
    ("Basic", True, True, True, True),
    ("HRA", False, True, True, True),
    ("Special Allowance", False, True, True, True),
    ("Overtime", False, True, True, False),
]


def _slab(state, typ, lo, hi, amt, order, gender="ALL", months="", employer="", freq="monthly"):
    return {"state": state, "rule_type": typ, "min_salary": str(lo), "max_salary": str(hi),
            "deduction_amount": str(amt), "employer_amount": str(employer), "frequency": freq,
            "gender": gender, "applicable_months": months, "effective_from": "2024-04-01", "effective_to": "",
            "source_reference": "Test values - verify against the notification before real use",
            "sort_order": str(order)}


NOT_FEB = "1,3,4,5,6,7,8,9,10,11,12"


def configuration() -> dict:
    yn = lambda v: "Yes" if v else "No"  # noqa: E731
    return {
        "components": [
            {"component_name": n, "pf_applicable": yn(pf), "esic_applicable": yn(es), "pt_applicable": yn(pt),
             "lwf_applicable": yn(lw), "bonus_applicable": yn(n == "Basic"), "included_in_wages": "Yes",
             "taxable": "Yes", "tax_exemption_type": "none"} for n, pf, es, pt, lw in COMPONENTS],
        "statutory": [{
            "pf_employee_rate": "0.12", "pf_wage_ceiling": "15000", "pf_restrict_to_ceiling": "Yes",
            "esic_employee_rate": "0.0075", "esic_wage_ceiling": "21000", "esic_rounding": "up",
            "esic_full_month_on_entry": "Yes", "esic_continue_month_on_exit": "Yes",
            "pt_states": "Karnataka, Maharashtra", "lwf_states": "Maharashtra",
        }],
        "pt_lwf_slabs": [
            _slab("Karnataka", "PT", 0, 24999, 0, 1), _slab("Karnataka", "PT", 25000, 99999999, 200, 2),
            _slab("Maharashtra", "PT", 0, 7500, 0, 3, "MALE"),
            _slab("Maharashtra", "PT", 7501, 10000, 175, 4, "MALE"),
            _slab("Maharashtra", "PT", 10001, 99999999, 200, 5, "MALE", NOT_FEB),
            _slab("Maharashtra", "PT", 10001, 99999999, 300, 6, "MALE", "2"),
            _slab("Maharashtra", "PT", 0, 25000, 0, 7, "FEMALE"),
            _slab("Maharashtra", "PT", 25001, 99999999, 200, 8, "FEMALE", NOT_FEB),
            _slab("Maharashtra", "PT", 25001, 99999999, 300, 9, "FEMALE", "2"),
            _slab("Maharashtra", "LWF", 0, 99999999, 25, 10, months="6,12", employer=75, freq="half-yearly"),
        ],
        "minimum_wage_rates": [
            {"state": "Karnataka", "zone": "*", "scheduled_employment": "*", "skill_category": cat,
             "basic_per_month": b, "vda_per_month": v, "working_days_basis": "26",
             "effective_from": f, "effective_to": t, "source_reference": "Test rate"}
            for cat, b, v, f, t in (
                ("Unskilled", "12000", "2000", "2026-04-01", "2026-09-30"),
                ("Skilled", "14000", "2500", "2026-04-01", "2026-09-30"),
                # the October VDA revision
                ("Unskilled", "12000", "2500", "2026-10-01", ""),
                ("Skilled", "14000", "3000", "2026-10-01", ""),
            )
        ],
        "minimum_wage_applicability": [{"effective_from": "2026-04-01", "applicable": "Yes",
                                        "reason": "Retail shops are a scheduled employment", "source_reference": "test"}],
    }


# ── people ────────────────────────────────────────────────────────────────────
class P:
    def __init__(self, eid, name, state, gender, skill, basic, special=0.1, doj="2021-06-01", eps=True, note=""):
        self.id, self.name, self.state, self.gender, self.skill = eid, name, state, gender, skill
        self.basic, self.special, self.doj, self.eps, self.note = basic, special, doj, eps, note
        self.dox = ""
        self.revisions: list[tuple[str, int, date]] = []   # (effective_from, new basic, month approved)
        self.status: dict[date, str] = {}                 # month -> status
        self.state_from: list[tuple[date, str]] = []       # transfers

    def structure(self, basic: float) -> dict[str, float]:
        return {"Basic": basic, "HRA": rnd(basic * 0.4), "Special Allowance": rnd(basic * self.special)}

    def basic_on(self, day: date, known_by: date | None = None) -> int:
        """The basic in force on a day, counting only revisions approved by ``known_by``."""
        b = self.basic
        for eff, nb, approved in sorted(self.revisions):
            if date.fromisoformat(eff) <= day and (known_by is None or approved <= known_by):
                b = nb
        return b

    def state_on(self, m: date) -> str:
        s = self.state
        for since, st in sorted(self.state_from):
            if since <= m:
                s = st
        return s


PEOPLE = [
    P("E01", "Arvind Rao", "Karnataka", "Male", "Skilled", 40000, note="above both PF ceilings"),
    P("E02", "Bindu Nair", "Karnataka", "Female", "Skilled", 30000),
    P("E03", "Chetan Patil", "Maharashtra", "Male", "Skilled", 20000, note="PF wage between Rs 15,000 and 25,000"),
    P("E04", "Deepa Kulkarni", "Maharashtra", "Female", "Skilled", 18000),
    P("E05", "Eshwar Gowda", "Karnataka", "Male", "Unskilled", 14500, special=0,
      note="ESIC-covered; the July increment takes him over Rs 21,000"),
    P("E06", "Fathima Begum", "Karnataka", "Female", "Unskilled", 14500, special=0, note="ESIC-covered all year"),
    P("E07", "Ganesh Jadhav", "Maharashtra", "Male", "Unskilled", 14500, special=0, note="Maharashtra PT incl. February"),
    P("E08", "Harish Shetty", "Karnataka", "Male", "Skilled", 20000, doj="2026-05-15", note="joined 15 May"),
    P("E09", "Indira Menon", "Karnataka", "Female", "Skilled", 25000, note="left 20 Aug"),
    P("E10", "Jagdish Pawar", "Karnataka", "Male", "Skilled", 22000, note="transferred to Maharashtra from August"),
    P("E11", "Kiran Bhat", "Karnataka", "Male", "Skilled", 24000, note="promoted 16 Aug"),
    P("E12", "Lakshmi Iyer", "Karnataka", "Female", "Skilled", 26000, note="promotion effective 1 Nov, approved in January"),
    P("E13", "Mohan Das", "Karnataka", "Male", "Skilled", 30000, note="overtime in November"),
    P("E14", "Nisha Deshmukh", "Maharashtra", "Female", "Skilled", 16000, note="April increment with arrears in July"),
    P("E15", "Om Prakash", "Karnataka", "Male", "Skilled", 35000, doj="2018-01-10", eps=False,
      note="kept out of EPS, wage above Rs 25,000: stays out"),
    P("E16", "Pooja Hegde", "Karnataka", "Female", "Skilled", 20000, doj="2019-03-01", eps=False,
      note="kept out of EPS, wage within Rs 25,000: brought in from October"),
    P("E17", "Rakesh Kumar", "Karnataka", "Male", "Skilled", 20000, note="on hold in December"),
    P("E18", "Sunita Rao", "Karnataka", "Female", "Skilled", 20000, note="LOP in November, one day reversed in December"),
    P("E19", "Tarun Joshi", "Karnataka", "Male", "Skilled", 30000),
    P("E20", "Uma Shankar", "Karnataka", "Female", "Skilled", 28000),
    P("E21", "Vivek Sawant", "Maharashtra", "Male", "Skilled", 26000),
    P("E22", "Waheeda Khan", "Karnataka", "Female", "Skilled", 22000),
    P("E23", "Yash Kamath", "Karnataka", "Male", "Skilled", 21000),
    P("E24", "Zara Fernandes", "Maharashtra", "Female", "Skilled", 27000),
]
BY = {p.id: p for p in PEOPLE}
BY["E05"].revisions.append(("2026-04-01", 15200, date(2026, 7, 1)))
BY["E14"].revisions.append(("2026-04-01", 17000, date(2026, 7, 1)))
BY["E11"].revisions.append(("2026-08-16", 28000, date(2026, 8, 1)))
BY["E12"].revisions.append(("2026-11-01", 30000, date(2027, 1, 1)))
BY["E09"].dox = "2026-08-20"
BY["E10"].state_from.append((date(2026, 8, 1), "Maharashtra"))
BY["E17"].status[date(2026, 12, 1)] = "On Hold"

LOP = {("E06", date(2026, 5, 1)): 2, ("E13", date(2026, 11, 1)): 0, ("E18", date(2026, 11, 1)): 3,
       ("E22", date(2026, 5, 1)): 1}
OT_HOURS = {("E13", date(2026, 11, 1)): 10}
LOP_REVERSAL = {("E18", date(2026, 12, 1)): 1, ("E18", date(2027, 3, 1)): 1}

# month -> employee -> (rule ids the tool must report, the mistake)
EXPECTED: dict[str, dict[str, tuple[list[str], str]]] = {}


def plant(m: date, eid: str, rules: list[str], why: str) -> None:
    EXPECTED.setdefault(key(m), {})[eid] = (rules, why)


# ── statutory arithmetic (hand rules) ─────────────────────────────────────────
def statutory_ceiling(day: date) -> int:
    return 25000 if day >= PF_CHANGE else 15000


def month_ceiling(m: date) -> D:
    first, last = m, m.replace(day=days_in(m))
    old, new = statutory_ceiling(first), statutory_ceiling(last)
    if old == new:
        return D(new)
    old_days = (PF_CHANGE - first).days
    return (D(old) * old_days + D(new) * (days_in(m) - old_days)) / D(days_in(m))


def pt_for(state: str, gender: str, gross: float, m: date) -> int:
    if state == "Karnataka":
        return 200 if gross >= 25000 else 0
    feb = m.month == 2
    if gender == "Female":
        return (300 if feb else 200) if gross > 25000 else 0
    if gross <= 7500:
        return 0
    if gross <= 10000:
        return 175
    return 300 if feb else 200


def esic_period_start(m: date) -> date:
    if m.month >= 10:
        return date(m.year, 10, 1)
    if m.month >= 4:
        return date(m.year, 4, 1)
    return date(m.year - 1, 10, 1)


def ot_pay(p: P, m: date, hours: float, basic: float) -> int:
    full = sum(p.structure(basic).values())
    return rnd(D(str(full)) / D(days_in(m)) / D(8) * D(2) * D(str(hours)))


# ── the year ──────────────────────────────────────────────────────────────────
HEAD = ["Employee ID", "Employee Name", "State", "PAN", "UAN", "ESI Number", "Bank Account", "Date of Joining",
        "Total Days", "Paid Days", "LOP Days", "LOP Reversal Days", "LOP Reversal Amount",
        "Basic", "HRA", "Special Allowance", "Overtime", "Basic Arrear", "HRA Arrear", "Special Allowance Arrear",
        "Gross", "PF Employee", "PF Employee Arrear", "ESIC Employee", "PT", "LWF Employee", "LWF Employer", "TDS",
        "Total Deductions", "Net"]


def build():
    months: dict[str, dict] = {}
    esic_covered: dict[str, date] = {}       # employee -> period start they were covered in
    shortfall: dict[str, int] = {}           # September PF shortfall per employee
    for m in MONTHS:
        mdays = days_in(m)
        start = esic_period_start(m)
        rows, attendance = [], []
        for p in PEOPLE:
            doj = date.fromisoformat(p.doj)
            dox = date.fromisoformat(p.dox) if p.dox else None
            if doj > m.replace(day=mdays) or (dox and dox < m):
                continue
            if p.status.get(m) == "On Hold":
                continue                          # salary held: not on this month's register
            first = max(doj, m) if doj.year == m.year and doj.month == m.month else m
            last = dox if (dox and dox.year == m.year and dox.month == m.month) else m.replace(day=mdays)
            employed = (last - first).days + 1
            lop = LOP.get((p.id, m), 0)
            paid = employed - lop
            # the structure due: day-weighted where a known revision lands inside the month
            known = m
            b_start, b_end = p.basic_on(m, known), p.basic_on(m.replace(day=mdays), known)
            rev_day = next((date.fromisoformat(e) for e, _, a in p.revisions
                            if a <= known and m < date.fromisoformat(e) <= m.replace(day=mdays)), None)
            if rev_day:
                old_days = (rev_day - m).days
                due = {k: money(D(str(v)) * old_days / mdays + D(str(p.structure(b_end)[k])) * (mdays - old_days) / mdays)
                       for k, v in p.structure(b_start).items()}
            else:
                due = {k: float(v) for k, v in p.structure(b_end).items()}
            earn = {k: money(D(str(v)) * D(paid) / D(mdays)) for k, v in due.items()}
            # arrears: revisions approved this month, effective in earlier months
            arrear = dict.fromkeys(due, 0.0)
            arrear_months = D(0)
            for eff, nb, approved in p.revisions:
                effd = date.fromisoformat(eff)
                if approved == m and effd < m:
                    for prev in [x for x in MONTHS if effd.replace(day=1) <= x < m]:
                        frac = D(1) if effd <= prev else D(days_in(prev) - effd.day + 1) / D(days_in(prev))
                        # the revision before this one, if any, is the old structure for that month
                        prior_basic = p.basic_on(prev, prev)
                        old = p.structure(prior_basic)
                        new = p.structure(nb)
                        for k in arrear:
                            arrear[k] += float(D(str(new[k] - old[k])) * frac)
                        arrear_months += frac
            arrear = {k: money(v) for k, v in arrear.items()}
            ot = ot_pay(p, m, OT_HOURS[(p.id, m)], b_end) if (p.id, m) in OT_HOURS else 0
            reversal_days = LOP_REVERSAL.get((p.id, m), 0)
            prev_m = MONTHS[MONTHS.index(m) - 1] if MONTHS.index(m) else None
            reversal_amt = (money(D(str(sum(p.structure(b_end).values()))) * reversal_days / D(days_in(prev_m)))
                            if reversal_days and prev_m else 0)
            gross = money(sum(earn.values()) + sum(arrear.values()) + ot + reversal_amt)

            # PF: the month's ceiling; arrears to each earlier month's own ceiling
            ceiling = month_ceiling(m)
            pf_basic = D(str(earn["Basic"]))
            pf = rnd(min(pf_basic, ceiling) * D("0.12"))
            if m == date(2026, 9, 1):            # the register is worked on the old ceiling in September
                worked = rnd(min(pf_basic, D(15000)) * D("0.12"))
                if worked < pf:
                    shortfall[p.id] = pf - worked
                pf = worked
            if arrear["Basic"] and arrear_months:
                per = D(str(arrear["Basic"])) / arrear_months
                full_new = D(str(due["Basic"]))
                c_old = D(statutory_ceiling(m - timedelta(days=1)))
                pf += rnd(arrear_months * (min(full_new, c_old) - min(max(full_new - per, D(0)), c_old)) * D("0.12"))
            pf_arrear = shortfall.get(p.id, 0) if m == date(2026, 10, 1) else 0

            # ESIC: coverage on the full-month rate, held to the end of a contribution period
            esic_wage_full = sum(v for k, v in due.items())
            covered = esic_wage_full <= 21000 or esic_covered.get(p.id) == start
            if covered:
                esic_covered[p.id] = start
            esic_base = D(str(sum(earn.values()) + sum(arrear.values()) + ot + reversal_amt))
            esic = int((esic_base * D("0.0075")).to_integral_value(rounding=ROUND_CEILING)) if covered else 0

            state = p.state_on(m)
            pt = pt_for(state, p.gender, gross, m)
            lwf = 25 if state == "Maharashtra" and m.month in (6, 12) else 0
            lwf_er = 75 if lwf else 0
            ded = pf + pf_arrear + esic + pt + lwf
            n = int(p.id[1:])
            row = {"Employee ID": p.id, "Employee Name": p.name, "State": state, "PAN": f"ABCPF{n:04d}K",
                   "UAN": f"1012026500{n:02d}",
                   "ESI Number": f"52000001{n:02d}", "Bank Account": f"91002000{n:04d}", "Date of Joining": p.doj,
                   "Total Days": mdays, "Paid Days": paid, "LOP Days": lop,
                   "LOP Reversal Days": reversal_days or "", "LOP Reversal Amount": reversal_amt or "",
                   **earn, "Overtime": ot, "Basic Arrear": arrear["Basic"] or "", "HRA Arrear": arrear["HRA"] or "",
                   "Special Allowance Arrear": arrear["Special Allowance"] or "",
                   "Gross": gross, "PF Employee": pf, "PF Employee Arrear": pf_arrear or "", "ESIC Employee": esic,
                   "PT": pt, "LWF Employee": lwf, "LWF Employer": lwf_er, "TDS": 0,
                   "Total Deductions": ded, "Net": money(gross - ded)}
            rows.append(row)
            whole = employed == mdays
            attendance.append({"Employee ID": p.id, "Employee Name": p.name, "Total Days": mdays,
                               "Present Days": paid - 5 if whole else paid, "Paid Leave Days": 0,
                               "Weekly Off Days": 4 if whole else 0, "Holiday Days": 1 if whole else 0,
                               "LOP Days": lop, "Paid Days": paid,
                               "Overtime Hours": OT_HOURS.get((p.id, m), 0)})
        months[key(m)] = {"rows": rows, "attendance": attendance}
    return months


def _recompute(r: dict) -> None:
    r["Total Deductions"] = sum(float(r[k] or 0) for k in ("PF Employee", "PF Employee Arrear", "ESIC Employee",
                                                            "PT", "LWF Employee", "TDS"))
    r["Net"] = money(float(r["Gross"]) - r["Total Deductions"])


def mistakes(months: dict) -> None:
    """The planted mistakes, one or two a month."""
    def row(m, eid):
        return next(r for r in months[key(m)]["rows"] if r["Employee ID"] == eid)

    r = row(date(2026, 4, 1), "E19")
    r["PF Employee"] = rnd(30000 * 0.12)
    _recompute(r)
    plant(date(2026, 4, 1), "E19", ["PF-009"], "PF Rs 3,600 on the full basic; PF is restricted to Rs 15,000 (Rs 1,800)")

    r = row(date(2026, 5, 1), "E08")
    for k, v in BY["E08"].structure(20000).items():
        r[k] = float(v)
    r["Paid Days"], r["Gross"] = 31, 30000.0
    r["PF Employee"] = 1800
    r["PT"] = 200
    _recompute(r)
    plant(date(2026, 5, 1), "E08", ["MST-006", "ATT-001"], "Joined 15 May but paid the full month "
                                                         "(31 days against 17 in attendance)")

    r = row(date(2026, 6, 1), "E07")
    r["LWF Employee"], r["LWF Employer"] = 0, 0
    _recompute(r)
    plant(date(2026, 6, 1), "E07", ["STAT-009", "STAT-010"], "Maharashtra June LWF not deducted (employee Rs 25, "
                                                           "employer Rs 75)")

    r = row(date(2026, 7, 1), "E14")
    for k in ("Basic Arrear", "HRA Arrear", "Special Allowance Arrear"):
        r[k] = money(float(r[k] or 0) * 2 / 3)
    r["Gross"] = money(sum(float(r[k] or 0) for k in ("Basic", "HRA", "Special Allowance", "Overtime", "Basic Arrear",
                                                       "HRA Arrear", "Special Allowance Arrear")))
    _recompute(r)
    plant(date(2026, 7, 1), "E14", ["MOM-006"], "April increment arrears paid for two months; April to June is three")
    # ...and August pays the balance, as a payroll team would once the finding is raised.
    jul, aug = r, row(date(2026, 8, 1), "E14")
    old, new = BY["E14"].structure(16000), BY["E14"].structure(17000)
    owed = {k: float((new[k] - old[k]) * 3) for k in new}                  # April, May and June
    for comp in owed:
        aug[f"{comp} Arrear"] = money(owed[comp] - float(jul[f"{comp} Arrear"] or 0))
    aug["Gross"] = money(sum(float(aug[k] or 0) for k in ("Basic", "HRA", "Special Allowance", "Overtime",
                                                          "Basic Arrear", "HRA Arrear", "Special Allowance Arrear")))
    _recompute(aug)

    r = row(date(2026, 8, 1), "E11")
    for k, v in BY["E11"].structure(28000).items():
        r[k] = float(v)
    r["Gross"] = money(sum(BY["E11"].structure(28000).values()))
    r["PT"] = 200
    _recompute(r)
    plant(date(2026, 8, 1), "E11", ["INC-002"], "Promotion effective 16 Aug paid at the full new rate for August")

    r = row(date(2026, 9, 1), "E20")
    r["PT"] = 0
    _recompute(r)
    plant(date(2026, 9, 1), "E20", ["STAT-008"], "Karnataka PT Rs 200 not deducted")
    plant(date(2026, 9, 1), "E16", ["PF-010"], "Master still excludes her from EPS; with the Rs 25,000 ceiling she "
                                              "must be brought in from 17 Sep (corrected in the October master)")

    r = row(date(2026, 10, 1), "E02")
    r["PF Employee"] = float(r["PF Employee"]) + float(r["PF Employee Arrear"] or 0)
    _recompute(r)
    plant(date(2026, 10, 1), "E02", ["PF-012"], "September PF shortfall recovered twice: in the PF line and as an arrear")
    r = row(date(2026, 10, 1), "E05")
    r["ESIC Employee"] = int((D(str(r["Gross"])) * D("0.0075")).to_integral_value(rounding=ROUND_CEILING))
    _recompute(r)
    plant(date(2026, 10, 1), "E05", ["STAT-006"], "ESIC still deducted in the new contribution period; his wage is "
                                                  "above Rs 21,000")

    r = row(date(2026, 11, 1), "E13")
    r["Overtime"] = money(float(r["Overtime"]) / 2)
    r["Gross"] = money(sum(float(r[k] or 0) for k in ("Basic", "HRA", "Special Allowance", "Overtime")))
    _recompute(r)
    plant(date(2026, 11, 1), "E13", ["ATT-023"], "10 hours of overtime paid at the single rate, not twice")

    r = row(date(2026, 12, 1), "E10")
    r["LWF Employee"], r["LWF Employer"] = 12, 36
    _recompute(r)
    plant(date(2026, 12, 1), "E10", ["STAT-009", "STAT-010"], "Maharashtra December LWF at the old Rs 12 / Rs 36; "
                                                            "it is Rs 25 / Rs 75")

    r = row(date(2027, 1, 1), "E22")
    r["Gross"] = float(r["Gross"]) + 1500
    r["Net"] = money(float(r["Gross"]) - r["Total Deductions"])
    plant(date(2027, 1, 1), "E22", ["AGG-001"], "Gross is Rs 1,500 more than the earnings")

    r = row(date(2027, 2, 1), "E07")
    r["PT"] = 200
    _recompute(r)
    plant(date(2027, 2, 1), "E07", ["STAT-008"], "Maharashtra February PT is Rs 300; Rs 200 deducted")

    plant(date(2027, 3, 1), "E18", ["LOP-004"], "One day of LOP reversed again; February had no LOP to reverse")
    months[key(date(2027, 3, 1))]["rows"] = [r for r in months[key(date(2027, 3, 1))]["rows"]
                                             if r["Employee ID"] != "E23"]
    months[key(date(2027, 3, 1))]["attendance"] = [a for a in months[key(date(2027, 3, 1))]["attendance"]
                                                   if a["Employee ID"] != "E23"]
    plant(date(2027, 3, 1), "E23", ["HC-001"], "Paid in February, missing in March, and no exit in the master")


# ── master and CTC files, by month ────────────────────────────────────────────
def master_rows(as_of: date) -> list[dict]:
    out = []
    for p in PEOPLE:
        n = int(p.id[1:])
        out.append({
            "Employee ID": p.id, "Employee Name": p.name, "Date of Joining": p.doj,
            # an exit is on the master from the month it happens
            "Date of Exit": p.dox if p.dox and date.fromisoformat(p.dox).replace(day=1) <= as_of else "",
            "Gender": p.gender, "State": p.state_on(as_of), "Department": "Stores", "Designation": "Associate",
            "Employment Type": "Permanent", "Employment Status": p.status.get(as_of, "Active"),
            "Skill Category": p.skill, "PAN": f"ABCPF{n:04d}K", "EPS Member": "No" if (not p.eps and not (p.id == "E16" and as_of >= date(2026, 10, 1)))
            else "Yes", "UAN": f"1012026500{n:02d}", "ESIC IP Number": f"52000001{n:02d}",
            "Bank Account": f"91002000{n:04d}", "IFSC": "HDFC0001234",
        })
    return out


MASTER_MONTHS = [date(2026, 4, 1), date(2026, 8, 1), date(2026, 10, 1), date(2026, 12, 1), date(2027, 1, 1)]


def ctc_rows(month: date) -> list[dict]:
    """CTC records uploaded in a month: the base in April, then each revision when approved."""
    out = []
    for p in PEOPLE:
        if month == MONTHS[0]:
            eff = p.doj if p.doj > "2025-04-01" else "2025-04-01"
            s = p.structure(p.basic)
            out.append({"Employee ID": p.id, "Employee Name": p.name, "Effective From": eff,
                        **{k: v * 12 for k, v in s.items()}, "Annual CTC": sum(s.values()) * 12})
        for eff, nb, approved in p.revisions:
            if approved == month:
                s = p.structure(nb)
                out.append({"Employee ID": p.id, "Employee Name": p.name, "Effective From": eff,
                            **{k: v * 12 for k, v in s.items()}, "Annual CTC": sum(s.values()) * 12})
    return out


def write(path: Path, rows: list[dict], headers: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=headers or list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def readme() -> str:
    lines = []
    for m in MONTHS:
        k = key(m)
        files = ["`attendance.csv`", "`salary_register.csv`"]
        if m in MASTER_MONTHS:
            files.insert(0, "`employee_master.csv`")
        if ctc_rows(m):
            files.insert(1 if m in MASTER_MONTHS else 0, "`ctc.csv`")
        planted = EXPECTED.get(k, {})
        lines.append(f"### {m:%B %Y}\n\nLoad from `months/{k}/`: {', '.join(files)}.\n")
        if planted:
            lines.append("| Employee | Mistake | Must report |\n| --- | --- | --- |")
            lines += [f"| {e} | {why} | {', '.join(rules)} |" for e, (rules, why) in sorted(planted.items())]
        else:
            lines.append("No planted mistakes this month.")
        lines.append("")
    people = "\n".join(f"| {p.id} | {p.name} | {p.state} | {p.skill} | {p.note} |" for p in PEOPLE)
    return f"""# Full financial year test company: April 2026 to March 2027

A dummy retail company, 24 employees in Karnataka and Maharashtra, run through a whole year:
increments approved late and paid with arrears, a mid-month promotion, a back-dated promotion,
a joiner, a leaver, a transfer, a salary on hold, LOP and its reversal, overtime, the PF ceiling
rising to Rs 25,000 on 17 September 2026 with the shortfall recovered in October, the ESIC
contribution period turning in October, a minimum-wage VDA revision, Maharashtra LWF in June
and December and Maharashtra's February PT. Nothing here is real.

Every payslip is worked out by the generator's own payroll rules, independently of the product,
and one or two mistakes are planted each month. Regenerate with
`cd backend && PYTHONPATH=. python ../testdata/payroll-fy2026-27/generate.py`.

## How to run the year

1. Create a company (Setup -> Companies) and upload `1_configuration.csv` (Setup -> Configuration upload).
2. Then, month by month from April 2026, open the month's folder and load its files in this order:
   employee master (Data & imports -> Employee master, effective the 1st of that month), CTC
   (Data & imports -> CTC upload), attendance (Data & imports -> Attendance, that month), and the
   salary register (Control Centre -> Check a register, that month). Validate, then compare the
   results with the month's table below.
3. Every planted mistake must be reported; everyone else must have no warning or critical finding.
   Information notes (a new joiner, a Maharashtra employee with no minimum-wage rate loaded, the
   September PF shortfall) are expected.

The automated version of this is `backend/tests/test_full_year.py`.

## Rules in the configuration (test values)

* PF 12% of Basic, restricted to the ceiling: Rs 15,000 until 16 Sep 2026, Rs 25,000 from 17 Sep.
  September is worked on the old ceiling (a shortfall the tool notes), recovered in October as a
  "PF Employee Arrear" line. PF on arrears: each earlier month to its own ceiling.
* ESIC 0.75% rounded up; covered while the full-month wage is Rs 21,000 or less, and to the end of
  the contribution period (April-September, October-March) once covered. Overtime counts.
* PT: Karnataka Rs 200 from Rs 25,000. Maharashtra men Rs 175 / Rs 200 (Rs 300 in February); women nil
  up to Rs 25,000, then Rs 200 (Rs 300 in February).
* LWF: Maharashtra Rs 25 (employer Rs 75) in June and December.
* Minimum wage, Karnataka, on the CTC: unskilled Rs 14,000 and skilled Rs 16,500 to September; Rs 14,500
  and Rs 17,000 from October (VDA revision).

## The people

| ID | Name | State | Skill | What happens to them |
| --- | --- | --- | --- | --- |
{people}

## Month by month

{chr(10).join(lines)}
"""


if __name__ == "__main__":
    year = build()
    mistakes(year)
    if (HERE / "months").exists():
        shutil.rmtree(HERE / "months")
    (HERE / "1_configuration.csv").write_bytes(tables_to_csv(configuration()))
    for m in MONTHS:
        folder = HERE / "months" / key(m)
        if m in MASTER_MONTHS:
            write(folder / "employee_master.csv", master_rows(m))
        if ctc_rows(m):
            write(folder / "ctc.csv", ctc_rows(m))
        write(folder / "attendance.csv", year[key(m)]["attendance"])
        write(folder / "salary_register.csv", year[key(m)]["rows"], HEAD)
    (HERE / "README.md").write_text(readme(), encoding="utf-8")
    answer = {k: {e: {"rules": r, "mistake": w} for e, (r, w) in v.items()} for k, v in sorted(EXPECTED.items())}
    (HERE / "answer_key.json").write_text(json.dumps(answer, indent=1) + "\n", encoding="utf-8")
    print(f"{len(MONTHS)} months, {len(PEOPLE)} people, {sum(len(v) for v in EXPECTED.values())} planted mistakes")
