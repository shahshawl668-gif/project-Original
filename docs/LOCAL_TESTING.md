# Testing the whole product on your own machine

Everything runs locally in Docker — the database, the API with its validation and
report workers, and the web app — so a full financial year can be checked before
anything is hosted. Nothing leaves your machine.

## 1. Start it

You need Docker Desktop (or Docker Engine with Compose) running.

```bash
docker compose -f docker/docker-compose.yml up --build
```

The first build takes a few minutes. It is ready when the log shows `API ready`
and the web app has started. Then:

* Web app: http://localhost:3000
* API health: http://localhost:8000/api/health

The database lives in a Docker volume, so it survives a restart. To start again
from an empty database:

```bash
docker compose -f docker/docker-compose.yml down -v
```

A `.env` file in the repository root is optional; without one the local defaults in
`docker/docker-compose.yml` are used. Those defaults are for your machine only — do
not expose these ports to a network.

## 2. Load the full-year test company

The test company is in `testdata/payroll-fy2026-27`: 24 people in Karnataka and
Maharashtra, April 2026 to March 2027, with increments, arrears, a mid-month
promotion, a back-dated promotion, a joiner, a leaver, a transfer, a salary on hold,
LOP and its reversal, overtime, the PF ceiling rising to Rs 25,000 on 17 September
2026, the ESIC contribution period turning in October, a minimum-wage VDA revision,
Maharashtra LWF and February PT — and one or two planted mistakes each month. Its
README lists, month by month, exactly what the tool must report.

With the stack running, from the repository root (Python 3 with `requests`
installed — `pip install requests`):

**Either load the whole year automatically**, then look at it in the browser:

```bash
python backend/tools/load_full_year.py
```

It loads each month the way a payroll team would — master and CTC when they change,
attendance, the salary register — queues the validation, waits for it, and prints
each month's result against the answer key. It ends with the sign-in link, the email
and a password for the account it created.

**Or do the months yourself in the screens**:

```bash
python backend/tools/load_full_year.py --setup-only
```

creates the account and loads the company's configuration only. Sign in with the
link it prints, then for each month open `testdata/payroll-fy2026-27/months/<YYYY-MM>/`
and load, in order: the employee master (if the folder has one), the CTC (if it has
one), the attendance, and the salary register from the Control Centre's *Check a
register*. Compare each month's results with the table in the pack's README.

Sign-in for a company is at `http://localhost:3000/w/<company-slug>/login` (the loader
prints yours). `http://localhost:3000/login` is for platform staff.

## 3. What to check

* **Every planted mistake is reported** for its month, and nobody else has a warning
  or critical finding. Information notes are expected: a Maharashtra employee with no
  minimum-wage rate loaded, the September PF shortfall to recover, a new joiner.
* **History** (Validation → History) lists twelve finished runs; each opens its results.
* **The Control Centre** shows each month checked, the headcount roll-forward (last
  month + joiners − exits), and what is still open before approval.
* **Exports**: the Excel results and the parallel-run pack from a month's results; the
  Report Centre workbooks for any month.
* **Approval**: work a month's findings (fix, waive with a reason), submit and sign off.

## 4. The automated checks behind it

From `backend/`:

```bash
python -m pytest tests -q                       # everything, about eight minutes
python -m pytest tests/test_full_year.py -q     # the year, month by month
python -m pytest tests/test_isolation_sweep.py  # no company can reach another's data
```

The year test loads the same pack and fails if any planted mistake is missed, if a
correct payslip gets a warning, if an attendance file does not reconcile, or if a
register column is reported as ignored. The isolation sweep creates one of nearly
everything the product stores in one company and replays every identifier against
every route from another company; any success is a leak.

To run the suite on PostgreSQL as production does, give it a database of its own —
the tests create their own companies, which you do not want mixed into the one you
are testing by hand:

```bash
docker compose -f docker/docker-compose.yml exec db createdb -U payroll payroll_test
DATABASE_URL=postgresql+psycopg2://payroll:payroll-local-only@localhost:5432/payroll_test python -m pytest tests -q
```

## 5. If something goes wrong

* **Port already in use**: set `BACKEND_PORT`, `FRONTEND_PORT` or `POSTGRES_PORT` in `.env`.
* **The web app cannot reach the API**: it is built to call `http://localhost:8000`; if
  you changed `BACKEND_PORT`, also set `NEXT_PUBLIC_API_URL` and rebuild.
* **A loader run stops on an existing account**: pass `--email` with a new address, or
  `--password` with the one it printed before.
