# PayrollCheck — India payroll validation & business intelligence

Not an HRMS, and it does not run payroll — which is exactly what qualifies it to
check one. It sits beside whatever system does and answers three questions about
the output: **is this month right**, **what is it costing us**, and **did it
reach the bank and the ledger**.

- **Checks attendance** against itself before it is stored, and then checks pay
  against attendance — loss of pay never deducted, overtime worked and never
  paid, an employee on the attendance register and on no payslip.
- **Validates** PF, ESIC, PT, LWF, income tax, minimum wage and structure — and
  checks the register against the employee master and attendance, which is what
  catches a wrong input that was processed consistently.
- **Reconciles** the bank payment file against net pay due, and builds the
  month's journal voucher from your own chart of accounts, checking it balances
  and equals the payroll cost the dashboard reports.
- **Explains** month-on-month cost movement, and sizes accumulated statutory
  exposure with interest and damages by age.
- **Records** findings across months with a waiver trail, and freezes a signed
  evidence pack per period.

Data is scoped to an **entity** (one legal employer). A payroll bureau runs many
under one login; an enterprise is simply an organization with one. See
`USER_MANUAL.md`.

Monorepo: **backend** is FastAPI + SQLAlchemy; **frontend** is Next.js 14 (App Router).


## Documentation

| Document | For | Covers |
|---|---|---|
| [`docs/IMPLEMENTATION_MANUAL.md`](docs/IMPLEMENTATION_MANUAL.md) | Whoever onboards a client | What to collect, the order configuration has to happen in, parallel run, acceptance |
| [`docs/ADMIN_MANUAL.md`](docs/ADMIN_MANUAL.md) | Platform and organization administrators | Login types, roles and rights, creating client accounts, invitations, break-glass support |
| [`docs/CLIENT_USER_MANUAL.md`](docs/CLIENT_USER_MANUAL.md) | Payroll, HR and finance staff at a client | The monthly routine, screen by screen |
| [`docs/BRD.md`](docs/BRD.md) | Stakeholders, clients | Scope, requirements, roles, acceptance criteria, known gaps |
| [`USER_MANUAL.md`](USER_MANUAL.md) | Operators wanting depth | Every module, full rule reference, API table, troubleshooting |
| [`docs/GO_LIVE.md`](docs/GO_LIVE.md) | Whoever ships it | Sequenced test plan and production cutover |
| [`DEPLOYMENT.md`](DEPLOYMENT.md) | Operators | Hosting, environment variables, DNS, rollback |

The three manuals are illustrated with screenshots of the running product, in
[`docs/images/`](docs/images). They are captured from a seeded demo group rather
than drawn, so they show the real interface — regenerate them with
`backend/e2e_deployed.py`-style seeding plus Playwright when the UI changes.

## Production layout (peopleopslab.in)

| Role | URL | Hosts |
|------|-----|--------|
| **Web app (Next.js)** | `https://peopleopslab.in` and `https://www.peopleopslab.in` | Vercel, Render Web, etc. |
| **API (FastAPI)** | `https://api.peopleopslab.in` | Render, Fly.io, VM + reverse proxy, etc. |

### Default: same-origin API proxy (recommended on Vercel)

On **`peopleopslab.in`** / **`www.peopleopslab.in`**, the SPA **automatically** calls **`/api/proxy/api/…`** (same host as the website). A **Route Handler** in Next forwards those requests server-side to your real API. That avoids **CORS**, **mixed content**, and several **browser “Failed to fetch”** scenarios.

You must set **`BACKEND_URL`** on the **Next.js** host:

| Variable | Where | Example |
|---------|-------|---------|
| **`BACKEND_URL`** | Server-only env on Vercel (Production) — **do not** use `NEXT_PUBLIC_` prefix | `https://api.peopleopslab.in` |

No trailing slash. Redeploy after adding it.

Smoke tests:

1. `https://YOUR_VERCEL_SITE/api/proxy/api/health` → should return backend JSON wrapped as usual (`success: true`).
2. `https://peopleopslab.in/api/proxy/api/health` after DNS is correct.

Optional overrides:

- **`NEXT_PUBLIC_USE_API_RELAY=1`**: force proxy mode on **any** hostname (still needs **`BACKEND_URL`**).
- **`NEXT_PUBLIC_DIRECT_API=1`**: disable proxy even on **peopleopslab.in** — browser calls **`NEXT_PUBLIC_API_URL`** directly (CORS must allow the web origin).

### Direct browser → API (no proxy)

Set **`NEXT_PUBLIC_API_URL=https://api.peopleopslab.in`** on the frontend build **and** use **`NEXT_PUBLIC_DIRECT_API=1`** so proxied routing is explicitly off — or preview on a hostname that isn’t **peopleopslab.in** without `NEXT_PUBLIC_USE_API_RELAY`.

**API** **`CORS_ORIGINS`** must still list your web origins if the browser hits the API directly.

### Troubleshooting “Failed to fetch” from the dashboard

| Check | Action |
|--------|--------|
| Proxy without `BACKEND_URL` | Vercel returns **502** with a JSON message — set **`BACKEND_URL`** and redeploy. |
| Upstream unreachable from Vercel | **502** with `upstream_unreachable` — DNS/TLS/firewall from Vercel to `api.*`. |
| You want legacy direct calls | **`NEXT_PUBLIC_DIRECT_API=1`** + **`NEXT_PUBLIC_API_URL`**, fix backend CORS. |

## Local development

### Backend (`backend/`)

```bash
cd backend
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -r requirements.txt
copy .env.example .env    # edit secrets as needed for local-only
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Health check: `GET http://127.0.0.1:8000/api/health`

### Frontend (`frontend/`)

```bash
cd frontend
npm install
copy .env.example .env.local
npm run dev
```

For normal local work: **`NEXT_PUBLIC_API_URL=http://localhost:8000`**. Hostname is **localhost**, so **proxy stays off**.

To exercise the proxy locally:

- `.env.local`: **`NEXT_PUBLIC_USE_API_RELAY=1`** and **`BACKEND_URL=http://127.0.0.1:8000`** (both read by Next; `BACKEND_URL` is server-only).

## Deploying on GitHub

CI runs via `.github/workflows/ci.yml`.

## Production environment variables (summary)

**API (`api.peopleopslab.in`)**

| Variable | Value |
|----------|--------|
| `JWT_SECRET` | Strong random secret |
| `DATABASE_URL` | Postgres (recommended for production) |
| `CORS_ORIGINS` | Include `https://peopleopslab.in`, `https://www.peopleopslab.in` (required if browsers call the API **directly**; optional if everyone uses **`/api/proxy`**) |
| `ALLOW_ANONYMOUS_API` | `false` |

**Frontend (peopleopslab.in on Vercel)**

| Variable | Value |
|----------|--------|
| **`BACKEND_URL`** | **`https://api.peopleopslab.in`** (server-side for `/api/proxy`) |
| `NEXT_PUBLIC_API_URL` | Optional; used when **`NEXT_PUBLIC_DIRECT_API=1`** or outside **peopleopslab.in** inference |

## DNS

- **peopleopslab.in** → Next.js
- **www** → Next.js
- **api** → FastAPI

## Security reminders

- Never commit `.env` / `.env.local`.
- The proxy only forwards paths starting with **`/api/`** (enforced server-side).
