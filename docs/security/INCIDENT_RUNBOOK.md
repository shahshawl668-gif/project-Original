# Incident runbook

> **Status: DRAFT PROCEDURE — not approved, not yet exercised.** The commands
> and endpoints in it exist and are tested; the roles, contacts and deadlines
> must be confirmed by the business and by legal counsel before it is relied
> on. Exercise it (a tabletop is enough to start) and record the exercise.

## 0. Contacts — to be filled in by the business

| Role | Person | Reachable by |
|---|---|---|
| Incident lead | _name_ | _phone_ |
| Platform owner (Render, GitHub, DNS) | _name_ | _phone_ |
| Legal / privacy counsel | _name_ | _phone_ |
| Client contact per organisation | _in the client contract_ | |

## 1. First hour — every incident

1. **Open a record** (date, who noticed, what was seen). Keep times in IST and UTC.
   Everything below is written into it as it happens.
2. **Preserve evidence before changing anything.** Export the relevant slice:
   - `GET /api/admin/security/events?kind=…&outcome=…` (platform owner/admin)
   - the client's audit trail (`/audit` in the product, or `audit_events` by `org_id`)
   - Render logs for the window (Render retains them only briefly on the free plan — export now)
   The audit and security tables refuse edits, but a database restore would still replace them.
3. **Decide the clock.** If personal data may be affected, legal counsel decides
   today whether and when to notify: the client (who is likely the Data
   Fiduciary under the DPDP Act and has its own 72-hour Board deadline under
   Rule 7 once in force), CERT-In (6 hours for specified incidents under the
   2022 directions), and anyone a contract names. **This runbook does not make
   that decision.** Record who made it and when.

## 2. Playbooks

### 2a. A person's account is compromised (or their laptop is lost)

```bash
cd backend
python -m app.auth_recovery end-sessions person@client.in --reason "INC-… laptop lost"
```
Every session ends at its next request (≤ 30 minutes for an access token
already issued; refresh is refused at once). Then: they reset their password;
if two-step sign-in was on and the phone is gone, `reset-mfa` **only after
confirming identity by a channel other than the one the request came on** (a
call to a number already on file, not one given in the request). Review what
the account did: its audit trail and its `security_events`.

A member of platform staff: `POST /api/admin/staff/{user_id}/revoke-sessions`
does the same from the console (platform owner).

### 2b. Many failed sign-ins / credential stuffing

`GET /api/admin/security/events?kind=login&outcome=failure` and `…outcome=blocked`.
Locks are automatic. If the pattern is broad (many addresses), the app cannot
see source IPs reliably behind the relay: put an edge rate limit in front
(SECURITY.md R10). Lift a genuine user's lock with
`python -m app.auth_recovery unlock person@client.in`.

### 2c. `refresh / detected` — a refresh token was replayed

The product has already ended every session of that user. Treat as 2a: the
token was copied from their browser or device.

### 2d. A secret is exposed (repository, log, screenshot, chat)

Do not delete it and hope. Rotate it, in this order, keeping the service up:

| Secret | Rotation | Effect |
|---|---|---|
| `JWT_SECRET` | Set a new value in Render, redeploy | Everyone is signed out; no data lost |
| `STUDIO_SECRET_KEY` | Prepend a new key (`new,old`), redeploy, run `python -m app.rotate_secrets --apply`, then set `new` alone and redeploy | Nothing breaks during rotation. Dropping the old key before re-encryption makes connection secrets and **two-step secrets** unreadable |
| `DATABASE_URL` password | Rotate in Render's database settings, update the API's variable, redeploy | Brief interruption |
| Integration key | Revoke in Studio → API, issue a new one to the client | That integration stops until updated |
| A user's password | They reset it; sessions end | — |

A value that reached git history stays there. Rotation, not rewriting history, is the fix.

### 2e. Suspected cross-company exposure

Stop and preserve (step 1). Identify the route and the objects from the audit
trail and request logs. Reproduce against a local copy with synthetic data,
never against production. Add the case to `tests/test_isolation_sweep.py`
before fixing. Notification per step 3 — this is the incident most likely to
need it.

### 2f. Data loss or corruption

Stop writes (Render: suspend the API service). Restore to a **new** database
from the most recent good backup and run
`backend/tools/restore_drill.py`-style checks against it before pointing the
API at it. Today production has no backups (SECURITY.md R1): this playbook
cannot work until that is fixed.

## 3. Close

Record the cause, what was changed, which tests now cover it, who was told and
when. Review the runbook itself. File the record with the ISMS records
(`isms/03-risk-method.md` names where).
