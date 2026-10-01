# 02 — Information security policy

> **TEMPLATE — NOT APPROVED.** Drafted from the codebase on 30 September 2026. It is not a policy until the named approver signs it, and it is not evidence of an operating ISMS until the records it names exist. Text in _italics_ is for the business to decide.

**Approver:** _name, role_ · **Approved on:** _date_ · **Review:** annually and after any significant incident.

1. **Purpose.** Protect the confidentiality, integrity and availability of client
   payroll data and of the service that checks it. The product never runs
   payroll; it must never alter a payslip or pay anyone.
2. **Commitments.** Meet applicable legal, regulatory and contractual
   requirements; set and review objectives (below); continually improve the ISMS.
3. **Principles that the code already enforces** — tenant isolation (404 to a
   stranger); platform staff have no access to client payroll except through
   time-boxed, read-only, recorded support grants; silence is never a pass;
   statutory rates are configuration.
4. **Everyone** with access uses two-step sign-in, never shares an account,
   never puts a credential in a repository, document, chat or ticket, and
   reports a suspected incident at once (`../INCIDENT_RUNBOOK.md`).
5. **Objectives for the first year** _(to confirm)_: zero cross-tenant
   exposures; 100% of staff on two-step sign-in; a restore drill against
   production backups every quarter; dependency advisories assessed within 14 days;
   an independent test before the first real client's data.
