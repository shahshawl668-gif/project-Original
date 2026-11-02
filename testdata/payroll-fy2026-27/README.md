# Full financial year test company: April 2026 to March 2027

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
| E01 | Arvind Rao | Karnataka | Skilled | above both PF ceilings |
| E02 | Bindu Nair | Karnataka | Skilled |  |
| E03 | Chetan Patil | Maharashtra | Skilled | PF wage between Rs 15,000 and 25,000 |
| E04 | Deepa Kulkarni | Maharashtra | Skilled |  |
| E05 | Eshwar Gowda | Karnataka | Unskilled | ESIC-covered; the July increment takes him over Rs 21,000 |
| E06 | Fathima Begum | Karnataka | Unskilled | ESIC-covered all year |
| E07 | Ganesh Jadhav | Maharashtra | Unskilled | Maharashtra PT incl. February |
| E08 | Harish Shetty | Karnataka | Skilled | joined 15 May |
| E09 | Indira Menon | Karnataka | Skilled | left 20 Aug |
| E10 | Jagdish Pawar | Karnataka | Skilled | transferred to Maharashtra from August |
| E11 | Kiran Bhat | Karnataka | Skilled | promoted 16 Aug |
| E12 | Lakshmi Iyer | Karnataka | Skilled | promotion effective 1 Nov, approved in January |
| E13 | Mohan Das | Karnataka | Skilled | overtime in November |
| E14 | Nisha Deshmukh | Maharashtra | Skilled | April increment with arrears in July |
| E15 | Om Prakash | Karnataka | Skilled | kept out of EPS, wage above Rs 25,000: stays out |
| E16 | Pooja Hegde | Karnataka | Skilled | kept out of EPS, wage within Rs 25,000: brought in from October |
| E17 | Rakesh Kumar | Karnataka | Skilled | on hold in December |
| E18 | Sunita Rao | Karnataka | Skilled | LOP in November, one day reversed in December |
| E19 | Tarun Joshi | Karnataka | Skilled |  |
| E20 | Uma Shankar | Karnataka | Skilled |  |
| E21 | Vivek Sawant | Maharashtra | Skilled |  |
| E22 | Waheeda Khan | Karnataka | Skilled |  |
| E23 | Yash Kamath | Karnataka | Skilled |  |
| E24 | Zara Fernandes | Maharashtra | Skilled |  |

## Month by month

### April 2026

Load from `months/2026-04/`: `employee_master.csv`, `ctc.csv`, `attendance.csv`, `salary_register.csv`.

| Employee | Mistake | Must report |
| --- | --- | --- |
| E19 | PF Rs 3,600 on the full basic; PF is restricted to Rs 15,000 (Rs 1,800) | PF-009 |

### May 2026

Load from `months/2026-05/`: `attendance.csv`, `salary_register.csv`.

| Employee | Mistake | Must report |
| --- | --- | --- |
| E08 | Joined 15 May but paid the full month (31 days against 17 in attendance) | MST-006, ATT-001 |

### June 2026

Load from `months/2026-06/`: `attendance.csv`, `salary_register.csv`.

| Employee | Mistake | Must report |
| --- | --- | --- |
| E07 | Maharashtra June LWF not deducted (employee Rs 25, employer Rs 75) | STAT-009, STAT-010 |

### July 2026

Load from `months/2026-07/`: `ctc.csv`, `attendance.csv`, `salary_register.csv`.

| Employee | Mistake | Must report |
| --- | --- | --- |
| E14 | April increment arrears paid for two months; April to June is three | MOM-006 |

### August 2026

Load from `months/2026-08/`: `employee_master.csv`, `ctc.csv`, `attendance.csv`, `salary_register.csv`.

| Employee | Mistake | Must report |
| --- | --- | --- |
| E11 | Promotion effective 16 Aug paid at the full new rate for August | INC-002 |

### September 2026

Load from `months/2026-09/`: `attendance.csv`, `salary_register.csv`.

| Employee | Mistake | Must report |
| --- | --- | --- |
| E16 | Master still excludes her from EPS; with the Rs 25,000 ceiling she must be brought in from 17 Sep (corrected in the October master) | PF-010 |
| E20 | Karnataka PT Rs 200 not deducted | STAT-008 |

### October 2026

Load from `months/2026-10/`: `employee_master.csv`, `attendance.csv`, `salary_register.csv`.

| Employee | Mistake | Must report |
| --- | --- | --- |
| E02 | September PF shortfall recovered twice: in the PF line and as an arrear | PF-012 |
| E05 | ESIC still deducted in the new contribution period; his wage is above Rs 21,000 | STAT-006 |

### November 2026

Load from `months/2026-11/`: `attendance.csv`, `salary_register.csv`.

| Employee | Mistake | Must report |
| --- | --- | --- |
| E13 | 10 hours of overtime paid at the single rate, not twice | ATT-023 |

### December 2026

Load from `months/2026-12/`: `employee_master.csv`, `attendance.csv`, `salary_register.csv`.

| Employee | Mistake | Must report |
| --- | --- | --- |
| E10 | Maharashtra December LWF at the old Rs 12 / Rs 36; it is Rs 25 / Rs 75 | STAT-009, STAT-010 |

### January 2027

Load from `months/2027-01/`: `employee_master.csv`, `ctc.csv`, `attendance.csv`, `salary_register.csv`.

| Employee | Mistake | Must report |
| --- | --- | --- |
| E22 | Gross is Rs 1,500 more than the earnings | AGG-001 |

### February 2027

Load from `months/2027-02/`: `attendance.csv`, `salary_register.csv`.

| Employee | Mistake | Must report |
| --- | --- | --- |
| E07 | Maharashtra February PT is Rs 300; Rs 200 deducted | STAT-008 |

### March 2027

Load from `months/2027-03/`: `attendance.csv`, `salary_register.csv`.

| Employee | Mistake | Must report |
| --- | --- | --- |
| E18 | One day of LOP reversed again; February had no LOP to reverse | LOP-004 |
| E23 | Paid in February, missing in March, and no exit in the master | HC-001 |

