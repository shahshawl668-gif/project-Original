# PeopleOps Studio: client integration architecture and current status

## What is implemented

- One shared versioned integration API host; service accounts belong to one organization and name allowed legal companies.
- Each request authenticates a hashed key and resolves a company from the allowed list. Multi-company keys require `X-Company-Id`; unknown or unauthorized companies return 404.
- Company-scoped connections, mappings, workflows, run history, release records, and a developer workspace for formulas, conditions and lookups.
- REST/file connectors, inbound/outbound webhooks, retries, validation handoff, and mapping version publication are present. Review each connector against a real provider before declaring it production-ready.
- The development/test/production service-account environment must match each named company. It is checked again per integration request. These companies still share infrastructure and a database; the environment is **not** a separate deployment.
- Customer-supplied Python is **not executable** in the shared API process. The Developer workspace runs a restricted expression evaluator for test samples.

## Client and group company model

`Organization` is the account boundary; `Entity` is a legal payroll company. An enterprise can have group companies; a payroll practice can have clients in one organization, with memberships and entity access determining which users see each company. This is a shared application/deployment cell and database with application-level scoped rows. A different URL is an optional discovery and branding feature, not a security boundary. A practice's unrelated clients should ultimately be distinct tenant organizations, with explicitly granted cross-tenant operator access; putting all clients under one organization grants broad default membership and complicates isolation. Do not onboard external clients under one practice organization until that access model is finished and reviewed.

A service account should normally name one company and one source system. Independent clients get separate keys, connections, mappings and workflow releases. For group-company integrations, explicitly grant each company and send `X-Company-Id` on every call. The request's authenticated principal and database authorization determine access, not a URL, user-supplied tenant ID, or environment label.

## What needs to be built next

1. **Tenant provisioning and domains:** Product admin creates a tenant organization, slug, enabled products and initial owner invitation. Associate an approved host with the organization, enforce host-to-token/tenant agreement at login and API gateway, and issue tenant-specific URLs such as `client.peopleopslab.in`. Keep the shared API for integrations unless dedicated routing is contracted. Add a migration path for any practice clients currently mixed into one organization.
2. **Onboarding wizard:** Select company and source; connect/test credentials; sample source data; map fields and salary components; preview rejected rows and control totals; publish with approval; run a synthetic or masked rehearsal; activate a schedule. Surface each stage's permission, error and next action.
3. **Dedicated test environment:** The key-to-company environment check is now enforced. Separate databases and secrets remain necessary before claiming infrastructure-level separation; use synthetic data in non-production companies.
4. **Custom Python service:** Versioned draft with company scope, declared input/output schema and dependencies. Submit for independent approval, test against synthetic data, then execute only in isolated short-lived compute outside the API and report workers. The runner gets only a scoped input batch and short-lived output token. No payroll database credential or platform secret is present; deny outbound networking by default. Enforce CPU, memory, wall-time, input/output limits and dependency allowlist; log checksums, version, actor, outcome, counts and redacted errors. A killed run fails closed. Do not treat `eval`, restricted builtins, a thread, or a normal subprocess on the API host as a sandbox. Provision and review the runner before adding a Run/Publish button.
5. **Operational tests:** Exercise two unrelated organizations and group companies with disjoint data; key creation/rotation/revocation after role changes; URL/host mismatches; webhook and scheduled-run tenant scope; connector timeouts, retries and duplicates; mapping changes and rollback. Benchmark large imports without blocking payroll validation.

## Release scope of this branch

This branch improves the Studio overview and API Centre, explains selected-company scope and the shared API address, adds direct setup actions, clarifies that environment labels are not isolated instances, guides users through existing customization tools, and prevents a manager of one company from revoking a key shared with a company they no longer manage. It does not enable arbitrary Python or provision tenant domains.
