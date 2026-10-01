# Deployment guide — Payroll Validation SaaS

This is the **operational** guide. The `README.md` covers product / dev. This
document focuses on getting `peopleopslab.in` live end-to-end on:

| Layer        | Service              | Reason                                              |
| ------------ | -------------------- | --------------------------------------------------- |
| Frontend     | **Render** (Vercel also works) | Same vendor and region as the API; built from `docker/Dockerfile.frontend` |
| Backend API  | **Render** (or Railway) | Docker-friendly, $7 starter, free Postgres add-on |
| Database     | **Render Postgres**  | Auto-provisioned by `render.yaml`                   |
| Domain & DNS | **GoDaddy**          | Where `peopleopslab.in` is registered               |

---

## 0) What is live right now

Both services run on Render, in Singapore — the closest region to Indian users
that Render offers, and the same region as the database.

| Piece | URL | Render service |
|---|---|---|
| API | https://payroll-saas-api-r6a8.onrender.com | `payroll-saas-api` |
| Web | https://peopleopslab-web.onrender.com, served as https://www.peopleopslab.in | `peopleopslab-web` |
| Database | internal only | `payroll-saas-db` (PostgreSQL 16) |

Both deploy automatically from `main`. The API is built from
`docker/Dockerfile.backend`, the web app from `docker/Dockerfile.frontend`.
The API reads `DATABASE_URL` from Render's environment and runs on the
PostgreSQL database — its startup line says `database=postgresql://…`. The
connection string is deliberately not written down here or anywhere in the
repository. It is a credential; it belongs only in Render's environment.

### Still to do by hand: the free database expires

Render's free PostgreSQL is deleted 30 days after creation — this one on
**22 October 2026** — and the free plan takes no backups. Move it to a paid
plan before real client data goes in, and prove a restore — see
[`docs/DATABASE_MIGRATION.md`](docs/DATABASE_MIGRATION.md) and
[`docs/GO_LIVE.md`](docs/GO_LIVE.md).

### The domain

`peopleopslab.in` is registered at **GoDaddy**, and its DNS is managed there
unless someone has changed the domain's nameservers (GoDaddy → My Products →
`peopleopslab.in` → DNS shows which). Nothing else is involved: no other
hosting account — Hostinger included — holds any part of this product.

Both names point at the **web** service. The API has no name of its own;
browsers reach it through the web app's same-origin `/api/proxy` route.

| Type | Name | Value |
|---|---|---|
| A | `@` | the IP address Render shows for `peopleopslab.in` |
| CNAME | `www` | `peopleopslab-web.onrender.com` |

GoDaddy cannot put a CNAME on the bare domain, which is why `@` is an A
record. Take the address from Render → `peopleopslab-web` → Settings → Custom
Domains, which lists the exact records for each name it serves; do not copy an
address from an old note. Delete any other A or AAAA records on `@` or `www`,
including GoDaddy's default "Parked" record and any domain forwarding — a name
with two answers sends some visitors somewhere else.

These records could not be read from this repository or its tooling. When the
site misbehaves after a DNS change, compare GoDaddy's DNS page with this table
first, then check both names show as verified in Render's Custom Domains.

`api.peopleopslab.in` does not exist and nothing needs it. Creating it is
optional (§2 step 5); if you do, add it to `CORS_ORIGINS` only if browsers will
call it directly.

**Protect the GoDaddy account.** Whoever controls the domain's DNS can send
your users anywhere, including a copy of the sign-in page. Two-step
verification and the domain's transfer lock should both be on; the supplier
register (`docs/security/isms/08-suppliers.md`) records who checked.

## 1) Prerequisites

* GitHub repo pushed to `main`.
* The GoDaddy account that holds `peopleopslab.in`.
* A Render account (Vercel only if you choose it for the frontend, §3b).

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
5. Optional — the live deployment does not do this. To give the API its own
   name, `api.peopleopslab.in`:
   * Render → Service → Settings → **Custom Domain** → `api.peopleopslab.in`.
   * In GoDaddy's DNS, create a `CNAME api → <service>.onrender.com`.
   * Wait for the green TLS lock in Render.

### 2b) Alternative — Railway

* Use the included `railway.json`. New project → deploy from repo → set the
  same env vars listed above. Railway gives you a `*.up.railway.app` host;
  point `api.peopleopslab.in` at it via CNAME.

---

## 3) Frontend

### 3a) On Render — the live setup

The Blueprint does not create the web service; add it once by hand.

1. Render → **New** → **Web Service** → the GitHub repo → runtime **Docker**,
   Dockerfile path `./docker/Dockerfile.frontend`, same region as the API.
2. **Environment:**
   * `BACKEND_URL=<the API's address>`   ← server-only (NO `NEXT_PUBLIC_` prefix).
     That is the API's own `https://<service>.onrender.com` address, unless
     §2 step 5's custom domain exists and shows a green lock.
     `api.peopleopslab.in` was never created, and pointing `BACKEND_URL` at it
     fails every sign-in.
   * Optional: `NEXT_PUBLIC_API_URL=<the same address>` (for any direct fallback path)
3. Deploy. Verify on the `*.onrender.com` address:
   * `/` — login page renders.
   * `/api/proxy/api/health` — returns the health JSON envelope through the proxy.
4. Add custom domains: Render → the web service → Settings → **Custom
   Domains** → add `peopleopslab.in` and `www.peopleopslab.in`, then create the
   records it shows at GoDaddy (§0, The domain). Wait for both to verify and
   show a certificate.

### 3b) On Vercel — an alternative

The repo also ships `frontend/vercel.json` (region `bom1`, Mumbai). Moving the
frontend there changes the DNS records, so do it as a planned change.

1. Vercel → **Add New** → **Project** → import the GitHub repo.
2. **Root Directory:** `frontend` (Vercel detects Next.js).
3. Set `BACKEND_URL` as in §3a.
4. Vercel → Project → Domains → add both names, then at GoDaddy replace the
   §0 records with the ones Vercel shows for each name.

---

## 4) DNS summary — at GoDaddy

| Host                       | Type  | Target                                   |
| -------------------------- | ----- | ---------------------------------------- |
| `peopleopslab.in`          | A     | the IP Render shows for it (§0)          |
| `www.peopleopslab.in`      | CNAME | `peopleopslab-web.onrender.com`          |
| `api.peopleopslab.in`      | —     | none; only if §2 step 5 is done: CNAME `<service>.onrender.com` |

---

## 5) Smoke tests (post-deploy)

The fastest real check is the end-to-end runner. It signs up a throwaway
organization, configures it, uploads three months of payroll, attendance and a
bank file, and asserts that validation, cost analysis and reconciliation all
find the defects planted in the data:

```bash
cd backend
PEOPLEOPSLAB_BASE_URL=https://payroll-saas-api-r6a8.onrender.com python e2e_deployed.py
```

41 checks, non-zero exit on any failure, so it works as a release gate. It only
ever writes inside the organization it creates, so it is safe against a live
deployment — but it does write, so do not aim it at a tenant whose audit trail
matters.

The individual curl checks below are still useful when something is wrong and
you want to narrow it down.


```bash
API=https://payroll-saas-api-r6a8.onrender.com

# 1) Backend direct
curl $API/api/health

# 2) Backend through the web app's proxy (must work for the SPA)
curl https://www.peopleopslab.in/api/proxy/api/health

# 3) Tax engine sanity
curl -X POST $API/api/income-tax/compare \
  -H 'Content-Type: application/json' \
  -d '{"annual_gross": 1500000}'

# 4) Auth: signup → login
curl -X POST $API/api/auth/signup \
  -H 'Content-Type: application/json' \
  -d '{"email":"<a throwaway address you own>","password":"<a long unique password — never a real one in a document>","company_name":"QA Co"}'
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

### Frontend (Render web service, or Vercel)

| Var                          | Required | Example                          |
| ---------------------------- | -------- | -------------------------------- |
| `BACKEND_URL` (server-only)  | yes      | `https://payroll-saas-api-r6a8.onrender.com` |
| `NEXT_PUBLIC_API_URL`        | optional | the same address                 |
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

* **Render** (API and web): Service → Deploys → click any prior green deploy → **Redeploy**.
* **Vercel**, only if the frontend moved there: Deployments → previous → **Promote to Production**.
* **Database**: Render Postgres → Backups → **Restore** — on a paid plan only;
  the free plan has no backups to restore.
* **DNS**: note a record's old value at GoDaddy before editing it — putting
  it back is the rollback.

---

## 9) Troubleshooting

* **"Could not reach the API" on the SPA:** open
  `https://peopleopslab.in/api/proxy/api/health`. If that returns
  `proxy_misconfigured`, `BACKEND_URL` is unset on the web service.
* **The domain does not load, but `peopleopslab-web.onrender.com` does:** the
  problem is DNS or the certificate, not the app. Compare GoDaddy's DNS page
  with §0 and check both names show as verified in Render → Custom Domains.
* **CORS error in browser console:** the API's `CORS_ORIGINS` does not include
  the SPA host. Update the Render env var and redeploy.
* **502 from Render:** check Render → Service → Logs. Common causes: app
  crashed during startup (missing env), wrong port (must use `$PORT`).
* **Database connection refused:** confirm `DATABASE_URL` starts with
  `postgresql://` (not `mysql://` etc.). The `config.py` normaliser converts
  Render's `postgres://` automatically.
