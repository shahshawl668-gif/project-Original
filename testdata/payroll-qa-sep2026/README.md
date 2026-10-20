# Payroll QA month (September 2026)

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
| C02 | CTC break-up 13,600 (Basic + Conveyance + Other Allowance, HRA excluded) is below the Karnataka unskilled minimum of 14,000 | MW-001 |
| C04 | CTC break-up 11,000 (HRA excluded) is below the Karnataka unskilled minimum of 14,000 | MW-001 |
| C06 | 3 days of LOP in attendance, but the full month was paid | ATT-001, ATT-002, ATT-020 |
| C08 | Increment effective 16 Sep paid at the full new rate for the whole month | INC-002 |
| C11 | Increment effective 1 Aug: September paid at the new rate but the August arrear (3,000 Basic + 1,200 HRA) was not paid | MOM-006 |
| C12 | PF 3,600 deducted on the full Basic, but PF is restricted to the 15,000 ceiling (1,800) | PF-009 |
| C13 | ESIC not deducted although the ESIC wage of 20,500 is within 21,000 | STAT-006 |
| C14 | Maharashtra PT of 200 charged to a woman earning 22,000 (nil up to 25,000 for women) | STAT-008 |
| C18 | Maharashtra LWF deducted in September; it is due only in June and December | STAT-009 |
| C19 | Gross is 2,000 more than the sum of the earnings | AGG-001 |
| C21 | New CTC 15,000 excluding HRA is below the Karnataka skilled minimum of 16,500 (the arrear itself is correct) | MW-001 |
| C23 | CTC 13,200 excluding HRA is below the Karnataka skilled minimum of 16,500 | MW-001 |

Everyone else is correct and must produce no warning or critical finding. The ones that prove the
tool does not over-report:

| Employee | Why it is correct |
| --- | --- |
| C01 | above both ceilings |
| C03 | exactly at the minimum wage, with an 'Other Allowance' that counts towards it |
| C05 | 4 days LOP, prorated |
| C07 | increment from 16 Sep, paid 15 days old + 15 days new |
| C09 | increment from 1 Jul, July and August arrear paid; PF already at the ceiling |
| C10 | increment from 16 Jun, arrear for half of June, July and August; PF on the arrear |
| C15 | Maharashtra PT 175 for a man earning 7,501-10,000 |
| C16 | joined 11 Sep, paid 20 days; rate 24,400 so outside ESIC |
| C17 | left 20 Sep, paid 20 days |
| C20 | high earner, clean |
| C22 | 6 days LOP: earned basic 12,800, so PF is below the ceiling |
| C24 | gross exactly 25,000: Karnataka PT 200 |
| C25 | ESIC wage exactly 21,000: covered |

### Expected background (not mistakes)

* `LC-001` (warning) for C01 and C22: the Code on Wages test takes wages as the PF-applicable
  components unless the company names its wage components; Special Allowance is not PF-applicable
  here. It is a structure review point, not a payroll error.
* `ARR-004` (info) for C09: the arrear carries no further PF because the wage was already at the
  ceiling.
* `MOM-001` (info) for the September joiners; `MW-003` (info) for Maharashtra staff, where no minimum
  wage rate is loaded.
