"""
Disbursement validation: is this salary payment file safe to release?

The register check asks whether payroll was calculated correctly. This asks a
different question, of a different file: the bank payment file the HRMS
produced. It never pays anyone and never sends a file anywhere. It reads the
file, decides which rows are safe, writes a clean copy without the rest, and
leaves the release to a person.

Four outcomes per check, chosen per company:

* **STOP_FILE** — the file as a whole must not go: nothing is released.
* **HOLD_ROW** — that employee comes out of the file; everyone else is paid.
* **FLAG** — the employee is paid; the approver sees the finding.
* **NOT_RUN** — an input the check needs was not supplied, named in the reason.
  A check that could not run is never reported as passed.

The engine (``engine.run``) works on plain data and touches no database, so it
can be tested on its own and run on 10,000 employees in well under a second.
"""
