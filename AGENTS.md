# AGENTS.md

## Cursor Cloud specific instructions

### Architecture
- **Backend**: FastAPI (Python 3.12) at `backend/` — SQLite for local dev (automatic, no Postgres needed)
- **Frontend**: Next.js 14 (Node 22) at `frontend/` — uses App Router

### Starting services
- **Backend**: `cd backend && source .venv/bin/activate && uvicorn app.main:app --reload --host 127.0.0.1 --port 8000`
- **Frontend**: `cd frontend && npm run dev` (port 3000)
- Health check: `GET http://localhost:8000/api/health`

### Key env setup
- Backend: copy `backend/.env.example` to `backend/.env`, set `ALLOW_ANONYMOUS_API=true` for dev (no auth needed)
- Frontend: create `frontend/.env.local` with `NEXT_PUBLIC_API_URL=http://localhost:8000`
- The backend auto-creates a SQLite DB (`payroll_dev.db`) on first run — no database service needed

### Testing
- Backend tests: `cd backend && source .venv/bin/activate && python -m pytest tests/ -v` (25/28 pass; 3 `compare_regimes` tests have a pre-existing `__dict__` bug on NamedTuple)
- Frontend lint: `cd frontend && npm run lint`
- Frontend build: `cd frontend && npm run build`
- Smoke test (requires backend running): `cd backend && source .venv/bin/activate && python smoke_noauth.py`

### Gotchas
- `python3.12-venv` system package is required to create the backend venv (install with `sudo apt-get install -y python3.12-venv`)
- The backend needs `pytest`, `httpx`, `aiosqlite` installed for tests (not in requirements.txt — install via `pip install pytest pytest-asyncio httpx aiosqlite`)
- The `income-tax/compute` endpoint has a known bug: `TaxBreakup` is a NamedTuple and doesn't support `.__dict__` — use `income-tax/compare` or `payroll/validate` endpoints for testing instead
- Frontend uses `package-lock.json` → use `npm install` (not pnpm/yarn)
