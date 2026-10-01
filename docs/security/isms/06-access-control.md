# 06 — Access control

> **TEMPLATE — NOT APPROVED.** Drafted from the codebase on 30 September 2026. It is not a policy until the named approver signs it, and it is not evidence of an operating ISMS until the records it names exist. Text in _italics_ is for the business to decide.

**Enforced in code** (`../CONTROL_REGISTER.md` §A–B): tenant isolation;
client roles owner / manager / analyst / viewer; masking; platform roles
owner / admin / support with no payroll access; break-glass support grants;
throttled sign-in; two-step sign-in with organisation- and platform-level
enforcement; session revocation.

**Organisational rules to approve:**
1. Platform staff are invited, never promoted from client accounts; every
   member of staff uses two-step sign-in (`REQUIRE_MFA_FOR_PLATFORM_STAFF=true`
   _once all are enrolled_).
2. Access to Render, GitHub and GoDaddy (the domain and its DNS) is personal (no
   shared logins), protected by two-step sign-in, and listed here with its
   owner: _list_.
3. _Quarterly_ access review of platform staff, hosting accounts and
   repository collaborators; record who reviewed and what changed.
4. A leaver's access is removed the same day: platform role, sessions
   (`POST /api/admin/staff/{id}/revoke-sessions`), hosting and repository.
5. A lost second factor is reset only after identity is confirmed by a
   channel other than the request's (`python -m app.auth_recovery reset-mfa`).
