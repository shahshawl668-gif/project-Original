# Payroll SaaS (India validation UI + API)

Monorepo: **backend** is FastAPI + SQLAlchemy; **frontend** is Next.js 14 (App Router).

## Production layout (peopleopslab.in)

This project is set up for a **split origin** in production:

| Role | URL | Hosts |
|------|-----|--------|
| **Web app (Next.js)** | `https://peopleopslab.in` and `https://www.peopleopslab.in` | Vercel, Render Web, etc. |
| **API (FastAPI)** | `https://api.peopleopslab.in` | Render, Fly.io, VM + reverse proxy, etc. |

The browser loads the app from **peopleopslab.in**; all API calls go to **`NEXT_PUBLIC_API_URL` = `https://api.peopleopslab.in`**. CORS on the API must allow the app origins above (defaults in `backend/app/config.py` already include apex + `www`).

If you later serve the app from another hostname (for example `https://app.peopleopslab.in`), add that origin to `CORS_ORIGINS` on the API.

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

`.env.local` should keep **`NEXT_PUBLIC_API_URL=http://localhost:8000`** for local API. Open [http://localhost:3000](http://localhost:3000).

## Deploying on GitHub

1. **Create a GitHub repository** and push this folder as the repo root (it already contains `.git`).

2. **CI** runs on every push/PR via `.github/workflows/ci.yml` (backend `compileall`, frontend `npm ci` + `npm run build`).

## Production environment variables

**API (`api.peopleopslab.in`)**

| Variable | Value |
|----------|--------|
| `JWT_SECRET` | Long random secret (never reuse dev default) |
| `DATABASE_URL` | Managed Postgres URL (recommended); or persistent SQLite only for experiments |
| `CORS_ORIGINS` | At minimum `https://peopleopslab.in,https://www.peopleopslab.in` (comma-separated). Keep `http://localhost:3000` if you sometimes hit prod API from local Next. |
| `ALLOW_ANONYMOUS_API` | `false` |

**Frontend (peopleopslab.in build & runtime)**

| Variable | Value |
|----------|--------|
| `NEXT_PUBLIC_API_URL` | **`https://api.peopleopslab.in`** (no path, no trailing slash) |

## DNS

- **`peopleopslab.in`** → Next.js deployment (apex).
- **`www.peopleopslab.in`** → same Next.js deployment (CNAME or ALIAS).
- **`api.peopleopslab.in`** → FastAPI deployment; TLS certificate on this hostname.

## Smoke test after deploy

1. Open `https://peopleopslab.in`, sign up or log in.
2. Payroll upload → validate → on Results use **Excel audit**.
3. In DevTools **Network**, requests should target `https://api.peopleopslab.in` (or whatever you set) and return `200`.

## Security reminders

- Never commit `.env` or `.env.local`.
- Rotate `JWT_SECRET` if it was ever committed or leaked.
- Use HTTPS on both app and API in production.
