# Deployment guide — Payroll Validation SaaS

This is the **operational** guide. The `README.md` covers product / dev. This
document focuses on getting `peopleopslab.in` live end-to-end on:

| Layer        | Service              | Reason                                              |
| ------------ | -------------------- | --------------------------------------------------- |
| Frontend     | **Vercel**           | Native Next.js App Router support                   |
| Backend API  | **Render** (or Railway) | Docker-friendly, $7 starter, free Postgres add-on |
| Database     | **Render Postgres**  | Auto-provisioned by `render.yaml`                   |

---

## 1) Prerequisites

* GitHub repo pushed to `main`.
* Domain `peopleopslab.in` you control (Cloudflare / Namecheap / GoDaddy / Route 53).
* Vercel + Render accounts.

---

## 2) Backend on Render (recommended path — Blueprint)

The repo ships a `render.yaml` Blueprint. Render reads it and provisions the
service + database in one click.

1. Render dashboard → **New** → **Blueprint** → connect your GitHub repo.
2. Confirm the proposed services:
   * `payroll-saas-api`  (web, Docker, free SSL)
   * `payroll-saas-db`   (Postgres 16, free plan)
3. Render auto-fills `DATABASE_URL`. Confirm these env vars are set:
   * `ENV=production`
   * `ALLOW_ANONYMOUS_API=false`
   * `JWT_SECRET` ← Render generates one
   * `CORS_ORIGINS=https://peopleopslab.in,https://www.peopleopslab.in`
4. Wait for build → first deploy. Verify:
   ```bash
   curl https://payroll-saas-api.onrender.com/api/health
   # {"success": true, "data": {"status": "ok", "version": "1.1.0", "env": "production"}, "error": null}
   ```
5. Add custom domain `api.peopleopslab.in`:
   * Render → Service → Settings → **Custom Domain** → `api.peopleopslab.in`.
   * In your DNS, create a `CNAME api → <service>.onrender.com`.
   * Wait for the green TLS lock in Render.

### 2b) Alternative — Railway

* Use the included `railway.json`. New project → deploy from repo → set the
  same env vars listed above. Railway gives you a `*.up.railway.app` host;
  point `api.peopleopslab.in` at it via CNAME.

---

## 3) Frontend on Vercel

1. Vercel → **Add New** → **Project** → import the GitHub repo.
2. **Root Directory:** `frontend` (Vercel detects Next.js).
3. **Environment Variables (Production):**
   * `BACKEND_URL=https://api.peopleopslab.in`   ← server-only (NO `NEXT_PUBLIC_` prefix)
   * Optional: `NEXT_PUBLIC_API_URL=https://api.peopleopslab.in` (for any direct fallback path)
4. Deploy. Verify on the assigned URL:
   * `/` — login page renders.
   * `/api/proxy/api/health` — returns the health JSON envelope through the proxy.
5. Add custom domains:
   * Vercel → Project → Domains → add `peopleopslab.in` and `www.peopleopslab.in`.
   * Apex (`peopleopslab.in`) → A record `76.76.21.21`.
   * `www`  → CNAME `cname.vercel-dns.com`.

---

## 4) DNS summary

| Host                       | Type  | Target                       |
| -------------------------- | ----- | ---------------------------- |
| `peopleopslab.in`          | A     | `76.76.21.21` (Vercel)       |
| `www.peopleopslab.in`      | CNAME | `cname.vercel-dns.com`       |
| `api.peopleopslab.in`      | CNAME | `<service>.onrender.com`     |

---

## 5) Smoke tests (post-deploy)

```bash
# 1) Backend direct
curl https://api.peopleopslab.in/api/health

# 2) Backend through Vercel proxy (must work for the SPA)
curl https://peopleopslab.in/api/proxy/api/health

# 3) Tax engine sanity
curl -X POST https://api.peopleopslab.in/api/income-tax/compare \
  -H 'Content-Type: application/json' \
  -d '{"annual_gross": 1500000}'

# 4) Auth: signup → login
curl -X POST https://api.peopleopslab.in/api/auth/signup \
  -H 'Content-Type: application/json' \
  -d '{"email":"qa@peopleopslab.in","password":"Strong-Pwd-123","company_name":"QA Co"}'
```

All four must return HTTP 200 with `{"success": true, ...}`.

---

## 6) Environment variable reference

### Backend (Render / Railway)

| Var                  | Required | Example                                                    |
| -------------------- | -------- | ---------------------------------------------------------- |
| `ENV`                | yes      | `production`                                               |
| `DATABASE_URL`       | yes      | `postgres://...` (Render injects automatically)            |
| `JWT_SECRET`         | yes      | `openssl rand -hex 48`                                     |
| `CORS_ORIGINS`       | yes      | `https://peopleopslab.in,https://www.peopleopslab.in`      |
| `CORS_ORIGIN_REGEX`  | no       | `^https://.*-myteam\.vercel\.app$` (preview deployments)   |
| `ALLOW_ANONYMOUS_API`| auto     | `false` (forced false in production by `config.py`)        |
| `PORT`               | platform | Render/Railway inject this                                 |
| `WEB_CONCURRENCY`    | no       | `2`                                                        |

### Frontend (Vercel)

| Var                          | Required | Example                          |
| ---------------------------- | -------- | -------------------------------- |
| `BACKEND_URL` (server-only)  | yes      | `https://api.peopleopslab.in`    |
| `NEXT_PUBLIC_API_URL`        | optional | `https://api.peopleopslab.in`    |
| `NEXT_PUBLIC_USE_API_RELAY`  | optional | `1` to force proxy on any host   |
| `NEXT_PUBLIC_DIRECT_API`     | optional | `1` to disable proxy entirely    |

---

## 7) Local dev (Docker)

```bash
docker compose -f docker/docker-compose.yml up --build
# Frontend  http://localhost:3000
# Backend   http://localhost:8000
# Postgres  localhost:5432 (payroll/payroll/payroll_db)
```

To run without Docker:

```bash
# backend
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements-postgres.txt
uvicorn app.main:app --reload

# frontend (separate shell)
cd frontend && npm ci && npm run dev
```

---

## 8) Rollbacks

* **Render**: Service → Deploys → click any prior green deploy → **Redeploy**.
* **Vercel**: Deployments → previous → **Promote to Production**.
* **Database**: Render Postgres → Backups → **Restore**.

---

## 9) Troubleshooting

* **"Could not reach the API" on the SPA:** open
  `https://peopleopslab.in/api/proxy/api/health`. If that returns
  `proxy_misconfigured`, your `BACKEND_URL` is unset on Vercel.
* **CORS error in browser console:** the API's `CORS_ORIGINS` does not include
  the SPA host. Update the Render env var and redeploy.
* **502 from Render:** check Render → Service → Logs. Common causes: app
  crashed during startup (missing env), wrong port (must use `$PORT`).
* **Database connection refused:** confirm `DATABASE_URL` starts with
  `postgresql://` (not `mysql://` etc.). The `config.py` normaliser converts
  Render's `postgres://` automatically.
