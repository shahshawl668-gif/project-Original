# 01 — ISMS scope and context

> **TEMPLATE — NOT APPROVED.** Drafted from the codebase on 30 September 2026. It is not a policy until the named approver signs it, and it is not evidence of an operating ISMS until the records it names exist. Text in _italics_ is for the business to decide.

## Proposed scope (clause 4.3)

The design, development, operation and support of the PeopleOpsLab payroll
validation service (web application, API, integration API and PeopleOps
Studio), including the source repository, CI, and the hosting accounts that
run it; the people who build and operate it.

_Excluded (with justification):_ _the business's general office IT, if separate._

## Interested parties (4.2)

| Party | Requirement relevant to information security |
|---|---|
| Client organisations | Confidentiality of payroll data; contractual security terms; breach notice |
| Their employees (data principals) | Protection of personal data they did not choose to share with this vendor |
| Regulators | DPDP Act 2023 / Rules 2025; CERT-In directions 2022 — _legal review required_ |
| Suppliers (Render, GitHub) | Their terms; shared-responsibility boundaries |

## Internal and external issues (4.1)

- Single-founder / small-team operation: key-person risk for access and recovery.
- Hosting on free tiers at the time of writing (see `../../SECURITY.md` §7).
- **Climate change (Amendment 1:2024).** The organisation must determine whether
  climate change is a relevant issue. _Decision and reasoning to be recorded
  here._ A likely answer for a cloud-hosted service: relevant only through the
  hosting provider's resilience, handled under 07 and 08.
