# Disbursement validation

Checks whether a salary payment file is safe to release to the bank, produces a
clean file without the rows that are not, and leaves the release to a person.

**It never pays anyone and never sends a file anywhere.** No bank connection,
no SFTP, no payment API exists in this module or is planned for it. It reads the
file the HRMS produced, judges it, and hands back a verdict, a clean copy and an
approval pack.

## Current state

| Step | What | State |
|---|---|---|
| 1 | Rule engine (DSB-01 … DSB-17), verdict, bridge; bank file templates and clean file with SHA-256; input readers and the two mapping profiles; synthetic generator with answer keys; tests | **Built** (1 Oct 2026) |
| 2 | Exception report (CSV, XLSX) and approver summary (PDF), all drawn from one stored report | **Built** (3 Oct 2026) |
| 3 | Storage: runs, per-company settings, approval records; API with tenancy and roles | Planned |
| 4 | Page: upload, verdict, findings, downloads, printable summary, approval | Planned |
| 5 | Manuals and handbook routes | Planned |

Step 1 has no page or endpoint yet. It is reachable from code and from the
generator's `--check` mode only.

## Inputs

| Input | Needed | Read as |
|---|---|---|
| Bank payment file (the file under test) | Required | A bank file template |
| Payroll register, current period: net pay, and where the HRMS gives them reimbursements, salary held, held salary released and **total salary** | Required | A mapping profile |
| Bank master: account, IFSC, beneficiary name, verification status, last changed | Optional | A mapping profile |
| Bank detail change log | Optional | A mapping profile |
| Previous period (register or bank file, as a table): net pay and/or total salary | Optional | A mapping profile |
| Hold list: F&F processed, separated, on hold, with reason | Optional | A mapping profile |
| Off-cycle payments already made this period | Optional | A mapping profile |

CSV and XLSX. Every cell is read as text: account numbers keep their leading
zeros and never pass through a float, so scientific notation cannot appear. An
account number that a spreadsheet already turned into `1.23457E+17` is reported
as such (DSB-12), because the lost digits cannot be recovered.

**Mapping** extends the Studio mapping engine (`services/studio/mapping.py`):
six new object types (`disbursement_register`, `bank_master`, `bank_change_log`,
`previous_period`, `hold_list`, `offcycle_payments`) whose mappings are ordinary
specifications — source column, aliases, lookups, recorded defaults — validated
by the same `check_spec`. Values are parsed by this module, so an unreadable
cell becomes a note on its row rather than a rejected row that vanishes.

Two profiles ship, both built from synthetic layouts and copied from no client:

* **Generic** — plain column names (`Employee ID`, `Net Pay`, `Account Number` …)
  with common alternatives accepted; bank file `generic_csv`.
* **Darwinbox-style** — column names and status words in the style of a Darwinbox
  export (`Employee Code`, `Net Salary`, `Employment Status: Resigned` …); bank
  file `batch_pipe_hdt`. Check each column against your own export.

## What the bank should pay: total salary, not net pay

The bank file does not pay net pay. After net pay come **reimbursements** (paid
with salary but outside it), **salary held** this month (withheld, paid later) and
**held salary released** from an earlier month. The amount a payment line must
equal is the **total salary payable**:

    total salary = net pay + reimbursements + held salary released − salary held

The engine takes it, in this order:

1. **The register's own total salary column** (`Total Salary`, `Total Salary
   Payable`, `Net Payable`, `Take Home` …) — what the HRMS told the bank to pay.
2. **Built from its parts** when there is no total column but there are
   reimbursement / salary hold / hold release columns. DSB-08 says so.
3. **Net pay** when the register has none of these. DSB-08 says plainly that
   reimbursements and held salary could not be allowed for, so the difference
   it reports may be one of them.

DSB-08 (amount), DSB-15 (missing from the file), DSB-01 (clean file against the
register) and the bridge all use this amount. An employee whose salary is held
in full has nothing payable and is not expected in the file. DSB-13 (variance)
stays on net pay when both periods give it, because total salary swings with
reimbursements and holds; it falls back to total salary otherwise and says so.

**DSB-17** checks the register against itself: when it states total salary *and*
the parts, the total must equal net pay + reimbursements + released holds − held.
The bank pays the stated total, so a total that does not add up is money that
may be wrong even though the file matches the register. Default FLAG; a company
can make it HOLD_ROW. It is NOT_RUN when the register gives no total, or a total
with no reimbursement or hold column to explain how it differs from net pay.

## Bank file templates

A template (`app/data/disbursement/templates/*.json`) is data: columns and their
order, delimiter, an optional column-header row, an optional **header record**
(debit account, value date, record count, total) and **footer record** (count,
total), and how dates and amounts are written. Two ship, both generic and
synthetic, neither labelled as any bank's format:

* `generic_csv` — a row of column names, one line per payment.
* `batch_pipe_hdt` — `H|debit account|value date|count|total`, then `D|…` per
  payment, then `T|count|total`.

Delimited text and Excel are supported. Fixed-width layouts are not yet (the
existing reconciliation reader does handle them).

**The clean file** copies kept payment lines byte for byte — same order, quoting
and line endings, byte-order mark kept — and rewrites only the count and total in
the header and footer records. A workbook is rebuilt with fixed timestamps.
Either way the same input gives the same bytes and so the same SHA-256.

## The checks

| ID | Check | Default | Needs |
|---|---|---|---|
| DSB-01 | Total does not reconcile (see below) | STOP_FILE | bank file, register |
| DSB-02 | Row count does not reconcile (see below) | STOP_FILE | bank file, register |
| DSB-03 | Paid in the file, not in the register (or no employee code) | STOP_FILE | bank file, register |
| DSB-04 | Header debit account or value date is not the configured one | STOP_FILE | header record, configured values |
| DSB-05 | Same account number on two or more employees — all of them held | HOLD_ROW | bank file |
| DSB-06 | Bank details changed since the previous period and not verified | HOLD_ROW | bank master with verification column, plus change log or previous period |
| DSB-07 | Amount zero, negative, or unreadable | HOLD_ROW | bank file |
| DSB-08 | Amount differs from total salary payable in the register (see above) | HOLD_ROW | bank file, register |
| DSB-09 | Separated before the period, F&F processed, or on hold | HOLD_ROW | hold list or register status columns |
| DSB-10 | Employee appears more than once — every line held | HOLD_ROW | bank file |
| DSB-11 | Already paid off-cycle this period | HOLD_ROW | off-cycle payments |
| DSB-12 | IFSC not 4 letters + 0 + 6 letters/digits; account blank, not digits, or outside 9–18 digits | HOLD_ROW | bank file |
| DSB-13 | Net pay changed more than 25% against the previous period, excluding joiners, exits, arrears and increments (total salary if the previous period has no net pay) | FLAG | register, previous period |
| DSB-14 | Beneficiary name does not match (case, spacing, salutations, initials, small spelling differences ignored; threshold 0.80) | FLAG | bank file and register names |
| DSB-15 | Due in the register, not in the file, not on hold or already paid off-cycle | FLAG | bank file, register |
| DSB-16 | Account or IFSC in the file is not the one on the bank master | HOLD_ROW | bank master |
| DSB-17 | Total salary in the register is not net pay + reimbursements + released holds − salary held | FLAG | register with total salary, net pay and a reimbursement or hold column |

DSB-16 and DSB-17 were not in the original brief. DSB-16 was added at review because a file that
pays an account other than the one on record is the most direct way money goes
astray, and it is how a lost leading zero shows itself. DSB-17 came with the correction that
the bank pays total salary, not net pay (above).

**Severities are per company.** Each check can be switched off (reported as
DISABLED, never as passed) or moved between the severities that make sense for
it: a check about a line can be STOP_FILE, HOLD_ROW or FLAG; a check about the
whole file can be STOP_FILE or FLAG.

### DSB-01 and DSB-02: why the file checks do not re-count the row problems

Read literally, "file total ≠ register total" fires on every duplicate line,
wrong amount or held employee, because each of those changes the total — so a
single bad line would stop everyone's salary, and a month with only row-level
problems could never be released. Three readings were compared:

| Option | What it compares | Why not / why |
|---|---|---|
| A. Literal | Raw file against the register | Any row error stops the whole file. Rejected |
| B. Clean file only | After holds, the clean file against the register | True by construction; catches almost nothing. Rejected |
| **C. Bridge** | Every rupee and line of difference explained by a named finding; the file stops only on what no row finding explains | **Chosen** |

Under C, DSB-01 stops the file when:

1. the header or footer states a total that is not the sum of the lines — the
   file disagrees with itself;
2. after the held lines are removed, the clean file does not equal the register's
   total salary payable for the employees it pays (beyond `total_tolerance`,
   default ₹0);
3. the held lines add up to more than `max_hold_share_pct` (default 25%) of the
   file's value — a file that wrong is more likely the wrong run or month than a
   file with a few wrong lines.

DSB-02 stops the file when the header or footer states a count that is not the
number of lines, when nothing would be left to pay, when held lines are more than
25% of the lines, or when more than 25% of the employees due are missing.

**The bridge** shown to the approver walks from the register's total due to the
file total and on to the clean file, one named line at a time (missing employees,
paid but not in the register, paid but not due, duplicates, amount differences,
held lines). It is arithmetic, shown as such, and the tests prove it closes to the
paisa.

### DSB-06: what "verified" means

A changed account is the classic route for salary fraud and the commonest source
of a failed credit. "Verified" means the company has confirmed the new details
belong to the employee — typically a ₹1 test credit that returns the account
holder's name ("penny drop"), a cancelled cheque, or a bank letter — and recorded
that in the HRMS. The bank master's verification column carries it.

* Accepted as verified (configurable): verified, yes, y, true, 1, approved,
  validated, success, penny drop success, active. Anything else — pending,
  rejected, blank, an unknown word — is not verified, and the finding quotes the
  value.
* A change is seen from the change log (dated within or after the previous
  period), or from the previous period's account or IFSC differing from the
  master's. The master's last-changed date adds supporting evidence.
* A change-log entry's own verification status, when given, wins over the
  master's.
* No verification column at all: the check is NOT_RUN, never assumed either way.

## Verdict

* Any STOP_FILE finding → **DO_NOT_RELEASE**, and no clean file is produced.
* Otherwise any held line → **RELEASE_WITH_HOLDS**, with the count and amount held.
* Otherwise → **CLEAR_TO_RELEASE**.

Checks that could not run (NOT_RUN) do not change the verdict but are listed with
it, every time, with the reason; the approval step (step 3) will require each to be
acknowledged.

## What people receive

Every output is drawn from one *report* — plain data the run produces and the
database keeps — so a report downloaded a week later is the same document
(`services/disbursement/outputs.py`; `check.py` runs a check end to end).

* **Exception report, CSV** — one row per finding: check, severity, employee,
  field, expected, actual, amount in the file, bank file rows, reason. Checks that
  did not run are rows with severity NOT_RUN and the reason; checks the company
  switched off are rows with severity DISABLED. Free text that a spreadsheet would
  run as a formula (`= + - @`) is written with a leading apostrophe; amounts stay
  numbers. UTF-8 with a byte-order mark so Excel reads ₹.
* **Exception report, Excel** — sheets Summary, Findings, Checks (every check's
  status), Bridge, Inputs (each file's name, rows and SHA-256) and Notes (values
  that could not be read, defaults used). No cell is a formula; IDs and accounts
  are text.
* **Approver summary, PDF** — the verdict and what it means; amount and headcount
  the clean file pays; held employees with every reason and the amount held;
  flags by check; the checks that did not run; total against the previous period;
  the register-to-file bridge; the clean file's SHA-256 and each input's; and the
  approval block. The same report gives the same bytes. When the file is stopped
  the held figures are labelled "would be held": nothing is released.

**Account numbers and IFSCs are shown in full** in all three. Masking them would
defeat the check — the approver is being asked whether these are the right
accounts. Who can download them is therefore the control (step 3).

## Settings and defaults

| Setting | Default |
|---|---|
| `variance_pct` (DSB-13) | 25 |
| `name_similarity` (DSB-14) | 0.80 |
| `account_length_min` / `max` (DSB-12) | 9 / 18 |
| `amount_tolerance` per employee (DSB-08, DSB-17) | ₹0.00 |
| `total_tolerance` clean file (DSB-01) | ₹0.00 |
| `max_hold_share_pct` (DSB-01, DSB-02; 0 = off) | 25 |
| `debit_account` (DSB-04) | none — DSB-04 NOT_RUN until set |
| value date (DSB-04) | given per run |
| `severities`, `enabled` | per check, as above |

An unknown setting, a severity a check cannot take, or an out-of-range value is
refused, not silently replaced.

## Synthetic data and the answer key

```bash
cd backend
python tools/disbursement_synth.py --out /tmp/dsb --employees 500 --seed 20260901 --scenario all --layout both --check
```

Writes `scenario_{A,B,C,D}_{generic,darwinbox_style}/` with every input file,
`expected_findings.csv` and `scenario.json`, and with `--check` prints planted /
caught / false positives per rule. Names come from generic lists; IFSC codes use
the made-up prefixes `ZZZA0` … `ZZZH0`; account numbers are random. The clean
population claims reimbursements (about a fifth), has some salary held in part or
in full and some earlier holds released, and is untidy on purpose — trailing spaces, lower-case IFSC, amounts as
text with commas, salutations and initials, masters that lost leading zeros — and
must produce no findings.

| Pack | Expected |
|---|---|
| A clean month | CLEAR_TO_RELEASE, zero findings |
| B row errors only | RELEASE_WITH_HOLDS; every hold and flag check planted at least twice |
| C file-level breaks | DO_NOT_RELEASE |
| D optional inputs missing | DSB-06, DSB-11, DSB-13 (and DSB-04 where there is a header) NOT_RUN; the rest still run |

```bash
cd backend && python -m pytest tests/test_disbursement.py -q
```

Results at step 1 (500 employees, both layouts, 41 tests): every rule planted at
least twice, every planted case caught, zero false positives. 10,000 employees are
read, checked and given a clean file in about 2 s (CSV) and 4 s (XLSX).

## Known limitations at step 1

* Fixed-width bank files are not supported by the template layer yet.
* The previous period is read as a table (CSV/XLSX with columns), not through a
  bank file template.
* A quoted field containing a line break inside a delimited bank file is not
  supported; such files are rare and would be reported as unreadable lines.
* Results are not stored yet, and there is no approval record until step 3.
