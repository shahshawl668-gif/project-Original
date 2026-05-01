# Payroll SaaS (India validation UI + API)

Monorepo: **backend** is FastAPI + SQLAlchemy; **frontend** is Next.js 14 (App Router).

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
