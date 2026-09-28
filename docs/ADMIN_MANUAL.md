# Peopleopslab — Administrator Manual

Running the product: who can sign in, what each of them can do, how a client
account gets created, and how support access works.

Two different jobs are described here, and it matters which one you are doing:

- **Platform administrator** — you run Peopleopslab itself. You can see
  organizations exist. You cannot read their payroll.
- **Organization owner** — you run one client's account. You can see everything
  inside it and decide who else can.

---

## 1. The first account

Production has **no public signup**. `/api/auth/signup` answers 404, whatever
`ALLOW_PUBLIC_SIGNUP` says, and every account after the first arrives by
invitation. That leaves one question: how the first platform owner gets in.

**An installation upgraded from before platform roles** already has one: a
one-time migration names the legacy `role = "admin"` account as platform owner.
Nothing to do.

**A fresh database** — a new installation, a restore into an empty instance, or
the free-tier database being replaced when it expires — has nobody. From a
shell on a machine that can reach the database (on Render, the API service's
**Shell** tab):

```bash
cd backend
python -m app.bootstrap_owner you@yourdomain.in --site https://www.peopleopslab.in
```

It prints a one-time link to `/platform/join`. Open it within **24 hours** and
set your password. Deliberately narrow:

- **It only ever creates the first.** It refuses (exit code 2) once any platform
  owner or admin exists, so it cannot add a second owner or take over a
  platform someone else runs. Further staff are invited from the console (§2).
- **It never handles a password.** You set yours in the browser, so nothing
  secret lands in shell history or a deploy log.
- **It will not promote an existing account.** A client's login is never
  quietly turned into platform access; the first owner is always a new account.
- The link is the only copy of the token — only its hash is stored.

> Run it before you tell anyone the site exists, and open the link yourself.
> Until it is accepted, the link is the key to the whole platform.

---

## 2. The three kinds of login

Platform staff and client users are **separate populations with separate
sign-in pages.** A client account cannot sign in to the platform, a platform
account cannot sign in to a client workspace, and client credentials only work
at their own workspace's address.

| Who | Signs in at | Gets there by |
|---|---|---|
| Platform staff (owner, admin, support) | `/platform/login` | Invitation from a platform owner, accepted at `/platform/join` |
| A client's people | `/w/<workspace>/login` — e.g. `/w/acme-industries/login` | Invitation from the platform (the first owner) or from their own organization |
| Platform staff helping a client | Support session opened from the console | A time-boxed grant, §6 |

The same email and password at another workspace's address is refused with the
same message as a wrong password, so the sign-in page never confirms which
workspaces exist.

![Sign in](images/00-login.png)

### Platform roles

| Role | Can do |
|---|---|
| **Owner** | Everything below, plus invite and remove platform staff |
| **Admin** | Create client workspaces, see which organizations exist, open support sessions |
| **Support** | Open support sessions only |

**No platform role gives access to client payroll.** Entity access is decided by
organization membership, which never consults the platform role. A standing
developer login over every client's salary, PAN and bank data would be the most
attractive single target in the system, so it does not exist.

To see a client's data you open a support session (§6).

### Organization roles

Set per member, inside one organization:

| Role | Can do | Cannot do |
|---|---|---|
| **Owner** | Everything, including inviting owners, removing members, setting the support policy | — |
| **Manager** | Configuration, uploads, validation, sign-off, invite analyst/viewer | Change owners, set support policy |
| **Analyst** | Upload, validate, work findings, reconcile | Change configuration, manage people |
| **Viewer** | Read and export | Change anything |

Two rules hold regardless of role:

- **You cannot change your own role, or remove yourself.** Both directions are
  how an organization ends up with nobody who can administer it.
- **You can only invite at your own level or below.** An analyst cannot mint an
  owner.

### Entity access

Independently of role, a member can be narrowed to specific entities. Leave it
empty and they see every entity in the organization. This is how a practice
gives an analyst three client companies out of thirty.

---

## 3. Creating a client account

Two shapes, and the right one depends on who owns the data.

### A. The client owns their account (recommended)

1. In the platform console (`/platform`), **Create client workspace** with the
   company name and the owner's email. You get back the workspace's sign-in
   address (`/w/<workspace>/login`) and a one-time invitation link
   (`/invite?token=…`), shown once.
2. Send the owner both. They open the invitation, set their password, and from
   then on sign in at their workspace's address.
3. They add their remaining entities.
4. They invite their own people.
5. If they want your help, they set their support policy to allow it (§6).

Cleanest arrangement: the client's data belongs to the client's account, you
hold no standing access, and your entry is time-boxed and visible to them.

### B. You run it for them (a practice)

1. Your organization is set to `org_type = "practice"`.
2. You create **one entity per client company**.
3. You invite your own staff, narrowed by entity access to the clients they
   work on.
4. Client staff, if they need access, are invited as **viewer** and narrowed to
   their own entity.

Here the data lives in your organization. Be deliberate about that — it is a
commercial and contractual decision, not a technical one.

---

## 4. Inviting people

**Settings → Team & invitations.**

![Team and invitations](images/11-team.png)

1. Enter the email.
2. Choose a role — your own level or below.
3. Choose entities, or leave empty for all of them.
4. **Create invitation.**

What you get back is a link, **shown once**. Only its SHA-256 fingerprint is
stored, so it cannot be recovered afterwards — resend to issue a fresh one.

Invitations expire after **7 days**. The email on the invitation must match the
email used to accept it; an invitation is not a general-purpose key.

> An unaccepted invitation is an outstanding key to this organization's payroll.
> Revoke any that are no longer needed rather than letting them expire quietly.

### Changing and removing

- **Change a role** — Members list. You cannot act on someone above your own
  level, or on yourself.
- **Remove a member** — revokes access immediately. Their audit history stays;
  removing someone must not erase what they did.
- The **last owner** cannot be demoted or removed.

---

## 5. Users & roles (platform)

**Settings → Users & roles**, platform administrators only.

Lists accounts in **your own organization**, plus any organization you currently
hold a live support grant on. It does not list every user on the installation —
a staff list is who a company employs, and enumerating one needs a grant, the
same as any other client data. Reads under a grant are written to that client's
audit trail as `support.read`.

You can promote and demote **within your own organization only**. A support
grant is read-only, so holding one does not put a client's accounts within reach
of promotion.

The last platform administrator cannot demote themselves.

---

## 6. Break-glass support access

The documented way for platform staff to read a client's data when the client
reports something that cannot be reproduced otherwise.

### What it guarantees

| Property | How |
|---|---|
| **Never implicit** | No grant, no access. Being platform staff is not access. |
| **Time-boxed** | Expiry stored on the grant; default 60 minutes, maximum 480. Expiry is derived, so a lapsed session stops working the moment it lapses. |
| **Reason-required** | Minimum 12 characters, stored, shown to the client. |
| **Read-only, always** | Recorded per grant, not decided at read time. |
| **Identities masked** | As they are for a viewer. Bugs live in configuration and totals, which masking leaves legible. |
| **Visible to the client** | Every open, use and close writes to *their* audit trail, not a staff log they cannot see. |
| **Revocable** | Instantly, by any owner there. |

### Opening one

**Settings → Support access** (platform side):

1. Choose the organization.
2. Write a real reason — "Investigating ticket 412, cost dashboard shows no
   June data". It is written to the client's audit trail.
3. Set a duration no longer than you need.
4. Open.

Under a `break_glass` policy it is active immediately. Under
`approval_required` it is `pending` until an owner there approves.

### What the client controls

On their own **Team & invitations** page, an owner sets the policy:

- **Allow, and tell us** (`break_glass`) — a session opens immediately; they see
  it at once and can revoke it. The default.
- **Ask us first** (`approval_required`) — nothing opens until an owner approves.
- **Never** (`disabled`) — no session can be opened. Switching to this **closes
  any session already open**; a policy that only applied to future sessions
  would not be the switch it appears to be.

While a session is live, a banner appears for **every member** of that
organization — not just owners — and it cannot be dismissed. Whoever the payroll
belongs to should be told, not only whoever can change the setting.

---

## 7. The audit trail

**Settings → Audit trail.** Append-only. Records configuration changes, uploads,
validation runs, finding decisions, sign-offs, invitations, member changes, and
every support session and use.

![Audit trail](images/12-audit.png)

Audit rows are written in the same transaction as the thing they describe. A
trail that can survive a rolled-back change records events that never happened.

---

## 8. Routine administration

### Monthly

- Review open invitations; revoke stale ones.
- Review members against who still works there.
- Check the audit trail for support sessions you did not expect.
- Confirm sign-off completed for the closed period.

### Each financial year

- Re-verify every statutory rate against current notifications (§9).
- Review PT and LWF slabs per state.
- Review rule suppressions — a suppression made once should not become
  invisible forever. Waivers expire by default for the same reason.

### On a change of staff

- Remove the leaver's membership **before** their last day.
- Reassign entity access rather than sharing a login. There is no scenario in
  which two people sharing an account is the right answer in a system whose
  output is evidence.

### The validation queue

Validations run as background jobs inside the API service, drained by worker
threads that start with it.

| Setting | Default | Meaning |
|---|---|---|
| `VALIDATION_WORKER_ENABLED` | `true` | Start worker threads in the API process. Turn off **only** if a separate `python -m app.worker` process runs instead — otherwise every validation waits forever. |
| `VALIDATION_WORKER_CONCURRENCY` | `1` | Threads per process. Each holds one validation in memory; see the measured figures in `docs/BACKGROUND_JOBS.md` §15 before raising it on a small instance. |

**A job whose worker died** (a deploy, the instance sleeping, out of memory) is
reclaimed automatically once its lease is two minutes stale, and retried up to
three attempts. Nothing to do.

**A job that failed** shows its reason on the client's progress page, written
for them (missing columns, no components configured). The raw error is kept in
`validation_jobs.error` for you; the client never sees it. A retry is a new job
and is always safe — a failed attempt writes nothing.

**A job stuck in `queued`** means no worker is running. Check the API boot log
line `validation_workers=N`; `0` means the setting is off.

### Run history and storage

Validation runs are **never deleted**: re-validating a month supersedes the
previous run and keeps it. Uploads are kept too, with the rows as parsed,
compressed. Budget the database for it — measured sizes per 1,000 employees are
in `docs/BACKGROUND_JOBS.md` §15. There is no purge; removing evidence is a
decision for the client, not a housekeeping task.

### Upgrading to the run-history release (October 2026)

- **Automatic on first start.** `preserve_run_history` in `app/migrations.py`
  adds columns to `validation_runs` and `validation_jobs`, creates
  `register_uploads` and `validation_run_employees`, and adds a unique index
  allowing one `current` run per period. It is idempotent and additive.
- **Existing runs** become run 1, `current` — true of every one, because the old
  code deleted the previous run on each re-validation. They carry no input
  digests, so they are reported as *"predates input tracking"* rather than as
  current; revalidating the month gives them a successor with full evidence.
- **Rollback:** redeploy the previous release. Every new column is nullable or
  defaulted and the old code does not read them, so it runs unchanged. Runs made
  by the new release stay in the table (the old code would show only the latest
  per month, as before). The one thing the old code does that the new one
  undoes is *delete* superseded runs on the next re-validation — so roll back
  only if you must.

---

## 9. What an administrator must not delegate

**Statutory rates must be verified by a payroll professional before real client
data is processed**, and re-verified every financial year. The shipped defaults
are FY-versioned and correct to the best of the build's knowledge, but Indian
payroll law changes by state, by notification and by year.

A validation engine that is confidently wrong is worse than none, because people
stop checking. See [`GO_LIVE.md`](GO_LIVE.md) §D6.
