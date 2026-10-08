"""
Workflows: trigger → conditions → actions, as data.

A workflow is a small, fixed vocabulary — not a programming language. Every
action calls a service the screens already use (sync, validation, finding
assignment), so a workflow can do nothing a person could not, and nothing a
person must decide. **There is no action that waives or resolves a finding,
publishes a rule, or submits, approves or signs a month.** Those stay with
people, under the approval controls they already have; a definition naming one
is refused when it is saved.

**How a run executes.** A run is a ``studio_runs`` row of kind ``workflow``,
drained by the same worker loop as imports. Steps run in order. A step that
starts other work — a sync, a validation — records the child and hands the
worker back; the run is requeued a few seconds later and resumes where it
stopped, so a long validation does not hold a worker thread. Each step has a
timeout and a retry count; a failed step runs the failure branch (notify,
webhook) and fails the run with the step named.

**Duplicates and loops.** Every start is written to ``studio_workflow_fires``
under a key — the event id, the schedule slot, the set of inputs — unique per
workflow, so an event seen twice starts one run. Events carry their
*causation*: a workflow never fires on an event its own runs caused, a chain
of workflows stops at depth three, and a workflow starts at most
``max_runs_per_hour`` runs. Each refusal is recorded on the workflow as its
last skip, with the reason.
"""
from __future__ import annotations

import re
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.models import (
    Entity,
    OrgMembership,
    StudioNotification,
    StudioRun,
    StudioStream,
    StudioWebhook,
    StudioWorkflow,
    StudioWorkflowFire,
    User,
)
from app.services import audit, tenancy
from app.services.clock import india_today
from app.services.studio import runs

#: Events a workflow can start on. ``inputs.ready`` is derived: it is checked
#: whenever an import or sync finishes, and fires once per distinct set of inputs.
TRIGGERS: dict[str, str] = {
    "manual": "Started by a person, from Studio.",
    "schedule": "On a schedule, in a named time zone.",
    "import.completed": "An import or sync finished.",
    "inputs.ready": "A month's inputs are all present (checked after every import or sync).",
    "validation.completed": "A month's validation finished.",
    "validation.failed": "A month's validation failed for good.",
    "finding.state_changed": "A finding was acknowledged, waived, resolved or reopened.",
    "period.submitted": "A month was submitted for approval.",
    "period.signed_off": "A month was signed off.",
    "period.reopened": "A signed month was reopened.",
    "inbound.received": "A signed call to one of your inbound webhook endpoints was accepted.",
}

#: What each action does, and whether it may run in the failure branch.
ACTIONS: dict[str, dict[str, Any]] = {
    "sync": {"label": "Fetch and import from a connection",
             "help": "Runs a stream: fetch, apply its published mapping, check and store. Waits for it to finish."},
    "check_readiness": {"label": "Check the month's inputs are present",
                        "help": "Fails (and takes the failure branch) if a required input is missing for the month."},
    "start_validation": {"label": "Validate the month",
                         "help": "Queues validation of the month's latest register and waits for the result."},
    "assign_findings": {"label": "Assign the month's open findings",
                        "help": "Sets an owner and due date on active findings. Never waives or resolves."},
    "notify": {"label": "Notify people in the product", "failure_branch": True,
               "help": "An in-product notification to the chosen people or roles. Nothing leaves the product."},
    "report": {"label": "Send a report link", "failure_branch": True,
               "help": "A notification linking to a report page. The page checks the reader's own access."},
    "webhook": {"label": "Send an outbound webhook", "failure_branch": True,
                "help": "A signed workflow.message event to one of your webhooks, with ids only."},
}

#: Things people sometimes expect a workflow to do, refused by name.
FORBIDDEN_ACTIONS = {
    "waive_finding": "Waiving a finding is a person's decision.",
    "resolve_finding": "Resolving a finding is a person's decision.",
    "publish_rule": "Publishing a rule needs a person's approval.",
    "submit_period": "Submitting a month for approval is a person's decision.",
    "sign_off": "Signing off a month is a person's decision, under its approval controls.",
    "approve": "Approvals are made by people.",
}

SEVERITIES = ("CRITICAL", "WARNING", "INFO")
OPS = ("eq", "ne", "in", "not_in", "gt", "gte", "lt", "lte", "present", "absent")
INPUTS = ("register", "master", "attendance", "ctc", "prior_register")
REPORTS = {
    "validation_results": "Validation results",
    "month_close": "Month close",
    "findings": "Findings worklist",
    "run": "This workflow run",
}
NOTIFY_ROLES = ("owner", "manager", "analyst", "viewer")
MAX_ACTIONS = 20
MAX_DEPTH = 3
WAIT_SECONDS = 5
STEP_BACKOFF_SECONDS = 30
_TEMPLATE = re.compile(r"\{\{\s*([a-z_][a-z0-9_.]*)\s*\}\}")


class WorkflowError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


# ---------------------------------------------------------------------------
# Definitions
# ---------------------------------------------------------------------------
def _uuid(value: Any, what: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise WorkflowError(f"{what} is not a valid id.") from exc


def _members(db: Session, entity: Entity) -> list[tuple[User, str]]:
    """People with a role on this company (machines have none)."""
    rows = (db.query(User).join(OrgMembership, OrgMembership.user_id == User.id)
            .filter(OrgMembership.org_id == entity.org_id).all())
    out = []
    for user in rows:
        role = tenancy.effective_entity_role(db, user, entity)
        if role:
            out.append((user, role))
    return out


def _check_period(value: Any, where: str) -> str:
    value = value or "context"
    if value in ("context", "current_month", "previous_month"):
        return value
    try:
        return date.fromisoformat(str(value)).replace(day=1).isoformat()
    except ValueError as exc:
        raise WorkflowError(f"{where}: period is context, current_month, previous_month or a date.") from exc


def _check_template(value: Any, where: str, limit: int) -> str:
    text_ = str(value or "").strip()
    if len(text_) > limit:
        raise WorkflowError(f"{where} is longer than {limit} characters.")
    return text_


def _check_recipients(db: Session, entity: Entity, params: dict[str, Any], where: str) -> dict[str, Any]:
    roles = [r for r in (params.get("roles") or []) if r]
    bad = [r for r in roles if r not in NOTIFY_ROLES]
    if bad:
        raise WorkflowError(f"{where}: unknown role {bad[0]}.")
    user_ids = [str(u) for u in (params.get("user_ids") or []) if u]
    if user_ids:
        allowed = {str(u.id) for u, _ in _members(db, entity)}
        if any(u not in allowed for u in user_ids):
            raise WorkflowError(f"{where}: a recipient cannot see this company.")
    if not roles and not user_ids:
        raise WorkflowError(f"{where}: choose at least one role or person to notify.")
    return {"roles": roles, "user_ids": user_ids}


def _check_action(db: Session, entity: Entity, action: Any, where: str, failure_branch: bool) -> dict[str, Any]:
    if not isinstance(action, dict):
        raise WorkflowError(f"{where} must be an object.")
    kind = action.get("type")
    if kind in FORBIDDEN_ACTIONS:
        raise WorkflowError(f"{where}: {FORBIDDEN_ACTIONS[kind]} No workflow can do it.")
    if kind not in ACTIONS:
        raise WorkflowError(f"{where}: unknown action {kind!r}.")
    if failure_branch and not ACTIONS[kind].get("failure_branch"):
        raise WorkflowError(f"{where}: the failure branch may only notify, send a report link or a webhook.")
    params = dict(action.get("params") or {})
    out: dict[str, Any] = {"type": kind, "label": _check_template(action.get("label"), f"{where} label", 100)}
    retries = int(action.get("retries", 0) or 0)
    if not 0 <= retries <= 3:
        raise WorkflowError(f"{where}: retries is 0 to 3.")
    timeout = int(action.get("timeout_minutes", 60) or 60)
    if not 1 <= timeout <= 24 * 60:
        raise WorkflowError(f"{where}: timeout is 1 to 1440 minutes.")
    out.update({"retries": retries, "timeout_minutes": timeout})
    if kind == "sync":
        stream = db.get(StudioStream, _uuid(params.get("stream_id"), f"{where} stream"))
        if stream is None or stream.entity_id != entity.id:
            raise WorkflowError(f"{where}: no such stream in this company.")
        out["params"] = {"stream_id": str(stream.id), "fail_on_rejections": bool(params.get("fail_on_rejections"))}
    elif kind == "check_readiness":
        required = [r for r in (params.get("required") or ["register", "master"]) if r]
        bad = [r for r in required if r not in INPUTS]
        if bad or not required:
            raise WorkflowError(f"{where}: required inputs are chosen from {', '.join(INPUTS)}.")
        out["params"] = {"required": required, "period": _check_period(params.get("period"), where)}
    elif kind == "start_validation":
        out["params"] = {"period": _check_period(params.get("period"), where),
                         "fail_on_critical": bool(params.get("fail_on_critical"))}
    elif kind == "assign_findings":
        owner = str(params.get("owner_user_id") or "")
        from app.services import issues

        if owner not in {a["user_id"] for a in issues.assignees(db, entity)}:
            raise WorkflowError(f"{where}: that person cannot work this company's findings.")
        due = int(params.get("due_in_days", 5) or 0)
        if not 0 <= due <= 90:
            raise WorkflowError(f"{where}: due in 0 to 90 days.")
        severities = [s for s in (params.get("severities") or ["CRITICAL", "WARNING"]) if s]
        if any(s not in SEVERITIES for s in severities):
            raise WorkflowError(f"{where}: severities are chosen from {', '.join(SEVERITIES)}.")
        out["params"] = {"owner_user_id": owner, "due_in_days": due, "severities": severities,
                         "only_unassigned": params.get("only_unassigned", True) is not False,
                         "period": _check_period(params.get("period"), where)}
    elif kind in ("notify", "report"):
        p = _check_recipients(db, entity, params, where)
        p["title"] = _check_template(params.get("title") or ("{{workflow}}: report" if kind == "report" else ""),
                                     f"{where} title", 200)
        if not p["title"]:
            raise WorkflowError(f"{where}: a notification needs a title.")
        p["body"] = _check_template(params.get("body"), f"{where} message", 2000)
        p["severity"] = params.get("severity") if params.get("severity") in ("info", "warning", "error") else "info"
        if kind == "report":
            if params.get("report") not in REPORTS:
                raise WorkflowError(f"{where}: report is one of {', '.join(REPORTS)}.")
            p["report"] = params["report"]
        out["params"] = p
    elif kind == "webhook":
        hook = db.get(StudioWebhook, _uuid(params.get("webhook_id"), f"{where} webhook"))
        if hook is None or hook.entity_id != entity.id:
            raise WorkflowError(f"{where}: no such webhook in this company.")
        out["params"] = {"webhook_id": str(hook.id), "message": _check_template(params.get("message"), where, 200)}
    return out


def check_definition(db: Session, entity: Entity, definition: Any) -> dict[str, Any]:
    """Validate a definition before it is saved. Returns it normalised."""
    from app.services.studio import sync

    if not isinstance(definition, dict):
        raise WorkflowError("The definition must be an object.")
    trigger = dict(definition.get("trigger") or {})
    ttype = trigger.get("type")
    if ttype not in TRIGGERS:
        raise WorkflowError(f"Unknown trigger {ttype!r}.")
    t_out: dict[str, Any] = {"type": ttype}
    if ttype == "schedule":
        try:
            t_out["schedule"] = sync.check_schedule(trigger.get("schedule") or {})
        except sync.SyncError as exc:
            raise WorkflowError(f"Schedule: {exc.message}") from exc
        if not t_out["schedule"]:
            raise WorkflowError("A scheduled workflow needs a schedule.")
    if ttype == "inputs.ready":
        required = [r for r in (trigger.get("required") or ["register", "master"]) if r]
        if any(r not in INPUTS for r in required) or not required:
            raise WorkflowError(f"Inputs ready: choose from {', '.join(INPUTS)}.")
        t_out["required"] = required
    conditions = []
    for i, c in enumerate(definition.get("conditions") or [], start=1):
        if not isinstance(c, dict) or not c.get("field"):
            raise WorkflowError(f"Condition {i} needs a field.")
        if c.get("op", "eq") not in OPS:
            raise WorkflowError(f"Condition {i}: operator is one of {', '.join(OPS)}.")
        if not re.fullmatch(r"[a-z_][a-z0-9_.]*", str(c["field"])):
            raise WorkflowError(f"Condition {i}: a field is a dotted name such as data.counts.rejected.")
        conditions.append({"field": c["field"], "op": c.get("op", "eq"), "value": c.get("value")})
    actions = definition.get("actions") or []
    if not actions:
        raise WorkflowError("A workflow needs at least one action.")
    if len(actions) > MAX_ACTIONS:
        raise WorkflowError(f"At most {MAX_ACTIONS} actions.")
    a_out = [_check_action(db, entity, a, f"Step {i}", False) for i, a in enumerate(actions, start=1)]
    f_out = [_check_action(db, entity, a, f"Failure step {i}", True)
             for i, a in enumerate(definition.get("on_failure") or [], start=1)]
    return {"trigger": t_out, "conditions": conditions, "actions": a_out, "on_failure": f_out}


def create(db: Session, entity: Entity, actor: User, *, name: str, description: str | None,
           definition: dict[str, Any], environment: str = "production") -> StudioWorkflow:
    wf = StudioWorkflow(org_id=entity.org_id, entity_id=entity.id, name=name.strip()[:100],
                        description=(description or "").strip()[:2000] or None, environment=environment,
                        status="draft", definition=check_definition(db, entity, definition),
                        created_by=actor.id, updated_by=actor.id, has_changes=True)
    db.add(wf)
    db.flush()
    audit.record(db, entity_id=entity.id, user=actor, action="studio.workflow.created",
                 object_type="studio_workflow", object_id=str(wf.id), summary=f"Workflow “{wf.name}” drafted")
    return wf


def update(db: Session, wf: StudioWorkflow, entity: Entity, actor: User, body: dict[str, Any]) -> StudioWorkflow:
    if "definition" in body:
        wf.definition = check_definition(db, entity, body["definition"])
        wf.has_changes = True
        wf.updated_by = actor.id
    if body.get("name"):
        wf.name = str(body["name"]).strip()[:100]
    if "description" in body:
        wf.description = (body.get("description") or "").strip()[:2000] or None
    if "max_runs_per_hour" in body:
        n = int(body["max_runs_per_hour"])
        if not 1 <= n <= 120:
            raise WorkflowError("Runs per hour is 1 to 120.")
        wf.max_runs_per_hour = n
    if "timeout_minutes" in body:
        n = int(body["timeout_minutes"])
        if not 5 <= n <= 24 * 60:
            raise WorkflowError("The workflow timeout is 5 to 1440 minutes.")
        wf.timeout_minutes = n
    audit.record(db, entity_id=entity.id, user=actor, action="studio.workflow.updated",
                 object_type="studio_workflow", object_id=str(wf.id), summary=f"Workflow “{wf.name}” edited")
    return wf


def publish(db: Session, wf: StudioWorkflow, entity: Entity, actor: User) -> StudioWorkflow:
    """Put the working copy in force. Re-checked now: a stream or person may have gone."""
    from app.services import approvals
    from app.services.studio import sync

    approvals.require_independent(db, entity.org_id, "studio_publish_requires_independent_approver",
                                  preparer_id=wf.updated_by, approver_id=actor.id, what="a workflow change")
    definition = check_definition(db, entity, wf.definition)
    wf.definition = definition
    wf.active_definition = definition
    wf.active_version = (wf.active_version or 0) + 1
    wf.has_changes = False
    wf.status = "active"
    wf.published_by = actor.id
    wf.published_at = _now()
    trig = definition["trigger"]
    wf.next_run_at = sync.next_run(trig["schedule"], _now()) if trig["type"] == "schedule" else None
    audit.record(db, entity_id=entity.id, user=actor, action="studio.workflow.published",
                 object_type="studio_workflow", object_id=str(wf.id),
                 summary=f"Workflow “{wf.name}” v{wf.active_version} put in force")
    return wf


def set_enabled(db: Session, wf: StudioWorkflow, entity: Entity, actor: User, enabled: bool) -> StudioWorkflow:
    from app.services.studio import sync

    if enabled and not wf.active_definition:
        raise WorkflowError("Publish the workflow first.", 409)
    wf.status = "active" if enabled else "disabled"
    trig = (wf.active_definition or {}).get("trigger") or {}
    wf.next_run_at = sync.next_run(trig["schedule"], _now()) if enabled and trig.get("type") == "schedule" else None
    audit.record(db, entity_id=entity.id, user=actor, action="studio.workflow." + ("enabled" if enabled else "disabled"),
                 object_type="studio_workflow", object_id=str(wf.id), summary=f"Workflow “{wf.name}” {wf.status}")
    return wf


def get(db: Session, entity: Entity, workflow_id: str) -> StudioWorkflow:
    try:
        wf = db.get(StudioWorkflow, uuid.UUID(workflow_id))
    except ValueError:
        wf = None
    if wf is None or wf.entity_id != entity.id:
        raise WorkflowError("Workflow not found.", 404)
    return wf


# ---------------------------------------------------------------------------
# Conditions and templates
# ---------------------------------------------------------------------------
def dig(obj: Any, path: str) -> Any:
    for part in path.split("."):
        if isinstance(obj, dict) and part in obj:
            obj = obj[part]
        else:
            return None
    return obj


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def condition_holds(cond: dict[str, Any], subject: dict[str, Any]) -> bool:
    got = dig(subject, cond["field"])
    op, want = cond.get("op", "eq"), cond.get("value")
    if op == "present":
        return got not in (None, "", [])
    if op == "absent":
        return got in (None, "", [])
    if op in ("in", "not_in"):
        values = want if isinstance(want, list) else [v.strip() for v in str(want or "").split(",")]
        hit = str(got) in {str(v) for v in values}
        return hit if op == "in" else not hit
    if op in ("gt", "gte", "lt", "lte"):
        a, b = _num(got), _num(want)
        if a is None or b is None:
            return False  # not comparable is not true
        return {"gt": a > b, "gte": a >= b, "lt": a < b, "lte": a <= b}[op]
    same = str(got).lower() == str(want).lower() if got is not None else want in (None, "")
    return same if op == "eq" else not same


def render(template: str, context: dict[str, Any]) -> str:
    """``{{period}}`` and ``{{event.data.counts.rejected}}`` — values only, nothing evaluated."""
    def one(m: re.Match) -> str:
        value = dig(context, m.group(1))
        return "—" if value is None else str(value)[:200]
    return _TEMPLATE.sub(one, template or "")


# ---------------------------------------------------------------------------
# Starting runs
# ---------------------------------------------------------------------------
def _skip(wf: StudioWorkflow, reason: str, key: str | None = None) -> None:
    wf.last_skip = {"at": _now().isoformat(), "reason": reason, "trigger_key": key}


def fire(db: Session, wf: StudioWorkflow, *, trigger_key: str, trigger: dict[str, Any], actor: User,
         actor_label: str, actor_type: str = "user", causation: dict[str, Any] | None = None,
         period: str | None = None, source_trigger: str = "workflow") -> StudioRun | None:
    """Start one run for this trigger, unless it would duplicate, loop or run away. Does not commit."""
    causation = causation or {}
    if causation.get("workflow_id") == str(wf.id):
        _skip(wf, "Its own run caused this event; a workflow never triggers itself.", trigger_key)
        return None
    depth = int(causation.get("depth") or 0)
    if depth >= MAX_DEPTH:
        _skip(wf, f"Chain of {depth} workflows reached; stopped so automation cannot loop.", trigger_key)
        return None
    hour_ago = _now() - timedelta(hours=1)
    recent = (db.query(func.count(StudioRun.id))
              .filter(StudioRun.workflow_id == wf.id, StudioRun.kind == "workflow",
                      StudioRun.created_at >= hour_ago).scalar() or 0)
    if recent >= wf.max_runs_per_hour:
        _skip(wf, f"{recent} runs started in the last hour — its limit. Raise it or find what is triggering it.",
              trigger_key)
        return None
    key = trigger_key[:200]
    seen = (db.query(StudioWorkflowFire.id)
            .filter(StudioWorkflowFire.workflow_id == wf.id, StudioWorkflowFire.trigger_key == key).first())
    if seen is not None:
        return None  # already started for this — a duplicate is the same run, not a second one
    # The unique constraint is the backstop: two workers racing on one key make
    # the second flush fail, its whole batch rolls back, and the retry sees the
    # key here. No savepoint — SQLite's driver does not honour them, and a fire
    # row kept without its run would block the trigger for good.
    fire_row = StudioWorkflowFire(workflow_id=wf.id, trigger_key=key)
    db.add(fire_row)
    db.flush()
    definition = wf.active_definition or {}
    steps = [{"index": i, "type": a["type"], "label": a.get("label") or ACTIONS[a["type"]]["label"],
              "status": "pending", "attempt": 0} for i, a in enumerate(definition.get("actions") or [])]
    run = runs.create(
        db, org_id=wf.org_id, entity_id=wf.entity_id, kind="workflow", object_type=None,
        actor_type=actor_type, actor_user_id=actor.id, actor_label=actor_label, trigger=source_trigger,
        environment=wf.environment, source_system="Workflow", source_object=wf.name,
        batch_id=trigger_key[:100], period_month=date.fromisoformat(period) if period else None,
        options={"definition": definition, "trigger": trigger, "trigger_key": trigger_key,
                 "causation": {"workflow_id": str(wf.id), "depth": depth + 1}},
        versions={"workflow": f"{wf.name} v{wf.active_version}", "workflow_version": wf.active_version},
        workflow_id=wf.id,
    )
    run.result_ref = {"steps": steps, "cursor": 0, "context": {"period": period, "workflow": wf.name}}
    fire_row.run_id = run.id
    wf.last_fired_at = _now()
    return run


def start_manual(db: Session, wf: StudioWorkflow, actor: User, period: str | None) -> StudioRun:
    if wf.status != "active" or not wf.active_definition:
        raise WorkflowError("Only an active workflow can be run. Publish it first.", 409)
    if period:
        try:
            period = date.fromisoformat(period).replace(day=1).isoformat()
        except ValueError as exc:
            raise WorkflowError("The month is a date.") from exc
    run = fire(db, wf, trigger_key=f"manual:{uuid.uuid4().hex}", trigger={"type": "manual", "by": actor.email},
               actor=actor, actor_label=actor.email, period=period, source_trigger="ui")
    if run is None:
        raise WorkflowError((wf.last_skip or {}).get("reason") or "Not started.", 409)
    audit.record(db, entity_id=wf.entity_id, user=actor, action="studio.workflow.run",
                 object_type="studio_workflow", object_id=str(wf.id), summary=f"Workflow “{wf.name}” run by hand")
    return run


def _publisher(db: Session, wf: StudioWorkflow) -> User | None:
    """Automatic runs act as the person who put the workflow in force — and only while they still may."""
    user = db.get(User, wf.published_by) if wf.published_by else None
    entity = db.get(Entity, wf.entity_id)
    if user is None or entity is None:
        return None
    return user if tenancy.effective_entity_role(db, user, entity) in ("owner", "manager") else None


def _inputs(db: Session, entity: Entity, period: date) -> dict[str, Any]:
    from app.models import SalaryRegisterRow
    from app.services import run_inputs

    digests = run_inputs.input_digests(db, entity, period, rows_sha256=None, config={})
    register, n_register = run_inputs._table_digest(  # noqa: SLF001 — the same digest the runs use
        db, SalaryRegisterRow, SalaryRegisterRow.entity_id == entity.id, SalaryRegisterRow.period_month == period)
    counts = {"register": n_register, "master": digests["counts"]["master_records"],
              "attendance": digests["counts"]["attendance_rows"], "ctc": digests["counts"]["ctc_records"],
              "prior_register": digests["counts"]["prior_register_rows"]}
    return {"counts": counts, "digests": {"register": register, **{k: digests[k] for k in
                                                                    ("master", "attendance", "ctc", "prior_register")}}}


def on_event(db: Session, event: Any) -> int:
    """Start the workflows this event triggers. Called by the fan-out, inside its transaction."""
    types = {event.type}
    if event.type == "import.completed" and (event.data or {}).get("status") in ("completed", "partially_completed"):
        types.add("inputs.ready")
    flows = (db.query(StudioWorkflow).filter(StudioWorkflow.entity_id == event.entity_id,
                                             StudioWorkflow.status == "active").all())
    started = 0
    for wf in flows:
        definition = wf.active_definition or {}
        ttype = (definition.get("trigger") or {}).get("type")
        if ttype not in types:
            continue
        subject = {"type": event.type, "data": event.data or {}}
        period = (event.data or {}).get("period_month")
        key = f"event:{event.id}"
        if ttype == "inputs.ready":
            if not period:
                continue
            entity = db.get(Entity, wf.entity_id)
            state = _inputs(db, entity, date.fromisoformat(period))
            required = definition["trigger"].get("required") or ["register", "master"]
            if any(not state["counts"].get(r) for r in required):
                continue  # not ready yet: nothing to record, the next import checks again
            # Once per distinct set of inputs: the same inputs never fire twice.
            key = "ready:" + period + ":" + runs.sha256_of({r: state["digests"].get(r) for r in required})[:32]
            subject["data"] = {**subject["data"], "inputs": state["counts"]}
        if not all(condition_holds(c, subject) for c in definition.get("conditions") or []):
            continue
        actor = _publisher(db, wf)
        if actor is None:
            _skip(wf, "The person who put it in force can no longer manage this company. Publish it again.", key)
            continue
        run = fire(db, wf, trigger_key=key, trigger={"type": ttype, "event_id": str(event.id), "event": event.type,
                                                     "data": subject["data"]},
                   actor=actor, actor_label=f"Workflow “{wf.name}”", causation=event.causation or {},
                   period=period)
        if run is not None:
            run.result_ref = {**run.result_ref, "context": {**run.result_ref["context"], "event": subject}}
            started += 1
    return started


def schedule_due(db: Session, limit: int = 20) -> int:
    from app.services.studio import sync

    now = _now()
    locking = "FOR UPDATE SKIP LOCKED" if db.bind.dialect.name == "postgresql" else ""
    rows = db.execute(text(
        "SELECT id FROM studio_workflows WHERE status = 'active' AND next_run_at IS NOT NULL "
        f"AND next_run_at <= :now ORDER BY next_run_at LIMIT :limit {locking}"  # nosec B608
    ), {"now": now, "limit": limit}).all()
    started = 0
    for (wid,) in rows:
        wf = db.get(StudioWorkflow, wid if isinstance(wid, uuid.UUID) else uuid.UUID(str(wid)))
        if wf is None:
            continue
        slot = _aware(wf.next_run_at)
        trig = (wf.active_definition or {}).get("trigger") or {}
        wf.next_run_at = sync.next_run(trig.get("schedule") or {}, now)
        actor = _publisher(db, wf)
        key = f"schedule:{slot.isoformat() if slot else now.isoformat()}"
        if actor is None:
            _skip(wf, "The person who put it in force can no longer manage this company. Publish it again.", key)
            continue
        if fire(db, wf, trigger_key=key, trigger={"type": "schedule", "slot": key[9:]}, actor=actor,
                actor_label=f"Schedule of workflow “{wf.name}”", source_trigger="schedule") is not None:
            started += 1
    db.commit()
    return started


# ---------------------------------------------------------------------------
# Executing a run
# ---------------------------------------------------------------------------
def _period_for(param: str, context: dict[str, Any]) -> date | None:
    today = india_today().replace(day=1)
    if param == "current_month":
        return today
    if param == "previous_month":
        return (today - timedelta(days=1)).replace(day=1)
    if param == "context":
        return date.fromisoformat(context["period"]) if context.get("period") else None
    return date.fromisoformat(param)


class StepFailed(Exception):
    def __init__(self, message: str, transient: bool = False):
        super().__init__(message)
        self.message = message
        self.transient = transient


class Waiting(Exception):
    """The step started work elsewhere and must be checked again shortly."""


def _recipients(db: Session, entity: Entity, params: dict[str, Any]) -> list[User]:
    roles, ids = set(params.get("roles") or []), set(params.get("user_ids") or [])
    return [u for u, role in _members(db, entity) if role in roles or str(u.id) in ids]


def _link(report: str | None, run: StudioRun, context: dict[str, Any]) -> str:
    if report == "validation_results" and context.get("validation_run_id"):
        return f"/payroll/results?run={context['validation_run_id']}"
    if report == "month_close":
        return "/reconciliation"
    if report == "findings":
        return "/payroll/issues"
    return f"/studio/runs/{run.id}"


def notify(db: Session, entity: Entity, users: list[User], *, title: str, body: str | None, link: str | None,
           severity: str = "info", source_run_id: Any = None) -> int:
    for user in users:
        db.add(StudioNotification(org_id=entity.org_id, entity_id=entity.id, user_id=user.id, severity=severity,
                                  title=title[:200], body=(body or None), link=link, source_run_id=source_run_id))
    return len(users)


def _execute(db: Session, run: StudioRun, entity: Entity, step: dict[str, Any], action: dict[str, Any],
             context: dict[str, Any]) -> str:
    """Run or check one step. Returns completed | warning; raises StepFailed or Waiting."""
    from app.models import FindingState, ValidationJob
    from app.services import issues, validation_jobs
    from app.services.studio import events, sync

    kind, params = action["type"], action.get("params") or {}
    causation = (run.options or {}).get("causation") or {}
    actor = db.get(User, run.actor_user_id)
    ref = step.setdefault("ref", {})

    if kind == "sync":
        if not ref.get("run_id"):
            stream = db.get(StudioStream, uuid.UUID(params["stream_id"]))
            if stream is None:
                raise StepFailed("The stream no longer exists.")
            try:
                child = sync.start(db, entity, stream, actor=actor, actor_label=f"Workflow “{context.get('workflow')}”",
                                   trigger="workflow", causation=causation)
            except sync.SyncError as exc:
                raise StepFailed(exc.message) from exc
            ref["run_id"] = str(child.id)
            raise Waiting()
        child = db.get(StudioRun, uuid.UUID(ref["run_id"]))
        if child is None:
            raise StepFailed("The sync run disappeared.")
        if child.status in ("queued", "running"):
            raise Waiting()
        context["last_run_id"] = str(child.id)
        context["counts"] = child.counts or {}
        if child.period_month or child.effective_from:
            context["period"] = context.get("period") or (child.period_month or child.effective_from).isoformat()
        step["message"] = f"{child.status.replace('_', ' ')}: {(child.counts or {}).get('received', 0)} received, " \
                          f"{(child.counts or {}).get('rejected', 0)} rejected"
        if child.status == "completed":
            return "completed"
        if child.status == "partially_completed":
            if params.get("fail_on_rejections"):
                raise StepFailed(f"The sync rejected {(child.counts or {}).get('rejected', 0)} record(s).")
            return "warning"
        raise StepFailed(f"The sync {child.status}: {child.error_message or ''}".strip())

    if kind == "check_readiness":
        period = _period_for(params["period"], context)
        if period is None:
            raise StepFailed("No month to check: the trigger named none and the step does not choose one.")
        state = _inputs(db, entity, period)
        missing = [r for r in params["required"] if not state["counts"].get(r)]
        context["period"] = period.isoformat()
        context["inputs"] = state["counts"]
        if missing:
            raise StepFailed(f"{period:%b %Y} is not ready: no {', '.join(m.replace('_', ' ') for m in missing)}.")
        step["message"] = f"{period:%b %Y}: " + ", ".join(f"{r.replace('_', ' ')} {state['counts'][r]}"
                                                         for r in params["required"])
        return "completed"

    if kind == "start_validation":
        if not ref.get("job_id"):
            period = _period_for(params["period"], context)
            if period is None:
                raise StepFailed("No month to validate: the trigger named none and the step does not choose one.")
            try:
                job, _ = validation_jobs.submit_for_period(db, entity_id=entity.id, user_id=actor.id,
                                                           period_month=period, params={"causation": causation})
            except validation_jobs.SubmitError as exc:
                raise StepFailed(exc.detail if hasattr(exc, "detail") else str(exc)) from exc
            ref["job_id"] = str(job.id)
            context["period"] = period.isoformat()
            context["validation_job_id"] = str(job.id)
            raise Waiting()
        job = db.get(ValidationJob, uuid.UUID(ref["job_id"]))
        if job is None:
            raise StepFailed("The validation job disappeared.")
        if job.state not in ("succeeded", "failed", "cancelled"):
            raise Waiting()
        if job.state != "succeeded":
            raise StepFailed(f"Validation {job.state}: {job.error_message or job.error_code or ''}".strip())
        context["validation_run_id"] = str(job.run_id) if job.run_id else None
        run.validation_job_id = job.id
        run.validation_run_id = job.run_id
        from app.models import FindingRecord

        by = dict(db.query(FindingRecord.severity, func.count(FindingRecord.id))
                  .filter(FindingRecord.run_id == job.run_id, FindingRecord.status == "FAIL")
                  .group_by(FindingRecord.severity).all()) if job.run_id else {}
        context["findings"] = {k.lower(): int(v) for k, v in by.items()}
        critical = int(by.get("CRITICAL", 0))
        step["message"] = "Validated: " + (", ".join(f"{v} {k.lower()}" for k, v in sorted(by.items())) or "no findings")
        if critical and params.get("fail_on_critical"):
            raise StepFailed(f"Validation found {critical} critical finding(s).")
        return "completed"

    if kind == "assign_findings":
        period = _period_for(params["period"], context)
        q = db.query(FindingState).filter(FindingState.entity_id == entity.id,
                                          FindingState.state.in_(issues.ACTIVE_STATES))
        if period is not None:
            q = q.filter(FindingState.last_seen_period == period)
        if params.get("severities"):
            q = q.filter(FindingState.severity.in_(params["severities"]))
        if params.get("only_unassigned", True):
            q = q.filter(FindingState.owner_user_id.is_(None))
        due = india_today() + timedelta(days=int(params.get("due_in_days") or 0)) if params.get("due_in_days") else None
        n = 0
        try:
            for state in q.all():
                issues.assign(db, entity=entity, state=state, actor=actor,
                              owner_user_id=uuid.UUID(params["owner_user_id"]), due_date=due)
                n += 1
        except issues.IssueError as exc:
            raise StepFailed(str(exc)) from exc
        owner = db.get(User, uuid.UUID(params["owner_user_id"]))
        step["message"] = f"{n} finding(s) assigned to {owner.email if owner else 'the owner'}"
        return "completed"

    if kind in ("notify", "report"):
        users = _recipients(db, entity, params)
        link = _link(params.get("report") if kind == "report" else ("run" if not context.get("validation_run_id")
                                                                     else "validation_results"), run, context)
        n = notify(db, entity, users, title=render(params["title"], context), body=render(params.get("body"), context),
                   link=link, severity=params.get("severity", "info"), source_run_id=run.id)
        step["message"] = f"{n} person(s) notified" + ("" if n else " — nobody matched; check the recipients")
        return "completed" if n else "warning"

    if kind == "webhook":
        hook = db.get(StudioWebhook, uuid.UUID(params["webhook_id"]))
        if hook is None or hook.status != "active":
            raise StepFailed("The webhook is missing or disabled.")
        event = events.emit(db, org_id=entity.org_id, entity_id=entity.id, type="workflow.message",
                            data={"workflow_id": str(run.workflow_id), "workflow_run_id": str(run.id),
                                  "period_month": context.get("period"),
                                  "validation_run_id": context.get("validation_run_id"),
                                  "message": render(params.get("message"), context)[:200] or None},
                            causation=causation, only_webhook_id=hook.id)
        db.flush()
        step["message"] = f"Event {str(event.id)[:8]} queued for {hook.name}"
        ref["event_id"] = str(event.id)
        return "completed"

    raise StepFailed(f"Unknown action {kind}.")


def _finish(db: Session, run: StudioRun, status: str, message: str | None = None, category: str | None = None) -> None:
    from app.services.studio import events

    runs.finish(db, run, status, error_category=category, error_message=message)
    events.emit(db, org_id=run.org_id, entity_id=run.entity_id, type="workflow.finished",
                data={"workflow_id": str(run.workflow_id), "run_id": str(run.id), "status": status},
                causation=(run.options or {}).get("causation") or {})


def _failure_branch(db: Session, run: StudioRun, entity: Entity, context: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for i, action in enumerate(((run.options or {}).get("definition") or {}).get("on_failure") or []):
        step = {"index": i, "type": action["type"], "label": action.get("label") or ACTIONS[action["type"]]["label"],
                "branch": "failure", "started_at": _now().isoformat()}
        try:
            step["status"] = _execute(db, run, entity, step, action, context)
        except (StepFailed, Waiting) as exc:
            step["status"] = "failed"
            step["message"] = getattr(exc, "message", "Could not run in the failure branch.")
        step["finished_at"] = _now().isoformat()
        out.append(step)
    return out


def _requeue(run: StudioRun, seconds: int, stage: str) -> None:
    run.status = "queued"
    run.stage = stage[:48]
    run.heartbeat_at = None
    run.queued_at = _now() + timedelta(seconds=seconds)
    # Waiting is not an attempt: the claim counted one, give it back.
    run.attempts = max((run.attempts or 1) - 1, 0)


def process(db: Session, run: StudioRun) -> StudioRun:
    """Advance a workflow run as far as it can go now. Commits."""
    from app.models import ValidationJob
    from app.services import validation_jobs

    entity = db.get(Entity, run.entity_id)
    state = dict(run.result_ref or {})
    steps: list[dict[str, Any]] = [dict(s) for s in state.get("steps") or []]
    context: dict[str, Any] = dict(state.get("context") or {})
    cursor = int(state.get("cursor") or 0)
    actions = ((run.options or {}).get("definition") or {}).get("actions") or []

    def save() -> None:
        run.result_ref = {**(run.result_ref or {}), "steps": steps, "cursor": cursor, "context": context}

    if run.cancel_requested_at is not None:
        for s in steps:
            if s.get("status") in ("waiting", "running"):
                ref = s.get("ref") or {}
                if ref.get("run_id"):
                    child = db.get(StudioRun, uuid.UUID(ref["run_id"]))
                    if child is not None:
                        runs.request_cancel(db, child)
                if ref.get("job_id"):
                    job = db.get(ValidationJob, uuid.UUID(ref["job_id"]))
                    if job is not None:
                        validation_jobs.request_cancel(db, job, run.actor_user_id)
                s["status"] = "cancelled"
        save()
        _finish(db, run, "cancelled", "Cancelled by a person.", "cancelled")
        db.commit()
        return run

    started = _aware(run.started_at) or _now()
    timeout = int(((run.options or {}).get("definition") or {}).get("timeout_minutes") or 0)
    from app.models import StudioWorkflow as _Wf

    wf = db.get(_Wf, run.workflow_id) if run.workflow_id else None
    overall = timedelta(minutes=timeout or (wf.timeout_minutes if wf else 120))

    while cursor < len(steps):
        step, action = steps[cursor], actions[cursor]
        step_started = datetime.fromisoformat(step["started_at"]) if step.get("started_at") else None
        if _now() - started > overall:
            step["status"] = "failed"
            step["message"] = f"The workflow ran longer than {int(overall.total_seconds() // 60)} minutes."
            return _fail(db, run, entity, steps, cursor, context, step["message"])
        if step_started and _now() - step_started > timedelta(minutes=action.get("timeout_minutes", 60)):
            step["status"] = "failed"
            step["message"] = f"Timed out after {action.get('timeout_minutes', 60)} minutes."
            return _fail(db, run, entity, steps, cursor, context, f"Step {cursor + 1} ({step['label']}): timed out.")
        if not step.get("started_at"):
            step["started_at"] = _now().isoformat()
            step["attempt"] = int(step.get("attempt") or 0) + 1
        step["status"] = "running"
        try:
            outcome = _execute(db, run, entity, step, action, context)
        except Waiting:
            step["status"] = "waiting"
            save()
            _requeue(run, WAIT_SECONDS, f"waiting: step {cursor + 1}")
            db.commit()
            return run
        except StepFailed as exc:
            step["message"] = exc.message
            if step["attempt"] <= int(action.get("retries") or 0):
                # Retry this step after a pause: a fresh start, the same step.
                step["status"] = "pending"
                step.pop("started_at", None)
                step["ref"] = {}
                save()
                _requeue(run, STEP_BACKOFF_SECONDS * (2 ** (step["attempt"] - 1)), f"retrying step {cursor + 1}")
                db.commit()
                return run
            step["status"] = "failed"
            step["finished_at"] = _now().isoformat()
            return _fail(db, run, entity, steps, cursor, context, f"Step {cursor + 1} ({step['label']}): {exc.message}")
        step["status"] = outcome
        step["finished_at"] = _now().isoformat()
        cursor += 1
        save()
        db.flush()

    for s in steps[cursor:]:
        s["status"] = "skipped"
    save()
    status = "partially_completed" if any(s.get("status") == "warning" for s in steps) else "completed"
    _finish(db, run, status)
    db.commit()
    return run


def _fail(db: Session, run: StudioRun, entity: Entity, steps: list[dict[str, Any]], cursor: int,
          context: dict[str, Any], message: str) -> StudioRun:
    for s in steps[cursor + 1:]:
        s["status"] = "skipped"
    failure = _failure_branch(db, run, entity, context)
    run.result_ref = {**(run.result_ref or {}), "steps": steps, "cursor": cursor, "context": context,
                      "failure_branch": failure}
    _finish(db, run, "failed", message, "workflow")
    run.recommended_action = ("Open the failed step: it links to the run or validation it started. Fix the cause, "
                              "then run the workflow again.")
    db.commit()
    return run


def cancel(db: Session, run: StudioRun) -> StudioRun:
    """Stop a workflow run and whatever it is waiting on."""
    if run.status not in ("queued", "running"):
        raise WorkflowError("The run has already finished.", 409)
    run.cancel_requested_at = _now()
    if run.status == "queued":
        # Not in a worker right now: finish it here, stopping any child.
        run.status = "running"
        process(db, run)
    return run


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------
def dry_run(db: Session, entity: Entity, definition: dict[str, Any], sample: dict[str, Any] | None,
            period: str | None) -> dict[str, Any]:
    """What would happen, with nothing done: the trigger, each condition, each step resolved."""
    definition = check_definition(db, entity, definition)
    subject = {"type": definition["trigger"]["type"], "data": dict((sample or {}).get("data") or sample or {})}
    context = {"period": period or subject["data"].get("period_month"), "workflow": "(dry run)", "event": subject}
    conditions = [{**c, "actual": dig(subject, c["field"]), "holds": condition_holds(c, subject)}
                  for c in definition["conditions"]]
    plan = []
    for i, action in enumerate(definition["actions"], start=1):
        params = action.get("params") or {}
        line = {"step": i, "type": action["type"], "label": action.get("label") or ACTIONS[action["type"]]["label"]}
        if "period" in params:
            p = _period_for(params["period"], context)
            line["period"] = p.isoformat() if p else None
            if p is None:
                line["warning"] = "No month: the trigger would have to name one."
        if action["type"] == "check_readiness" and line.get("period"):
            state = _inputs(db, entity, date.fromisoformat(line["period"]))
            missing = [r for r in params["required"] if not state["counts"].get(r)]
            line["now"] = state["counts"]
            if missing:
                line["warning"] = "Would fail now: no " + ", ".join(missing)
        if action["type"] in ("notify", "report"):
            line["recipients"] = [u.email for u in _recipients(db, entity, params)]
            line["title"] = render(params["title"], context)
        if action["type"] == "sync":
            stream = db.get(StudioStream, uuid.UUID(params["stream_id"]))
            line["stream"] = stream.name if stream else None
        if action["type"] == "assign_findings":
            owner = db.get(User, uuid.UUID(params["owner_user_id"]))
            line["owner"] = owner.email if owner else None
        plan.append(line)
    return {"would_run": all(c["holds"] for c in conditions), "conditions": conditions, "steps": plan,
            "failure_branch": [a["type"] for a in definition["on_failure"]]}


# ---------------------------------------------------------------------------
# Describing
# ---------------------------------------------------------------------------
def describe(db: Session, wf: StudioWorkflow) -> dict[str, Any]:
    last = (db.query(StudioRun).filter(StudioRun.workflow_id == wf.id, StudioRun.kind == "workflow")
            .order_by(StudioRun.created_at.desc()).first())
    return {
        "id": str(wf.id), "name": wf.name, "description": wf.description, "environment": wf.environment,
        "status": wf.status, "definition": wf.definition, "active_definition": wf.active_definition,
        "active_version": wf.active_version, "has_changes": wf.has_changes,
        "max_runs_per_hour": wf.max_runs_per_hour, "timeout_minutes": wf.timeout_minutes,
        "next_run_at": _aware(wf.next_run_at).isoformat() if wf.next_run_at else None,
        "last_fired_at": _aware(wf.last_fired_at).isoformat() if wf.last_fired_at else None,
        "last_skip": wf.last_skip,
        "last_run": {"id": str(last.id), "status": last.status,
                     "at": _aware(last.created_at).isoformat() if last.created_at else None} if last else None,
        "published_at": _aware(wf.published_at).isoformat() if wf.published_at else None,
        "updated_at": _aware(wf.updated_at).isoformat() if wf.updated_at else None,
    }


def catalogue() -> dict[str, Any]:
    return {"triggers": TRIGGERS, "actions": {k: {"label": v["label"], "help": v["help"],
                                                  "failure_branch": bool(v.get("failure_branch"))}
                                              for k, v in ACTIONS.items()},
            "not_available": FORBIDDEN_ACTIONS, "ops": OPS, "severities": SEVERITIES, "inputs": INPUTS, "reports": REPORTS,
            "roles": NOTIFY_ROLES}
