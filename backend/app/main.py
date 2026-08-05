"""FastAPI application entrypoint.

Production-grade setup:
  - CORS driven by `CORS_ORIGINS` env (comma separated; supports regex via
    `CORS_ORIGIN_REGEX`).
  - Standard `{success, data, error}` envelope for ALL errors.
  - Lifespan startup boots schema, patches columns, seeds reference data.
  - Health endpoints at `/api/health` and `/api/v1/health`.
  - All API routes mirrored under `/api` and `/api/v1`.
"""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import get_database, init_indexes, ping
from app.deps import SYSTEM_USER_EMAIL
from app.envelope import err_payload, ok
from app.models import User
from app.routers import api_router
from app.seed import seed_reference_data

logger = logging.getLogger("payroll.api")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


def _ensure_system_user(db) -> None:
    existing = User.find_one(db, {"email": SYSTEM_USER_EMAIL})
    if existing:
        if existing.role != "system":
            existing.role = "system"
            existing.save(db)
        return
    User(
        email=SYSTEM_USER_EMAIL,
        password_hash="__no_auth__",
        company_name="PayrollCheck",
        role="system",
    ).insert(db)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # MongoDB is schemaless: there are no tables to create, only indexes to
    # ensure (idempotent) plus reference/system-user seeding.
    db = get_database()
    init_indexes(db)
    seed_reference_data(db)
    _ensure_system_user(db)
    logger.info(
        "API ready | env=%s | db=%s | cors_origins=%s | anonymous=%s",
        settings.env,
        settings.mongodb_db_name,
        settings.cors_origins_list,
        settings.allow_anonymous_api,
    )
    yield


app = FastAPI(
    title="India Payroll Validation API",
    version="1.1.0",
    description="Statutory & payroll validation engine for India payroll teams.",
    lifespan=lifespan,
)

# ------------------ CORS ------------------
# Driven entirely by env. We add localhost dev origins automatically when env is "dev".
_origins = list(settings.cors_origins_list)
if settings.env != "production":
    for o in ("http://localhost:3000", "http://127.0.0.1:3000"):
        if o not in _origins:
            _origins.append(o)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_origin_regex=settings.cors_origin_regex or None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-Id"],
    max_age=600,
)


# ------------------ REQUEST LOGGING ------------------

@app.middleware("http")
async def request_id_and_log(request: Request, call_next):
    request_id = request.headers.get("X-Request-Id") or uuid.uuid4().hex[:12]
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:  # noqa: BLE001 - logged & re-raised below for handler
        logger.exception("Unhandled error %s %s rid=%s", request.method, request.url.path, request_id)
        raise
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    response.headers["X-Request-Id"] = request_id
    if request.url.path.startswith("/api"):
        logger.info(
            "%s %s -> %s in %.1fms rid=%s",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
            request_id,
        )
    return response


# ------------------ EXCEPTION HANDLERS ------------------

@app.exception_handler(HTTPException)
async def http_exception_envelope(_, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "data": None, "error": err_payload(exc.detail)},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_envelope(_, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "data": None,
            "error": err_payload(exc.errors(), code="validation_error"),
        },
    )


@app.exception_handler(Exception)
async def generic_exception_envelope(_, exc: Exception):
    logger.exception("Internal server error: %s", exc)
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "data": None,
            "error": err_payload("Internal server error", code="internal_error"),
        },
    )


# ------------------ HEALTH ------------------

def _health_payload():
    # Report database reachability so a deploy that boots with an unreachable
    # cluster is visible from the health check rather than only at first query.
    db_ok = ping()
    return {
        "status": "ok" if db_ok else "degraded",
        "version": app.version,
        "env": settings.env,
        "database": "mongodb" if db_ok else "unreachable",
    }


@app.get("/api/health", tags=["health"])
def health_root():
    return ok(_health_payload())


@app.get("/api/v1/health", tags=["health"])
def health_v1():
    return ok(_health_payload())


@app.get("/health", tags=["health"])
def health_plain():
    return ok(_health_payload())


# ------------------ ROUTES ------------------

# Mount API routes at both `/api` and `/api/v1` (versioned alias) so clients
# using either path keep working through future revisions.
app.include_router(api_router, prefix="/api")
app.include_router(api_router, prefix="/api/v1")
