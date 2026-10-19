# Payroll validation manual-test pack (August 2026)

Dummy data for testing the Payroll Validation module end to end. Nothing here is real.
Regenerate with `cd backend && PYTHONPATH=. python ../testdata/payroll-validation/generate.py`.

## Load order (about 5 minutes)

| Step | Where | File |
| --- | --- | --- |
| 1 | Configuration & admin -> **Configuration upload** (preview, then apply) | `1_configuration.csv` or `1_configuration.xlsx` |
| 2 | Data & imports -> **Employee master** (effective 2026-04-01) | `2_employee_master.csv` |
| 3 | Data & imports -> **CTC upload** (effective 2026-04-01) | `3_ctc_report.csv` |
| 4 | Data & imports -> **Attendance** (period August 2026) | `4_attendance_report.csv` |
| 5 | Data & imports -> **Salary register**, period **July 2026**, then Run validation (this is last month, so August can be compared with it) | `6_previous_month_register_july.csv` |
| 6 | Data & imports -> **Salary register**, period **August 2026**, then Run validation. Open Results | `5_salary_register.csv` |

Step 1 is the *one-file* setup: salary components and their PF/ESIC/PT flags, PF ceiling 25,000,
ESIC ceiling 21,000, PT states and slabs, and the PF/ESIC formulas in Excel style (inside the Statutory engine settings). It replaces only
the sections it contains.

## Rules in the configuration

* PF: employee 12% of (Basic + Special Allowance), wage capped at 25,000 (so at most 3,000).
* ESIC: 0.75% of ESIC wage (Basic, HRA, Special Allowance, Conveyance) rounded up, only while that wage is 21,000 or less.
* PT: Karnataka 200 from 25,000 gross; Maharashtra 175 from 7,501 and 200 above 10,000 (test values).
* The PF/ESIC *formulas* are applied: when a formula is set it is the expected employee PF/ESIC for every row, so the
  payslips in this pack follow them. To try your own rule, change the PF formula under Statutory engine (for example
  `IF(basic<=25000, MIN((basic+special_allowance)*12%, 3000), basic*12%)`) and re-run August: the employees above 25,000
  will now be expected at 12% of Basic, and the tool will say so.

## Answer key -- what the tool should report

Everyone not listed here is correct and should produce **no** finding for the issues named below.

| Employee | Planted problem |
| --- | --- |
| E004 | ESIC not deducted although ESIC wage is within 21,000 |
| E005 | PF not deducted at all (PF Employee = 0) |
| E015 | Professional tax missing for a Karnataka employee earning above 25,000 |
| E019 | ESIC deducted although ESIC wage is above 21,000 |
| E021 | PF deducted on full Basic above the ceiling (12% of the whole wage, not capped at 25,000) |
| E024 | Professional tax is 150, the Karnataka slab says 200 |
| E026 | Gross does not equal the sum of the earnings |
| E027 | Net does not equal Gross minus Total Deductions |
| E028 | Paid days (31) disagree with the attendance report (28) |
| E029 | Basic is 5,000 higher than the CTC letter allows |
| E030 | Paid in August after the exit date of 31 Jul 2026 |
| E031 | Joined 20 Aug 2026 but paid a full month of 31 days |
| E033 | Salary lines appear twice in the register (duplicate row) |
| E036 | 8 overtime hours in attendance but no overtime paid |
| E037 | Attendance file contradicts itself: 20 present + 4 off + 1 holiday does not reach 31 |
| E038 | On the attendance report and master, but missing from the salary register |
| E040 | On the attendance report and in the register, but NOT in the employee master |

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

### Reports to compare with

`sample-reports/` holds what the product produced for this pack: the validation results workbook, the
parallel-run pack, the findings and attendance-check lists as CSV, a one-page summary and every Report
Centre workbook. Compare your own run with them. Regenerate with
`cd backend && PYTHONPATH=. python ../testdata/payroll-validation/generate_reports.py`.

### Notes

* TDS in the registers equals the product's own Section 192 projection (new regime), so a correct payslip raises no TDS finding.
* The PT/LWF slabs and minimum-wage decision are test values.
