"""
Endpoints of the integration API, version 1.

Each one calls the service the product's own screens call — imports go
through ``services.ingest`` and ``services.register_ingest``, validation
through the validation job queue, findings through ``services.issues``, BI
through ``services.dashboards``. Nothing here calculates payroll.
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Body, Depends, Path, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.integration.deps import (
    envelope,
    get_company,
    get_principal,
    idempotent,
    page_params,
    paged,
    request_id,
    require,
)
from app.integration.errors import ApiError
from app.integration.schemas import (
    IMPORT_EXAMPLES,
    RULE_PROPOSAL_EXAMPLE,
    AssignmentRequest,
    BiQuery,
    CommentRequest,
    DecisionRequest,
    ImportRequest,
    ValidationJobRequest,
)
from app.models import Entity, FindingState, StudioRun, ValidationJob, ValidationRun
from app.schemas.validation_matrix import RuleCreate
from app.services import audit, issues
from app.services import validation_jobs as jobs
from app.services.studio import imports, runs
from app.services.studio.credentials import SCOPES, Principal

router = APIRouter()

# Scope checks, built once.
NEEDS_BI_READ = require("bi:read")
NEEDS_CONFIG_PROPOSE = require("config:propose")
NEEDS_CONFIG_READ = require("config:read")
NEEDS_FINDINGS_WRITE = require("findings:write")
NEEDS_IMPORTS_READ = require("imports:read")
NEEDS_IMPORTS_WRITE = require("imports:write")
NEEDS_SIGNOFF_READ = require("signoff:read")
NEEDS_VALIDATION_READ = require("validation:read")
NEEDS_VALIDATION_READ_AND_RESULTS_EMPLOYEE = require("validation:read", "results:employee")
NEEDS_VALIDATION_RUN = require("validation:run")

KindPath = Path(..., description="employee_master, ctc, attendance or salary_register",
                pattern="^(employee_master|ctc|attendance|salary_register)$")


def _run_for(db: Session, company: Entity, run_id: str, kind: str | None = None) -> StudioRun:
    try:
        run = db.get(StudioRun, uuid.UUID(run_id))
    except ValueError:
        run = None
    if run is None or run.entity_id != company.id or (kind and run.kind != kind):
        raise ApiError("not_found", "Run not found.")
    return run


def _actor(principal: Principal) -> dict[str, Any]:
    return {
        "actor_type": "machine",
        "actor_user_id": principal.user.id,
        "actor_label": principal.label,
        "service_account_id": principal.account.id,
        "credential_prefix": principal.credential.prefix,
        "environment": principal.account.environment,
    }


def _month(value: str) -> date:
    try:
        return date.fromisoformat(value).replace(day=1)
    except ValueError:
        raise ApiError("invalid_request", "Periods are dates: YYYY-MM-DD (the day is ignored).")


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------
@router.get("/me", tags=["identity"], summary="Who this key is and what it may do")
def me(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    companies = (
        db.query(Entity)
        .filter(Entity.id.in_([uuid.UUID(e) for e in principal.entity_ids]))
        .order_by(Entity.name)
        .all()
    )
    return envelope({
        "service_account": {"id": str(principal.account.id), "name": principal.account.name,
                            "environment": principal.account.environment},
        "credential": {"prefix": principal.credential.prefix,
                       "expires_at": principal.credential.expires_at.isoformat()},
        "scopes": sorted(principal.scopes),
        "companies": [{"id": str(c.id), "name": c.name, "code": c.code} for c in companies if c.is_active],
    })


@router.get("/scopes", tags=["identity"], summary="Every scope a key can hold")
def scopes(principal: Principal = Depends(get_principal)):
    return envelope([{"scope": k, "grants": v} for k, v in SCOPES.items()])


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
@router.post(
    "/imports/{kind}", tags=["imports"], status_code=202,
    summary="Submit a batch of records for import",
    description=(
        "Stages the batch and returns a run at once (202). The run is processed in the background; "
        "poll `GET /imports/{run_id}` for its status and reconciliation counts. **Idempotency-Key is "
        "required**: resend the same request with the same key and you get the same run, never a "
        "second import."
    ),
    openapi_extra={"requestBody": {"content": {"application/json": {"examples": IMPORT_EXAMPLES}}}},
)
async def submit_import(
    request: Request,
    kind: str = KindPath,
    body: ImportRequest = Body(...),
    principal: Principal = Depends(NEEDS_IMPORTS_WRITE),
    company: Entity = Depends(get_company),
    db: Session = Depends(get_db),
):
    rid = request_id(request)
    raw = body.as_options_body()

    def work() -> tuple[int, Any]:
        try:
            options = imports.check_submission(kind, raw)
        except ValueError as exc:
            raise ApiError("invalid_request", str(exc))
        versions: dict[str, Any] = {}
        if raw.get("mapping_key"):
            from app.services.studio import profiles

            version = profiles.in_force(db, company.id, raw["mapping_key"])
            if version is None or version.object_type != kind:
                raise ApiError("invalid_request", f"No published {kind} mapping called {raw['mapping_key']} is in force.")
            versions = {"mapping": f"{version.key} v{version.version}", "mapping_id": str(version.id)}
        run = runs.create(
            db, org_id=company.org_id, entity_id=company.id, kind="import", object_type=kind, versions=versions,
            **_actor(principal), source_system=raw.get("source_system"),
            source_object=raw.get("source_object"), batch_id=raw.get("batch_id"),
            period_month=date.fromisoformat(options["period_month"]) if options.get("period_month") else None,
            effective_from=date.fromisoformat(options["effective_from"]) if options.get("effective_from") else None,
            options=options, payload=raw["records"], request_id=rid,
            idempotency_key=request.headers.get("Idempotency-Key"),
        )
        audit.record(
            db, entity_id=company.id, user=principal.user, action="studio.import.submitted",
            object_type="studio_run", object_id=str(run.id),
            summary=f"{imports.LABELS[kind]} import of {len(raw['records']):,} records submitted by "
                    f"{principal.label}",
            detail={"batch_id": raw.get("batch_id"), "request_id": rid},
        )
        db.commit()
        return 202, runs.describe(db, run)

    status, payload, replayed = await idempotent(request, db, principal, company, work)
    return JSONResponse(status_code=status, content=payload,
                        headers={"Idempotent-Replayed": "true"} if replayed else None)


@router.post(
    "/imports/{kind}/check", tags=["imports"],
    summary="Check a batch without storing it",
    description="Runs every check and the same commit as a real import, then rolls it back. Returns the "
                "counts the import would report and every record it would reject, with the reason.",
    openapi_extra={"requestBody": {"content": {"application/json": {"examples": IMPORT_EXAMPLES}}}},
)
def check_import(
    kind: str = KindPath,
    body: ImportRequest = Body(...),
    principal: Principal = Depends(NEEDS_IMPORTS_WRITE),
    company: Entity = Depends(get_company),
    db: Session = Depends(get_db),
):
    try:
        out = imports.dry_run(db, entity=company, user=principal.user, actor_label=principal.label,
                              actor_type="machine", kind=kind, body=body.as_options_body(),
                              environment=principal.account.environment)
    except ValueError as exc:
        raise ApiError("invalid_request", str(exc))
    return envelope(out)


@router.get("/imports", tags=["imports"], summary="List import runs")
def list_imports(
    status: str | None = Query(default=None, description="queued, running, completed, partially_completed, failed, cancelled"),
    object_type: str | None = Query(default=None),
    batch_id: str | None = Query(default=None),
    page: int = Query(default=1),
    page_size: int = Query(default=50),
    principal: Principal = Depends(NEEDS_IMPORTS_READ),
    company: Entity = Depends(get_company),
    db: Session = Depends(get_db),
):
    page, page_size = page_params(page, page_size)
    rows, total = runs.search(db, company.id, kind="import", status=status, object_type=object_type,
                              q=batch_id, page=page, page_size=page_size)
    return envelope(paged([runs.describe(db, r) for r in rows], page, page_size, total))


@router.get("/imports/{run_id}", tags=["imports"], summary="An import run: status, counts, errors, lineage")
def get_import(
    run_id: str,
    principal: Principal = Depends(NEEDS_IMPORTS_READ),
    company: Entity = Depends(get_company),
    db: Session = Depends(get_db),
):
    return envelope(runs.describe(db, _run_for(db, company, run_id, "import"), detail=True))


@router.get("/imports/{run_id}/rejections", tags=["imports"],
            summary="Records the run rejected or skipped, with row, field and reason")
def get_rejections(
    run_id: str,
    disposition: str | None = Query(default=None, pattern="^(rejected|skipped)$"),
    page: int = Query(default=1),
    page_size: int = Query(default=100),
    principal: Principal = Depends(NEEDS_IMPORTS_READ),
    company: Entity = Depends(get_company),
    db: Session = Depends(get_db),
):
    page, page_size = page_params(page, page_size)
    run = _run_for(db, company, run_id, "import")
    rows, total = runs.rejections(db, run, page=page, page_size=page_size, disposition=disposition)
    return envelope(paged([runs.describe_rejection(r) for r in rows], page, page_size, total))


@router.post("/imports/{run_id}/retry-rejected", tags=["imports"], status_code=202,
             summary="Queue the run's rejected records again, as a new run",
             description="Useful when the rejection was caused by configuration that has since been fixed. "
                         "Records that were accepted are not resent. The retry always adds (upsert), even when "
                         "the first run replaced: the retried records never become the whole version. Records read "
                         "through a mapping are read again with the version in force now, which the new run names. "
                         "Idempotency-Key is required.")
async def retry_rejected(
    request: Request,
    run_id: str,
    principal: Principal = Depends(NEEDS_IMPORTS_WRITE),
    company: Entity = Depends(get_company),
    db: Session = Depends(get_db),
):
    def work() -> tuple[int, Any]:
        run = _run_for(db, company, run_id, "import")
        try:
            new = imports.retry_rejected(db, run, actor=principal.user, actor_label=principal.label,
                                         actor_type="machine", service_account_id=principal.account.id,
                                         credential_prefix=principal.credential.prefix)
        except ValueError as exc:
            raise ApiError("conflict", str(exc))
        db.commit()
        return 202, runs.describe(db, new)

    status, payload, replayed = await idempotent(request, db, principal, company, work)
    return JSONResponse(status_code=status, content=payload,
                        headers={"Idempotent-Replayed": "true"} if replayed else None)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
@router.post("/validation-jobs", tags=["validation"], status_code=202,
             summary="Start validating a month",
             description="Queues validation of the month's latest stored register (or the one named). A "
                         "second request while one is live returns the live job with `already_queued: true`. "
                         "Idempotency-Key is required.")
async def start_validation(
    request: Request,
    body: ValidationJobRequest,
    principal: Principal = Depends(NEEDS_VALIDATION_RUN),
    company: Entity = Depends(get_company),
    db: Session = Depends(get_db),
):
    rid = request_id(request)

    def work() -> tuple[int, Any]:
        upload_id = None
        if body.upload_id:
            try:
                upload_id = uuid.UUID(body.upload_id)
            except ValueError:
                raise ApiError("not_found", "Upload not found.")
        try:
            job, already = jobs.submit_for_period(
                db, entity_id=company.id, user_id=principal.user.id, period_month=body.period_month,
                upload_id=upload_id, run_type=body.run_type, params={},
            )
        except jobs.SubmitError as exc:
            raise ApiError("not_found" if exc.status == 404 else "invalid_request", exc.detail)
        run = None
        if not already:
            db.flush()
            run = runs.create(
                db, org_id=company.org_id, entity_id=company.id, kind="validation",
                object_type="validation", **_actor(principal), period_month=job.period_month,
                request_id=rid, idempotency_key=request.headers.get("Idempotency-Key"), status="running",
            )
            run.validation_job_id = job.id
            audit.record(
                db, entity_id=company.id, user=principal.user, action="studio.validation.started",
                object_type="validation_job", object_id=str(job.id),
                summary=f"Validation of {job.period_month:%b %Y} started by {principal.label}",
                detail={"request_id": rid},
            )
            db.commit()
        return 202, {"job": jobs.describe(job, db), "already_queued": already,
                     "studio_run_id": str(run.id) if run else None}

    status, payload, replayed = await idempotent(request, db, principal, company, work)
    return JSONResponse(status_code=status, content=payload,
                        headers={"Idempotent-Replayed": "true"} if replayed else None)


@router.get("/validation-jobs/{job_id}", tags=["validation"], summary="A validation job's progress")
def get_validation_job(
    job_id: str,
    principal: Principal = Depends(NEEDS_VALIDATION_READ),
    company: Entity = Depends(get_company),
    db: Session = Depends(get_db),
):
    try:
        job = db.get(ValidationJob, uuid.UUID(job_id))
    except ValueError:
        job = None
    if job is None or job.entity_id != company.id:
        raise ApiError("not_found", "Validation job not found.")
    return envelope(jobs.describe(job, db))


def _validation_run(db: Session, company: Entity, run_id: str) -> ValidationRun:
    try:
        run = db.get(ValidationRun, uuid.UUID(run_id))
    except ValueError:
        run = None
    if run is None or run.entity_id != company.id:
        raise ApiError("not_found", "Validation run not found.")
    return run


@router.get("/validation-runs", tags=["validation"], summary="Validation runs, newest first")
def list_validation_runs(
    period_month: str | None = Query(default=None),
    include_superseded: bool = Query(default=False),
    page: int = Query(default=1),
    page_size: int = Query(default=50),
    principal: Principal = Depends(NEEDS_VALIDATION_READ),
    company: Entity = Depends(get_company),
    db: Session = Depends(get_db),
):
    from app.routers.validation_runs import _describe_run

    page, page_size = page_params(page, page_size)
    query = db.query(ValidationRun).filter(ValidationRun.entity_id == company.id)
    if period_month:
        query = query.filter(ValidationRun.period_month == _month(period_month))
    if not include_superseded:
        query = query.filter(ValidationRun.status == "current")
    total = query.count()
    rows = (query.order_by(ValidationRun.period_month.desc(), ValidationRun.run_number.desc())
            .offset((page - 1) * page_size).limit(page_size).all())
    return envelope(paged([_describe_run(db, r, with_upload=False) for r in rows], page, page_size, total))


@router.get("/validation-runs/{run_id}", tags=["validation"],
            summary="One validation run: summary, coverage, and whether its inputs have changed since")
def get_validation_run(
    run_id: str,
    principal: Principal = Depends(NEEDS_VALIDATION_READ),
    company: Entity = Depends(get_company),
    db: Session = Depends(get_db),
):
    from app.routers.validation_runs import get_run

    _validation_run(db, company, run_id)
    return envelope(get_run(run_id=run_id, db=db, user=principal.user, entity=company)["data"])


@router.get("/validation-runs/{run_id}/findings", tags=["validation"], summary="A run's findings, paged")
def get_validation_findings(
    run_id: str,
    severity: str | None = Query(default=None, pattern="^(CRITICAL|WARNING|INFO)$"),
    rule_id: str | None = Query(default=None),
    employee_id: str | None = Query(default=None),
    sort: str = Query(default="financial_impact", pattern="^(financial_impact|employee_id|rule_id|severity)$"),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1),
    page_size: int = Query(default=100),
    principal: Principal = Depends(NEEDS_VALIDATION_READ),
    company: Entity = Depends(get_company),
    db: Session = Depends(get_db),
):
    from app.routers.validation_runs import list_run_findings

    page, page_size = page_params(page, page_size)
    _validation_run(db, company, run_id)
    data = list_run_findings(
        run_id=run_id, page=page, page_size=page_size, sort=sort, order=order, severity=severity,
        rule_id=rule_id, employee_id=employee_id, rule_prefix=None, q=None,
        # Called as a function, so every Query parameter needs its value spelled
        # out — a default here would be the Query object itself.
        component=None, state=None, owner=None, location=None, db=db,
        user=principal.user, entity=company,
    )["data"]
    # The integration contract's rule summary is unchanged by the product
    # screen's richer facets.
    rules = [{k: r[k] for k in ("rule_id", "rule_name", "severity", "count")} for r in data["rules"]]
    return envelope(paged(data["items"], page, page_size, data["total"], rules=rules))


@router.get("/validation-runs/{run_id}/employees", tags=["validation"],
            summary="Per-employee results of a run, paged (needs results:employee)")
def get_validation_employees(
    run_id: str,
    only_with_findings: bool = Query(default=False),
    page: int = Query(default=1),
    page_size: int = Query(default=100),
    principal: Principal = Depends(NEEDS_VALIDATION_READ_AND_RESULTS_EMPLOYEE),
    company: Entity = Depends(get_company),
    db: Session = Depends(get_db),
):
    from app.routers.validation_runs import list_run_employees

    page, page_size = page_params(page, page_size)
    _validation_run(db, company, run_id)
    data = list_run_employees(
        run_id=run_id, page=page, page_size=page_size, sort="risk_score", order="desc", q=None,
        risk_level=None, only_with_findings=only_with_findings, only_unverifiable=False, department=None,
        include_computed=False, db=db, user=principal.user, entity=company,
    )["data"]
    return envelope(paged(data["items"], page, page_size, data["total"], risk_levels=data["risk_levels"]))


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------
def _state(db: Session, company: Entity, fingerprint: str) -> FindingState:
    state = (db.query(FindingState)
             .filter(FindingState.entity_id == company.id, FindingState.fingerprint == fingerprint).first())
    if state is None:
        raise ApiError("not_found", "Finding not found.")
    return state


def _issue(db: Session, state: FindingState) -> dict[str, Any]:
    from app.routers.findings import _issue_out

    return _issue_out(db, state)


@router.get("/findings", tags=["findings"], summary="The findings worklist across months, paged")
def list_findings(
    state: str | None = Query(default="active", pattern="^(active|open|acknowledged|waived|resolved)$"),
    severity: str | None = Query(default=None, pattern="^(CRITICAL|WARNING|INFO)$"),
    rule_id: str | None = Query(default=None),
    overdue: bool = Query(default=False),
    page: int = Query(default=1),
    page_size: int = Query(default=100),
    principal: Principal = Depends(NEEDS_VALIDATION_READ),
    company: Entity = Depends(get_company),
    db: Session = Depends(get_db),
):
    page, page_size = page_params(page, page_size)
    if issues.expire_waivers(db, company.id):
        db.commit()
    out = issues.worklist(db, company, principal.user, page=page, page_size=min(page_size, 200),
                          state=state, severity=severity, rule_id=rule_id, owner=None, overdue=overdue,
                          recurring=False, q=None, sort="priority")
    return envelope(paged(out["items"], page, min(page_size, 200), out["total"], counts=out.get("counts")))


@router.get("/findings/assignees", tags=["findings"], summary="People a finding can be assigned to")
def list_assignees(
    principal: Principal = Depends(NEEDS_FINDINGS_WRITE),
    company: Entity = Depends(get_company),
    db: Session = Depends(get_db),
):
    return envelope(issues.assignees(db, company))


@router.patch("/findings/{fingerprint}/assignment", tags=["findings"], summary="Set owner and due date")
def assign_finding(
    fingerprint: str,
    body: AssignmentRequest,
    principal: Principal = Depends(NEEDS_FINDINGS_WRITE),
    company: Entity = Depends(get_company),
    db: Session = Depends(get_db),
):
    state = _state(db, company, fingerprint)
    owner = None
    if body.owner_user_id:
        try:
            owner = uuid.UUID(body.owner_user_id)
        except ValueError:
            raise ApiError("invalid_request", "owner_user_id is not a valid id.")
    try:
        issues.assign(db, entity=company, state=state, actor=principal.user, owner_user_id=owner,
                      due_date=body.due_date)
    except issues.IssueError as exc:
        raise ApiError("invalid_request", str(exc))
    db.commit()
    return envelope(_issue(db, state))


@router.post("/findings/{fingerprint}/comments", tags=["findings"], summary="Add a comment")
async def comment_finding(
    request: Request,
    fingerprint: str,
    body: CommentRequest,
    principal: Principal = Depends(NEEDS_FINDINGS_WRITE),
    company: Entity = Depends(get_company),
    db: Session = Depends(get_db),
):
    def work() -> tuple[int, Any]:
        state = _state(db, company, fingerprint)
        try:
            comment = issues.add_comment(db, state=state, actor=principal.user, body=body.body)
        except issues.IssueError as exc:
            raise ApiError("invalid_request", str(exc))
        db.commit()
        return 200, {"id": str(comment.id), "body": comment.body, "author": principal.account.name,
                     "created_at": comment.created_at.isoformat() if comment.created_at else None}

    status, payload, replayed = await idempotent(request, db, principal, company, work, required=False)
    return JSONResponse(status_code=status, content=payload,
                        headers={"Idempotent-Replayed": "true"} if replayed else None)


@router.post("/findings/{fingerprint}/decision", tags=["findings"],
             summary="Acknowledge or reopen a finding",
             description="A key may acknowledge a finding or put it back to open. Waiving accepts an exception "
                         "and resolving asserts it was fixed — both are a person's decision, so a key receives "
                         "`approval_required`.")
def decide_finding(
    fingerprint: str,
    body: DecisionRequest,
    principal: Principal = Depends(NEEDS_FINDINGS_WRITE),
    company: Entity = Depends(get_company),
    db: Session = Depends(get_db),
):
    if body.state in ("waived", "resolved"):
        raise ApiError("approval_required",
                       f"Marking a finding {body.state} is a person's decision. A key can acknowledge or reopen it.")
    state = _state(db, company, fingerprint)
    try:
        issues.decide(db, state=state, actor=principal.user, to_state=body.state, reason=None,
                      waived_until=None, note=body.note)
    except issues.IssueError as exc:
        raise ApiError("invalid_request", str(exc))
    db.commit()
    return envelope(_issue(db, state))


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
@router.get("/configuration", tags=["configuration"],
            summary="The company's configuration: components, statutory settings, rules and thresholds")
def get_configuration(
    principal: Principal = Depends(NEEDS_CONFIG_READ),
    company: Entity = Depends(get_company),
    db: Session = Depends(get_db),
):
    from app.routers.config_bundle import _export

    return envelope(_export(db, company.id))


@router.get("/configuration/rules", tags=["configuration"], summary="Company validation rules, every version")
def get_rules(
    principal: Principal = Depends(NEEDS_CONFIG_READ),
    company: Entity = Depends(get_company),
    db: Session = Depends(get_db),
):
    from app.routers.validation_matrix import list_rules

    return envelope(list_rules(db=db, entity=company)["data"])


@router.post("/configuration/rules", tags=["configuration"], status_code=201,
             summary="Propose a validation-rule change for a person to publish",
             description="Creates a draft and submits it for approval (status `pending`). It never takes effect "
                         "until an owner or manager publishes it in the product — and where the organisation "
                         "requires independent approval, that person is someone other than the key's creator. "
                         "Idempotency-Key is required.",
             openapi_extra={"requestBody": {"content": {"application/json": {"example": RULE_PROPOSAL_EXAMPLE}}}})
async def propose_rule(
    request: Request,
    body: RuleCreate,
    principal: Principal = Depends(NEEDS_CONFIG_PROPOSE),
    company: Entity = Depends(get_company),
    db: Session = Depends(get_db),
):
    def work() -> tuple[int, Any]:
        from fastapi import HTTPException

        from app.routers.validation_matrix import create_rule, submit

        try:
            draft = create_rule(body=body, db=db, user=principal.user, entity=company)["data"]
            pending = submit(rule_id=uuid.UUID(draft["id"]), db=db, user=principal.user, entity=company)["data"]
        except HTTPException as exc:
            raise ApiError("invalid_request", str(exc.detail))
        audit.record(db, entity_id=company.id, user=principal.user, action="studio.rule.proposed",
                     object_type="validation_rule", object_id=pending["id"],
                     summary=f"{principal.label} proposed {pending['rule_key']} v{pending['version']} for approval")
        db.commit()
        return 201, pending

    status, payload, replayed = await idempotent(request, db, principal, company, work)
    return JSONResponse(status_code=status, content=payload,
                        headers={"Idempotent-Replayed": "true"} if replayed else None)


# ---------------------------------------------------------------------------
# BI
# ---------------------------------------------------------------------------
@router.get("/bi/datasets", tags=["bi"], summary="Datasets, metrics, breakdowns and filters")
def bi_datasets(principal: Principal = Depends(NEEDS_BI_READ)):
    from app.services import dashboards

    return envelope(dashboards.catalogue())


@router.post("/bi/query", tags=["bi"], summary="An aggregate metric with its data basis")
def bi_query(
    body: BiQuery,
    principal: Principal = Depends(NEEDS_BI_READ),
    company: Entity = Depends(get_company),
    db: Session = Depends(get_db),
):
    from app.services import dashboards

    try:
        out = dashboards.query(db, company, dataset=body.dataset, metric=body.metric, breakdown=body.breakdown,
                               granularity=body.granularity, filters=body.filters, period=body.period)
    except dashboards.QueryError as exc:
        raise ApiError("invalid_request", str(exc))
    return envelope(out)


# ---------------------------------------------------------------------------
# Periods and sign-off
# ---------------------------------------------------------------------------
@router.get("/periods/{period}/status", tags=["sign-off"],
            summary="Where a month stands: uploaded, validated, issues, ready, signed off")
def period_status(
    period: str,
    principal: Principal = Depends(NEEDS_SIGNOFF_READ),
    company: Entity = Depends(get_company),
    db: Session = Depends(get_db),
):
    from app.routers.validation_runs import period_status as screen_status

    _month(period)
    return envelope(screen_status(period=period, db=db, user=principal.user, entity=company)["data"])


@router.get("/periods/{period}/evidence", tags=["sign-off"],
            summary="Sign-off record and evidence metadata — digests and references, not the evidence itself")
def period_evidence(
    period: str,
    principal: Principal = Depends(NEEDS_SIGNOFF_READ),
    company: Entity = Depends(get_company),
    db: Session = Depends(get_db),
):
    from app.models import PeriodSignOff, SignOffEvent

    month = _month(period)
    row = (db.query(PeriodSignOff)
           .filter(PeriodSignOff.entity_id == company.id, PeriodSignOff.period_month == month).first())
    if row is None:
        return envelope({"period_month": month.isoformat(), "state": None, "evidence": None,
                         "note": "Nothing has been submitted or signed for this month."})
    snapshot = row.snapshot or {}
    events = (db.query(SignOffEvent).filter(SignOffEvent.signoff_id == row.id)
              .order_by(SignOffEvent.created_at).all())
    run = snapshot.get("validation_run") or {}
    return envelope({
        "period_month": month.isoformat(),
        "state": row.state,
        "snapshot_digest": row.snapshot_digest,
        "validation_run": {"id": run.get("id"), "run_number": run.get("run_number"),
                           "input_digests": run.get("input_digests")},
        "approval": {k: snapshot.get(k) for k in ("preparer", "approver", "independent") if k in snapshot},
        "history": [{"from_state": e.from_state, "to_state": e.to_state, "actor": e.actor_email,
                     "snapshot_digest": e.snapshot_digest,
                     "at": e.created_at.isoformat() if e.created_at else None} for e in events],
        "evidence_pack": {"available": row.state == "signed",
                          "retrieve_in_product": f"/reconciliation?period={month.isoformat()}"},
    })


# ---------------------------------------------------------------------------
# Inbound webhooks
# ---------------------------------------------------------------------------
@router.post("/hooks/{token}", tags=["webhooks"], status_code=202,
             summary="Push records to a Studio inbound endpoint (signed, no API key)",
             description="Authenticated by signature, not by key: `X-PeopleOpsLab-Signature: t=<unix seconds>,"
                         "v1=<hex HMAC-SHA256(secret, \"<t>.<raw body>\")>` with the endpoint's secret, and a unique "
                         "`X-PeopleOpsLab-Event-Id`. A timestamp more than five minutes off is refused "
                         "(`signature_expired`). The same event id again answers 200 with `duplicate: true` and "
                         "starts nothing. Body: `{\"records\": [...], \"batch_id\": ..., \"period_month\": ...}`; the "
                         "endpoint's configured import type, mapping and options apply.")
async def inbound_hook(token: str, request: Request, db: Session = Depends(get_db)):
    from fastapi.concurrency import run_in_threadpool

    from app.config import settings
    from app.services.studio import ratelimit, webhooks

    rid = request_id(request)
    decision = ratelimit.check(f"hook:{token[:16]}", settings.integration_rate_limit_per_minute)
    request.state.rate_limit = decision
    if not decision.allowed:
        raise ApiError("rate_limited", headers={"Retry-After": str(decision.reset_seconds)})
    body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}
    try:
        out = await run_in_threadpool(webhooks.receive, db, token, headers, body, rid)
    except webhooks.WebhookError as exc:
        raise ApiError(exc.code, str(exc), status=exc.status) from exc
    return JSONResponse(status_code=200 if out["duplicate"] else 202, content=envelope(out))
