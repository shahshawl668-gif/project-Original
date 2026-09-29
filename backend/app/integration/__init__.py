"""
The PeopleOpsLab integration API — a separate, versioned application.

Mounted at ``/api/integration/v1`` beside the product API rather than inside
it. The product API serves the screens and is free to change with them; this
one is a contract with other people's systems and changes only by the policy
published in its description. It has its own OpenAPI document
(``/api/integration/v1/openapi.json``), its own docs page, and accepts only
integration keys — never a person's session.
"""
from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.responses import JSONResponse

from app.config import settings
from app.integration import errors
from app.integration.routes import router
from app.services.studio.credentials import SCOPES, redact

logger = logging.getLogger("payroll.integration")

VERSION = "1.0.0"
BASE_PATH = "/api/integration/v1"

#: path template → (deprecation date, sunset date, replacement). Empty today;
#: the mechanism is what the policy promises.
DEPRECATED: dict[str, tuple[str, str, str]] = {}


def _description() -> str:
    scope_rows = "\n".join(f"| `{k}` | {v} |" for k, v in SCOPES.items())
    code_rows = "\n".join(f"| `{k}` | {s} | {m} |" for k, (s, m) in errors.CODES.items())
    return f"""
The integration API lets your HRMS, attendance, finance and payroll systems send data to
PeopleOpsLab, start validation, and read results — without a person at a screen. It calls the
same services the product's screens use. It never runs payroll and never changes a payslip.

## Authentication
Send an integration key as `Authorization: Bearer pol_live_1a2b3c4d_<your key>`. Keys belong to
**service accounts** — machine identities created in Studio → API Centre by an owner or manager —
never to a person. A key carries **scopes** (below) and names the **companies** it may act on.
Keys expire (at most a year out), can be rotated with an overlap, and revoked at once. A person's
session is not accepted here, and a key is not accepted by the product's screens.

## Companies
Send `X-Company-Id: <company id>`. A key naming one company may omit it. A company the key does
not name answers `404 not_found`, the same as one that does not exist.

## Scopes
| Scope | Grants |
|---|---|
{scope_rows}

**What no key can do:** publish a validation rule, waive or resolve a finding, submit or sign a
month, or change who has access. Those are a person's decisions, and the API returns
`approval_required`.

## Asynchronous work
Imports and validation are **jobs**. The submit call returns `202` with a run at once; poll the
run (`GET /imports/{{id}}`, `GET /validation-jobs/{{id}}`) until its status is final:
`queued → running → completed | partially_completed | failed | cancelled`.

Every import reports reconciliation counts:
`received = accepted + rejected + skipped` and `accepted = created + updated + unchanged`.
Rejected records are listed with their row number, field, code and reason
(`GET /imports/{{id}}/rejections`). Nothing is dropped unseen; a value that cannot be read is a
rejection, never a silent blank or zero.

## Idempotency
Submitting an import, retrying rejected records, starting validation and proposing a rule
**require** an `Idempotency-Key` header (any unique string up to 255 characters, e.g. a UUID).
Resend the same request with the same key — after a timeout, say — and you get the first answer
back with `Idempotent-Replayed: true`, never a second import. The same key with a different body
is refused (`409 idempotency_key_reused`). Keys are remembered for 24 hours.

## Pagination and filtering
List endpoints take `page` (from 1) and `page_size` (1–500) and answer
`{{items, page, page_size, total, pages, has_more}}`. Filters are query parameters named in each
endpoint.

## Correlation
Send `X-Request-Id` to correlate your logs with ours; we echo it (or generate one) on every
response, include it in every error, and store it on the runs a request creates.

## Limits
| Limit | Value |
|---|---|
| Requests per key | {settings.integration_rate_limit_per_minute} per minute (`429 rate_limited`, with `Retry-After`) |
| Request body | {settings.integration_max_request_mb} MB (`413 payload_too_large`) |
| Records per import | {settings.integration_max_records:,} |
| Synchronous responses | designed to answer within 30 s; anything longer is a job |
| Rejected-record copies | kept {settings.studio_rejection_retention_days} days; the rejection itself is kept with the run |

Rate limits are counted per key in each API instance.

## Errors
Every error has the envelope `{{"success": false, "data": null, "error": {{"code", "detail",
"request_id"}}}}`. Branch on `code`; show `detail`.

| Code | HTTP | Meaning |
|---|---|---|
{code_rows}

## Versioning and deprecation
This is **v1**. Within v1 we only add: new endpoints, new optional request fields, new response
fields, new error codes, new scopes. Clients must ignore fields they do not know. Anything that
would break a correct v1 client ships as **v2** at a new base path; v1 then keeps working for at
least **12 months**. An endpoint scheduled for removal answers with `Deprecation` and `Sunset`
headers at least **6 months** before its sunset date, and a `Link` to its replacement.
"""


def create_app() -> FastAPI:
    app = FastAPI(
        title="PeopleOpsLab Integration API",
        version=VERSION,
        description=_description(),
        openapi_tags=[
            {"name": "identity", "description": "The calling key."},
            {"name": "imports", "description": "Employee master, CTC, attendance and salary registers."},
            {"name": "validation", "description": "Start validation and read results."},
            {"name": "findings", "description": "Work findings — never waive or resolve."},
            {"name": "configuration", "description": "Read configuration; propose rule changes for approval."},
            {"name": "bi", "description": "Aggregate metrics with their data basis."},
            {"name": "sign-off", "description": "Month status and evidence metadata."},
        ],
        servers=[{"url": BASE_PATH}],
    )

    @app.middleware("http")
    async def guard(request: Request, call_next):
        rid = request.headers.get("X-Request-Id") or getattr(request.state, "request_id", None) or uuid.uuid4().hex[:12]
        request.state.request_id = rid
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > settings.integration_max_request_mb * 1024 * 1024:
            return JSONResponse(status_code=413, headers={"X-Request-Id": rid},
                                content=errors.body("payload_too_large",
                                                    f"The request body is over {settings.integration_max_request_mb} MB.", rid))
        response = await call_next(request)
        response.headers["X-Request-Id"] = rid
        response.headers["X-API-Version"] = VERSION
        decision = getattr(request.state, "rate_limit", None)
        if decision is not None:
            response.headers["X-RateLimit-Limit"] = str(decision.limit)
            response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
            response.headers["X-RateLimit-Reset"] = str(decision.reset_seconds)
        route = request.scope.get("route")
        template = getattr(route, "path", None)
        if template in DEPRECATED:
            deprecated_on, sunset, replacement = DEPRECATED[template]
            response.headers["Deprecation"] = deprecated_on
            response.headers["Sunset"] = sunset
            response.headers["Link"] = f'<{replacement}>; rel="successor-version"'
        return response

    def _rid(request: Request) -> str | None:
        return getattr(request.state, "request_id", None)

    @app.exception_handler(errors.ApiError)
    async def api_error(request: Request, exc: errors.ApiError):
        return JSONResponse(status_code=exc.status, headers=exc.headers,
                            content=errors.body(exc.code, exc.message, _rid(request), exc.detail))

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        code = {401: "unauthorized", 403: "forbidden_scope", 404: "not_found", 409: "conflict",
                413: "payload_too_large", 429: "rate_limited"}.get(exc.status_code, "invalid_request")
        return JSONResponse(status_code=exc.status_code,
                            content=errors.body(code, str(exc.detail), _rid(request)))

    @app.exception_handler(RequestValidationError)
    async def schema_error(request: Request, exc: RequestValidationError):
        detail = [{"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
        return JSONResponse(status_code=422, content=errors.body(
            "validation_error", "The request does not match the schema.", _rid(request), detail))

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception):
        # Redacted: a key pasted into a field must not reach the log whole.
        logger.error("integration error rid=%s: %s", _rid(request), redact(repr(exc))[:500])
        return JSONResponse(status_code=500, content=errors.body(
            "internal_error", "Internal error. Retry with the same Idempotency-Key.", _rid(request)))

    app.include_router(router)
    return app


integration_app = create_app()
