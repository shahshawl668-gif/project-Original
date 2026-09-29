# Peopleopslab — User Manual

For the people who use Peopleopslab each month: payroll, HR and finance staff at
a client company.

You do not need to understand the rule engine to use this. You need to know
where to put the file, what the answers mean, and what to do about them.

---

## 1. What this does for you

You run payroll in whatever system you already use. Peopleopslab takes the
register that comes out of it and independently works out what the statute says
should have been there — PF, ESIC, professional tax, labour welfare fund, income
tax — then tells you every place the two disagree, what it costs, and what to do.

It also checks two things a register cannot check about itself:

- **Attendance** — whether people were paid for the days they actually worked.
- **Bank and ledger** — whether what the register says was due is what actually
  left the bank and what actually hit the accounts.

**It never pays anyone and never changes your payroll.** Nothing you do here
alters a payslip.

---

## 2. Signing in

Your administrator sends an invitation link. It works once, expires after seven
days, and only for the email address it was sent to. Open it and set your
password.

From then on, sign in at **your workspace's own address**, which your
administrator gives you with the invitation — for example
`https://www.peopleopslab.in/w/acme-industries/login`. Bookmark it. Your email
and password work only there; at any other address they are refused, with the
same message as a wrong password.

![Sign in](images/00-login.png)

After signing in you land on **Companies**.

---

## 3. Finding your way around

### Companies — the landing page

Every company you have access to, each with its own state, ordered so the one
needing attention is first.

![Companies](images/01-companies.png)

Each card shows the latest period, how many people were on it, open findings,
anything critical, and the total financial exposure. **Open** selects that
company and takes you into its work. A company with nothing uploaded says so.

### Payroll Control Centre — the month in one place

**Overview → Payroll Control Centre** shows one month for one company: which
files have arrived, how validation is going, what is still open, what changed
since the previous run, what blocks approval, whether the bank and ledger
reconcile, and the evidence pack. At the top it says the **next step** —
upload, validate, work the issues, submit — worked out from where the month
actually stands.

![Payroll Control Centre](images/19-control-centre.png)

The month's state is one of: *Not started*, *Awaiting data*, *Ready to
validate*, *Running*, *Action required*, *Incomplete*, *Ready for approval*,
*Signed off* or *Reopened*. A month with no failed checks is **not** shown as
clean if some statutory checks could not be performed — it says *Incomplete*
and tells you which inputs were missing. Every panel links to the page where
that part is worked, already set to this month and this run.

### The header

The company you are working on is always shown top-right; with several
companies it is a menu, and switching clears everything on screen so nothing
from the previous company stays behind. On month pages (the Control Centre,
upload, results, issues, month close) the **working period** and the month's
**current run** sit beside it. The period says *latest* until you choose one;
your choice is remembered per company until you close the browser.

### The sidebar

Tasks in the order a month is worked. The two long groups, Studio and
Configuration, open when you are in them.

![The navigation](images/15-sidebar-settings-open.png)

| Group | What is inside |
|---|---|
| **Overview** | Payroll Control Centre, Companies |
| **Data & imports** | Salary register, Register history, Attendance, CTC upload and history, Budget |
| **Validation & findings** | Validation runs, Results, Issues |
| **Reconciliation & approvals** | Month close & approval, Bank payments, Journal voucher |
| **Analytics & dashboards** | Dashboards, Cost analysis |
| **Reports** | Report Centre, Report Builder |
| **Studio** | Connections to your other systems: the API Centre, connections, data mapping, workflows, webhooks, developer tools, releases, and the run history of every batch they sent (analysts and above) |
| **Configuration & admin** | Companies, statutory settings, rules, formulas, slabs, bank and JV formats, team, audit trail |

---

## 4. The monthly routine

Once payroll is run and before it is paid:

```
  1  Upload attendance        →  do the days add up?
  2  Upload the register      →  does the pay match the statute and the days?
  3  Work the findings        →  fix, or explain (Validation & findings → Issues)
  4  Reconcile the bank file  →  did the right money reach the right accounts?
  5  Post the journal voucher →  does the ledger agree?
  6  Sign the period off      →  closed, with a record of who closed it
```

You can do 1 and 2 in either order, but attendance first is better: it lets the
product tell you that someone lost three days the register never deducted.

---

## 5. Step by step

### Step 1 — Attendance

**Data & imports → Attendance.** Upload the month's attendance, then
**validate** before committing.

![Attendance](images/04-attendance.png)

The file is checked against itself first: calendar days, present days, paid
leave, weekly offs, holidays, loss of pay and paid days all have to add up. **If
it contradicts itself, nothing is stored.** That is deliberate — a timesheet
that does not add up produces confident, wrong conclusions about the pay.

Fix the file and upload again. When it validates clean, commit it.

### Step 2 — Upload the register

**Data & imports → Salary register.** Four stages, shown across the top; each
says what happened before the next one starts.

![Salary register — mapping columns](images/02-payroll-upload.png)

1. **Choose file** — CSV or Excel, straight out of your payroll system, with
   the payroll month and the run type. The page lists what the file needs: an
   Employee ID column and, with the strict header check on, one column per
   salary component. *Regular* replaces the month's register used by cost
   reports and dashboards; *arrear* runs are validated but leave it alone.
2. **Map columns** — each column in your file beside a sample of its values
   and the field it maps to. A suggestion says how it was found (*same name* or
   *known alias*); anything you change says *set by you*; a column nobody maps
   is *not imported* — it is never guessed to be an earning. Required fields
   that are still unmapped are listed on the right, and the next step waits for
   them. Search the columns, apply a saved format, or save this one for next
   month.
3. **Server check** — the file is uploaded and read on the server: employees
   read, columns imported and ignored, the revision number for the month, and
   whether it replaced the month's register. Rows are not rejected here; a row
   with a wrong or missing value is reported by validation as a finding against
   that employee. Uploading the same month again adds a new revision; earlier
   revisions are kept with the runs that read them.
4. **Validate** — queues the full statutory pass.

**Validation runs on the server, not in your browser.** After you press
**Run validation** you are taken to a progress page showing the stage (reading
the register, checking employees, saving results) and how many employees have
been checked. **You can close the page** — the validation keeps going, the
upload page shows a link back to it, and **Validation & findings → Validation runs** lists every
validation with its outcome. A large register (thousands of employees) takes a
few minutes.

![Validation progress](images/16-validation-progress.png)

- **Cancel** stops it; nothing from a cancelled attempt is kept.
- If it **fails**, the page says why and what to fix. **Retry** is always safe:
  a failed attempt saves nothing, so retrying cannot produce duplicates.
- Pressing Validate twice, or in two tabs, does not start two validations — the
  second joins the first.

**Every upload is kept.** Re-uploading a corrected file does not erase the first
one: each upload records the file's fingerprint (SHA-256) and a revision number,
so months later you can show exactly which file was checked.

### Step 3 — Read the results

![Results](images/03-payroll-results.png)

Results are a **run**: a numbered, dated record of one validation of one month.
Validating the month again creates the next run; the earlier one is kept,
marked *superseded*, and still shows exactly what it reported. The chips at the
top of the results page switch between a month's runs, and **Compare** shows
what changed between two of them — which findings are **new**, which were
**resolved**, which **changed** and which are **unchanged**, with the rupee
totals of each.

If anything the result depended on changes after the run — the register is
re-uploaded, the employee master or attendance changes, or a component flag,
rate or rule is edited — the page shows **"Revalidation required"**, names
what changed, and offers to revalidate. A month is never shown as current when
its inputs have moved.

The figures across the top are the run's employees, the critical findings and
warnings still open after waivers, the open exposure, and the high-risk
employees; the ones with an arrow open the matching list. Under them, the
**outcome strip** says how much was checked (see Coverage below) — kept apart
from the issue counts on purpose.

Large results are paged on the server, fifty at a time, with the total always
stated. On **Findings**, filter by severity, check, component, location,
review state or owner, sort by employee, check, severity or impact, and choose
**Grouped by check** to see each check once with its number of findings,
employees and rupee total. Filters are kept in the page address: open a
finding, go back, and the list is as you left it. **Columns** hides or shows
columns and **Compact** fits more rows; both are remembered on this computer.
Click a row (or press Enter on it) for a quick look without leaving the table;
**Excel** downloads the whole run exactly as it was recorded, not re-computed.

Each finding carries a rule ID, a severity, what was expected, what the register
actually said, the difference in rupees, and a suggested fix. Where the product
does not put a rupee figure on a finding — a missing PAN, a duplicate UAN — it
says **"Impact not calculated"**. That is not ₹0; it means the cost was not
worked out, and such findings are left out of the exposure total rather than
added in as nothing. When two checks report the same rupees (PF short under two
rules, say), the total counts them once.

**Coverage — what was checked, not just what failed.** Every check reaches one
of five outcomes for every employee:

| Outcome | Means |
|---|---|
| **Passed** | The check ran and the register agreed |
| **Failed** | The check ran and found a problem — a finding |
| **Cannot validate** | The check needed something you did not supply — a column, the employee master, a minimum-wage decision |
| **Not applicable** | The check does not apply to this person — ESIC above the wage ceiling, say |
| **Disabled** | Your administrator switched the check off |

The strip under the figures shows the counts and a **coverage** percentage: of
the checks that applied, how many reached a verdict. A month with no failures
and 60% coverage has not been shown to be clean — 40% of it was not checked.
The **Coverage** tab lists the inputs that were missing, how many checks each
would have unlocked, and the employees who could not be fully checked. The
employee view lists every check for that person with its outcome and the reason.

![Coverage](images/18-coverage.png)

**Why this result?** Every finding has a **Why?** link. It opens the finding
with everything behind it, in order: the actual, expected and difference and
their rupee impact; the inputs the check read; the rule and the version of it
in force; each step of the calculation with the tolerance and rounding; the
suggested correction; the file, sheet, row and column the value came from; and
the review and approval history. **Back to findings** returns to the list with
its filters. Statutory figures there are your company's
configuration at the time of the run — not a statement of the law.

![Why this result](images/17-why-this-result.png)

**Severities, and what they mean for you:**

| Severity | Meaning | Do |
|---|---|---|
| **Critical** | A statutory breach or an unexplained money difference | Before paying |
| **Warning** | Very likely wrong, or worth a look | This cycle |
| **Info** | An observation | When convenient |

Each employee also gets a **risk level** (high, medium, low) from a score that
weighs their findings; it orders the employee list and is not a severity.

**A finding is a question, not an accusation.** The product is telling you what
it computed and what your register said. Sometimes the register is right and the
configuration is wrong — say so, and it stops asking.

### Working the issues

**Validation & findings → Issues** is where findings get worked. It lists every finding
still open across months — not just this upload — worst first: critical before
warning, the ones that keep coming back before the new ones, the expensive
before the cheap. Filter by state, severity, rule, owner, overdue or recurring,
or search by employee. The filters are kept in the page address, so a link
from the Control Centre arrives already filtered.

![Issues](images/20-issues.png)

Open a finding to:

- **Give it an owner and a due date.** Overdue findings are counted at the top
  of the page, and **Assigned to me** filters to your own.
- **Comment** — what you asked, who answered. Comments cannot be edited or
  deleted; they are the record.
- **Attach evidence** — the vendor's letter, the revised offer, the signed
  approval. PDF, PNG, JPEG, XLSX, XLS, CSV or text, up to 5 MB each. A file
  whose contents do not match its extension is refused.
- **Decide:**
  - **Mark in progress** — someone is on it.
  - **Resolve** — with a reason: what was corrected, or why it was never an
    error. If the next run finds it again, it reopens by itself.
  - **Waive** — with a reason, and **always with an end date**: 90 days if
    you give none, at most 366. When the date passes, the finding reopens and
    the history says the waiver expired. A waiver given before waivers had to
    end shows **"no end date — review"**; waive it again with a date, or reopen it.

![An issue](images/21-issue-detail.png)

**Many findings at once.** Tick them (or tick the header to select the page)
and choose **Resolve…**, **Waive…**, **Assign…** or **Mark in progress**. Each
finding gets its own entry in its history with the shared reason, exactly as
if you had done them one by one.

A finding in its first month is a mistake. The same finding in its ninth month
is a process problem — the product counts how many months each one has
survived, and **Recurring (3+ months)** shows you those.

Anyone can read the issues; changing them needs an analyst, manager or owner
role, and only people who can work this company can be given one.

### Step 4 — Bank payments

**Reconciliation & approvals → Bank payments.** Upload the payment advice you send the bank, or
the statement you get back.

![Bank payments](images/06-bank-payments.png)

The first time, someone sets up a **profile** describing your bank's layout.
After that it is just a file upload.

What it finds, among others:

- Someone **due but not paid**.
- Someone **paid but not due** — a payee on no register.
- A **different amount** than the register said.
- The **same person paid twice**.
- **Two employees sharing one account**.
- An account that is **not the one on the employee master** — occasionally a
  genuine change the employee requested, and the single most important line in
  the report. Verify it through a channel that is not email alone.

### Step 5 — Journal voucher

**Reconciliation & approvals → Journal voucher.** Builds the accounting entry from the register
using your own account codes.

![Journal voucher](images/07-journal-voucher.png)

Preview it, confirm it **balances**, then export — generic CSV, Tally, SAP or
Zoho.

### Step 6 — Month close

**Reconciliation & approvals → Month close & approval** shows the period together: bank reconciliation, JV,
and the month's **approval**. It opens on the working period shown in the
header; choosing another month here changes it everywhere. A month with no
register stored says so, rather than showing empty figures as though the
month were quiet, and a month with no bank file reads *No bank file*, not ₹0.

![Month close](images/05-month-close.png)

The approval panel shows where the month stands — *Uploaded → Validated →
Issues handled → Submitted → Signed off* — and, in plain words, anything that
stands in the way of the next step:

- **Not validated** — nothing to approve yet. Upload and validate.
- **Revalidation required** — something the run read has changed since. It
  names what; revalidate first.
- **Statutory checks could not be performed** — the month can still be
  approved, but only by stating why the gap is acceptable. That reason is kept
  in the sign-off record.

A month with no findings is **not** automatically ready: if material checks
could not run, it says so.

1. Someone with a write role **submits** the month, with optional notes.
2. An owner or manager **approves** it. If your organisation requires an
   independent approver, the person who submitted cannot approve — the panel
   says so and asks for someone else. Either way, the record states whether
   the approval was independent.
3. A signed month can be **reopened** by an owner or manager, with a reason.
   The signed record is kept, and the reopening is in the history. If anything
   changes after a month is signed, the panel says what — the signature stands
   as recorded, but no longer describes the month as it is.

**Evidence pack** downloads the workbook an auditor wants: the run and its
input fingerprints, coverage by check, every finding with its file row, the
approval trail, and the rates and schedules in force.

---

## 6. Cost analysis and reports

### Cost analysis

**Analytics & dashboards → Cost analysis.** What payroll cost, broken down by department, cost
centre, state, grade or any other dimension on the employee master, and how it
moved month to month.

![Cost analysis](images/08-cost-analysis.png)

The cost taxonomy is explicit: **CTC = earnings + employer contributions**.
Deductions sit *inside* gross and are not an additional cost to the company —
counting them again is the most common way payroll cost gets overstated.

**How the headline figures are defined** (hover the ⓘ on any figure for the same text):

| Figure | Meaning |
|---|---|
| **People paid** | Distinct employees on a regular register in the period — payroll headcount, not joining dates |
| **Average monthly headcount** | Employees on each month's register, averaged over the months that have one |
| **Cost per head / month** | Total CTC ÷ person-months. The same monthly definition for a month, a quarter or a year |

The strip above the figures says what they rest on: how many months have a
register, **which months are missing** (they are left out, not counted as ₹0),
how many months were validated or have changed since, how many are signed off,
how many people have no department recorded, and when data last arrived. An
arrears or off-cycle file is validated but never replaces the month's register,
so a month's cost is never overwritten by its arrears. In **Budget vs actual**, a
budgeted month with no register reads **no register** — not a ₹0 actual and a
false underspend — and is left out of the totals.

### Dashboards

**Analytics & dashboards → Dashboards.** Boards of your own and boards shared with the
company. **Start from a template** — payroll cost, headcount and movement,
statutory contributions, validation quality, issue resolution, budget vs actual,
department cost, month-close readiness — to get a private copy you can use as it
is or change.

![A dashboard](images/26-dashboard.png)

Each tile is a question answered when you open the board, from this company's
data only: pick the **dataset**, the **metric** (or a custom KPI), the
**breakdown**, the **chart**, any **filters**, and the tile takes the board's
**period** unless you set its own. A tile shows what it rests on under the
figure — months missing, months not validated — and **Open** (or clicking a bar
or a row) goes to the page behind it, already filtered. Every tile names its
metric, breakdown, period and units (₹, count or %), and any filters it uses; a
month or category with no data is left as a gap and labelled, never drawn as
zero. Severity and state breakdowns always wear the same colours — Critical
red, Warning amber, Info blue — with their names beside them.

**Viewing and editing are separate.** A board opens in view mode, where nothing
changes what is saved. **Edit** opens it for changes: rename it, choose who can
see it, add, edit or remove tiles, and reorder them with the arrow buttons on
each tile (they work from the keyboard). Nothing is saved until **Save**; leaving
with unsaved changes asks first, and **Discard changes** puts the board back.

**Adding a tile:** type what you want in **Find a metric** — it searches every
dataset's metrics and your custom KPIs at once — or choose the dataset and
metric step by step. The preview below the builder shows the tile with live
data for the board's period.

![Building a tile](images/27-tile-builder.png)

**Custom KPIs** are formulas over one dataset's metrics, such as
`employer_cost / gross * 100`. They are computed safely on the server; a KPI
whose input is missing, or that would divide by zero, shows "—", never 0.

**Who sees what.** A private board or KPI is yours alone. Sharing one shows it
to everyone who can open this company; that needs an analyst, manager or owner
role. The owner edits a board; an owner or manager can also edit or delete a
shared one. A shared board cannot use a private KPI. Other companies in the
group never see this company's boards.

### Reports

**Reports → Report Centre.** Select the company first, then a reporting period,
dimension and optional filters. The catalogue groups available reports by
purpose and lists required input data. Choose **Mask names** when the workbook
will be shared with someone who need not see employee identities. Download the
Excel workbook and check its **About this report** and **Data basis** sheets
before using its figures. An absent payroll month is not treated as a zero
month. Finding reconciliation shows current finding state within the selected
last-seen period; it does not reconstruct an earlier run.

The workbook is generated from current stored data. Keep the downloaded file
as evidence; generating the same report later may produce different values if
source registers or configurations have changed. The current catalogue does
not create an official statutory filing format.

**Build a report:** Open **Reports → Report Builder**. Choose the
payroll cost dataset, columns, period and filters, optional arithmetic calculation,
breakdown and sort. Preview the result and its CTC control total before saving a
personal draft. A manager can share a definition with the company. A saved
definition is evaluated against current data when opened again. Preview shows
at most 200 rows and states the full matched count. Save the definition with both
period bounds, then use **Download Excel** for all matched aggregate rows; check
the summary and data-basis sheets before sharing.

![Reports](images/09-reports.png)

### Register history

**Data & imports → Register history.** Every register uploaded, by period.

![Register history](images/13-register-history.png)

---

## 6b. Data sent by your other systems (Studio)

If your HRMS, attendance or payroll system sends data to PeopleOpsLab directly,
each batch appears in **Studio → Run history**.

![Run history](images/28-studio-runs.png)

Open a run to see what happened to every record:

![One run: counts, lineage, rejections](images/29-studio-run.png)

- **Received → accepted / rejected / skipped → created / updated / unchanged.**
  The two lines under the counts must both be green: every record received is
  accounted for, and every record accepted was stored.
- **Rejected** records were not stored. Each says which row, which field and
  why — a date that could not be read, a number that was not a number, the same
  employee twice with different values. Fix them in the sending system and send
  just those again. Nothing is ever stored as blank or zero because it could
  not be read.
- **Skipped** records were exact repeats of another row and were kept once.
- **What it led to** links to the validation results, when the batch was a
  register sent for validation.

A run started by a connection your administrator set up (**Studio →
Connections**) reads the same way, and also names the connection, the stream
and the **mapping version** that turned the other system's fields into ours.
If the same kind of rejection appears on every record, the mapping is the
likely cause — tell whoever looks after it; they can preview a fix against
the rejected rows before publishing it.

A service account can acknowledge and comment on findings, but only a person
can waive or resolve one, publish a rule, or approve a month.

**Notifications.** If your administrator has set up workflows, the bell at the
top of every page shows what they tell you — "June validated", "3 records
rejected" — with a link to the page concerned. They are yours alone. Workflows
can assign findings to you with a due date; they never waive, resolve or
approve anything.

**On Month close,** *Data from your systems* shows, for the month, how each
input arrived and whether anything was rejected or failed. Rejected records
are not in the month until they are fixed and sent again — check this before
approving.

![Data from your systems, on Month close](images/34-month-integration.png)

---

## 7. Questions people ask

**Will this change my payroll?**
No. It reads your register and reports. Nothing here writes back to your payroll
system or alters a payslip.

**There are hundreds of findings on my first run. Is that right?**
Yes, and it is expected. Most first-run findings come from configuration not yet
matching your structure. Work the CRITICALs first; the count usually collapses
once a component flag is corrected.

**A finding is wrong. The register is right.**
Then the configuration is wrong. Tell your administrator which rule and which
component. If the difference is deliberate, waive it with a reason so it stops
appearing.

**Can I see another company in the group?**
Only the ones you have been given access to. If a company you need is missing,
your administrator grants it.

**Someone from the software company can see our data?**
Only if you allow it, only for a stated reason, only for a time limit, only
read-only, with identities masked — and you will see a banner the whole time and
can revoke instantly. Your owner controls this under
**Configuration & admin → Team & invitations → Support access**, including switching it off
entirely.

**I closed the browser during validation. Is it lost?**
No. It kept running on the server. Open **Validation & findings → Validation runs**, or the upload
page, which links to any validation still in progress.

**We re-uploaded the register. Where did the first results go?**
Nowhere. Each validation is kept as a run. Open the results and pick the earlier
run from the chips at the top, or use **Compare**.

**The first page of the day is slow.**
On smaller hosting plans the server sleeps when idle and takes up to a minute to
wake. After that it is quick. The page tells you when this is what is happening.

**Nothing failed. Why can we not approve?**
Because some statutory checks could not run — most often, no decision on
whether minimum wage applies, or no employee master. The approval panel links
to exactly what is missing. Supply it and revalidate, or approve stating why
the gap is acceptable.

**Can a waiver last forever?**
No. Every waiver has an end date — 90 days by default, a year at most. When it
lapses the finding reopens, and the history says why.

**Why does a finding say "Impact not calculated"?**
Because the product did not work out a rupee figure for it — not because it
costs nothing. Open **Why this result?** to see what was compared.

**Who changed this setting?**
**Configuration & admin → Audit trail.** Append-only, and it records who did what and when.

---

## 8. Getting help

Before raising a ticket, have ready: the **company**, the **period**, the **rule
ID**, and the **employee ID**. Those four make almost any question answerable
without anyone needing to look at your salary data.
