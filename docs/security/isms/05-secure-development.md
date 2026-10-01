# 05 — Secure development

> **TEMPLATE — NOT APPROVED.** Drafted from the codebase on 30 September 2026. It is not a policy until the named approver signs it, and it is not evidence of an operating ISMS until the records it names exist. Text in _italics_ is for the business to decide.

**Already operating (verifiable in CI on every pull request):** ruff; bandit;
the test suite on SQLite and PostgreSQL; the handbook check; secret scan of the
whole history; dependency audit against assessed exceptions; SBOMs.

**Rules to approve:**
1. Every change reaches `main` through a pull request with passing checks
   and _one reviewer other than the author_ (_enable branch protection — not
   verifiable from the repository_).
2. A security fix lands with a test that fails without it.
3. No real personal data in development, tests, demos or screenshots —
   synthetic data only (`backend/tools/synthetic_payroll.py`).
4. A dependency advisory is assessed within _14 days_: upgrade, or an entry in
   `security/dependency-exceptions.json` with a reason and a review date.
5. No credential in code, documents, URLs, logs or samples. A leaked one is
   rotated (`../INCIDENT_RUNBOOK.md` 2d), never just deleted.
6. Statutory rates are configuration and are signed off (`docs/GO_LIVE.md` D6).
