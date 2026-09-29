"""
Environments and releases.

**Environments are companies.** A company is marked development, test or
production (the default). A test company holds synthetic data and its own
connections; configuration is built and tried there, then carried to
production by a release. Because payroll data, credentials and webhook secrets
live with a company, keeping environments apart needs no second copy of the
product — only a rule about what may cross.

**What a release carries: configuration, by name.** Published mapping versions
(by key) and workflow definitions (by name). Never records, registers, runs,
findings, connections, credentials or webhook secrets: a connection and a
webhook are set up in each environment on purpose, because they are where the
secrets live. A workflow's references to streams, webhooks and people are
re-resolved by name in the target; one that cannot be resolved blocks the
release.

**The path:** draft → submitted (the impact preview must have no blocking
problem) → approved or rejected by an owner or manager *other than the
author* → promoted, in one transaction, by an owner or manager of the target.
Promotion only adds: a mapping gains a new published version, a workflow a new
version; nothing already published is edited, so every earlier run still
names exactly what it used. What each item replaced is recorded, and a
**rollback is another release** that restores it, approved the same way.
"""
from __future__ import annotations

import copy
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models import (
    Entity,
    StudioCompanyEnvironment,
    StudioConnection,
    StudioMapping,
    StudioRelease,
    StudioRun,
    StudioStream,
    StudioWebhook,
    StudioWorkflow,
    User,
)
from app.services import audit, tenancy
from app.services.studio import mapping as mapping_engine
from app.services.studio import profiles, workflows

RANK = {"development": 0, "test": 1, "production": 2}
MANAGERS = ("owner", "manager")


class ReleaseError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Environments
# ---------------------------------------------------------------------------
def environment_of(db: Session, entity_id: Any) -> str:
    row = db.get(StudioCompanyEnvironment, entity_id)
    return row.environment if row else "production"


def set_environment(db: Session, entity: Entity, actor: User, environment: str) -> str:
    if environment not in RANK:
        raise ReleaseError("The environment is development, test or production.")
    row = db.get(StudioCompanyEnvironment, entity.id)
    before = row.environment if row else "production"
    if row is None:
        row = StudioCompanyEnvironment(entity_id=entity.id, org_id=entity.org_id)
        db.add(row)
    row.environment = environment
    row.set_by = actor.id
    audit.record(db, entity_id=entity.id, user=actor, action="studio.environment.set", object_type="entity",
                 object_id=str(entity.id), summary=f"Marked this company {environment} (was {before})")
    return environment


def _manages(db: Session, user: User, entity: Entity) -> bool:
    return tenancy.effective_entity_role(db, user, entity) in MANAGERS


def _entity(db: Session, entity_id: Any) -> Entity:
    try:
        entity = db.get(Entity, uuid.UUID(str(entity_id)))
    except ValueError:
        entity = None
    if entity is None:
        raise ReleaseError("Company not found.", 404)
    return entity


# ---------------------------------------------------------------------------
# What can be released
# ---------------------------------------------------------------------------
def candidates(db: Session, source: Entity) -> dict[str, Any]:
    keys = sorted({k for (k,) in db.query(StudioMapping.key).filter(StudioMapping.entity_id == source.id).all()})
    maps = []
    for key in keys:
        current = profiles.in_force(db, source.id, key)
        if current is not None:
            maps.append({"name": key, "label": current.name, "version": current.version,
                         "object_type": current.object_type})
    flows = [{"name": w.name, "version": w.active_version, "status": w.status}
             for w in db.query(StudioWorkflow).filter(StudioWorkflow.entity_id == source.id,
                                                      StudioWorkflow.active_version > 0)
             .order_by(StudioWorkflow.name).all()]
    return {"mappings": maps, "workflows": flows}


def _snapshot_mapping(db: Session, source: Entity, name: str, version: int | None) -> dict[str, Any]:
    rows = profiles.versions(db, source.id, name)
    if version is not None:
        row = next((r for r in rows if r.version == version and r.status in ("published", "retired")), None)
    else:
        row = profiles.in_force(db, source.id, name)
    if row is None:
        raise ReleaseError(f"Mapping {name} has no published version to release.")
    return {"kind": "mapping", "name": row.key, "source_version": row.version, "source_id": str(row.id),
            "snapshot": {"key": row.key, "name": row.name, "object_type": row.object_type,
                         "spec": copy.deepcopy(row.spec),
                         "effective_from": row.effective_from.isoformat() if row.effective_from else None}}


def _references(db: Session, definition: dict[str, Any]) -> dict[str, Any]:
    """Every id a definition names, as a name the target can resolve."""
    refs: dict[str, Any] = {"streams": {}, "webhooks": {}, "users": {}}
    for action in (definition.get("actions") or []) + (definition.get("on_failure") or []):
        p = action.get("params") or {}
        if p.get("stream_id"):
            s = db.get(StudioStream, uuid.UUID(p["stream_id"]))
            c = db.get(StudioConnection, s.connection_id) if s else None
            refs["streams"][p["stream_id"]] = {"connection": c.name if c else None, "stream": s.name if s else None}
        if p.get("webhook_id"):
            h = db.get(StudioWebhook, uuid.UUID(p["webhook_id"]))
            refs["webhooks"][p["webhook_id"]] = h.name if h else None
        for uid in [p.get("owner_user_id")] + list(p.get("user_ids") or []):
            if uid:
                u = db.get(User, uuid.UUID(str(uid)))
                refs["users"][str(uid)] = u.email if u else None
    return refs


def _snapshot_workflow(db: Session, source: Entity, name: str) -> dict[str, Any]:
    wf = (db.query(StudioWorkflow).filter(StudioWorkflow.entity_id == source.id, StudioWorkflow.name == name)
          .first())
    if wf is None or not wf.active_definition:
        raise ReleaseError(f"Workflow {name} has no published version to release.")
    return {"kind": "workflow", "name": wf.name, "source_version": wf.active_version, "source_id": str(wf.id),
            "snapshot": {"name": wf.name, "description": wf.description,
                         "definition": copy.deepcopy(wf.active_definition),
                         "max_runs_per_hour": wf.max_runs_per_hour, "timeout_minutes": wf.timeout_minutes,
                         "references": _references(db, wf.active_definition)}}


# ---------------------------------------------------------------------------
# Impact
# ---------------------------------------------------------------------------
def _resolve(db: Session, target: Entity, definition: dict[str, Any], refs: dict[str, Any]) -> tuple[dict, list[str]]:
    """The definition with the target's own ids, and what could not be found there."""
    out = copy.deepcopy(definition)
    problems: list[str] = []
    streams = {(c.name, s.name): s for s, c in
               db.query(StudioStream, StudioConnection).join(StudioConnection, StudioConnection.id == StudioStream.connection_id)
               .filter(StudioStream.entity_id == target.id).all()}
    hooks = {h.name: h for h in db.query(StudioWebhook).filter(StudioWebhook.entity_id == target.id).all()}
    people = {u.email: u for u, _ in workflows._members(db, target)}  # noqa: SLF001 — same membership rule
    for action in (out.get("actions") or []) + (out.get("on_failure") or []):
        p = action.get("params") or {}
        if p.get("stream_id"):
            ref = refs["streams"].get(p["stream_id"]) or {}
            hit = streams.get((ref.get("connection"), ref.get("stream")))
            if hit is None:
                problems.append(f"No stream “{ref.get('stream')}” on a connection named “{ref.get('connection')}” here. "
                                "Create it (with this environment's own credentials) first.")
            else:
                p["stream_id"] = str(hit.id)
        if p.get("webhook_id"):
            name = refs["webhooks"].get(p["webhook_id"])
            hit = hooks.get(name)
            if hit is None:
                problems.append(f"No webhook named “{name}” here. Create it (with its own secret) first.")
            else:
                p["webhook_id"] = str(hit.id)
        if p.get("owner_user_id"):
            email = refs["users"].get(str(p["owner_user_id"]))
            if email not in people:
                problems.append(f"{email or 'The assignee'} cannot work findings here.")
            else:
                p["owner_user_id"] = str(people[email].id)
        if p.get("user_ids"):
            mapped = []
            for uid in p["user_ids"]:
                email = refs["users"].get(str(uid))
                if email in people:
                    mapped.append(str(people[email].id))
                else:
                    problems.append(f"{email or 'A recipient'} has no access here.")
            p["user_ids"] = mapped
    return out, problems


def _tested(db: Session, source_id: Any, item: dict[str, Any]) -> dict[str, Any] | None:
    """The latest run in the source company that used exactly this version — the evidence it was tried."""
    q = db.query(StudioRun).filter(StudioRun.entity_id == source_id).order_by(StudioRun.created_at.desc())
    for run in q.limit(500).all():
        v = run.versions or {}
        if item["kind"] == "mapping" and v.get("mapping_id") == item["source_id"]:
            return {"run_id": str(run.id), "status": run.status, "counts": run.counts or {}}
        if item["kind"] == "workflow" and str(run.workflow_id) == item["source_id"] \
                and v.get("workflow_version") == item["source_version"]:
            return {"run_id": str(run.id), "status": run.status}
    return None


def impact(db: Session, release: StudioRelease) -> dict[str, Any]:
    target = db.get(Entity, release.target_entity_id)
    out = []
    for item in release.items or []:
        line: dict[str, Any] = {"kind": item["kind"], "name": item["name"], "source_version": item["source_version"],
                                "blocking": [], "warnings": []}
        snap = item["snapshot"]
        if item["kind"] == "mapping":
            current = profiles.in_force(db, target.id, item["name"])
            existing = profiles.versions(db, target.id, item["name"])
            line["target_version"] = current.version if current else None
            if existing and existing[0].object_type != snap["object_type"]:
                line["blocking"].append(f"{item['name']} maps {existing[0].object_type} here, not {snap['object_type']}.")
            try:
                profiles._check(db, target, snap["object_type"], snap["spec"])  # noqa: SLF001 — the target's own rules
            except (mapping_engine.SpecError, profiles.ProfileError) as exc:
                line["blocking"].append(f"Not valid here: {exc}")
            changes = mapping_engine.compare(current.spec, snap["spec"]) if current else None
            line["change"] = "create" if current is None else ("unchanged" if not changes else "update")
            line["diff"] = changes or []
        elif item["kind"] == "workflow":
            resolved, problems = _resolve(db, target, snap["definition"], snap.get("references") or {})
            if not item.get("resolved"):
                line["blocking"].extend(problems)
            current = (db.query(StudioWorkflow)
                       .filter(StudioWorkflow.entity_id == target.id, StudioWorkflow.name == item["name"]).first())
            line["target_version"] = current.active_version if current else None
            before = (current.active_definition or {}) if current else None
            after = snap["definition"] if item.get("resolved") else resolved
            if current is None:
                line["change"] = "create"
                line["warnings"].append("Created disabled: a person enables it here after checking it.")
            else:
                line["change"] = "unchanged" if before == after else "update"
            line["diff"] = _flow_diff(before, after)
        elif item["kind"] == "mapping_retire":
            line["change"] = "retire"
            line["diff"] = []
        elif item["kind"] == "workflow_disable":
            line["change"] = "disable"
            line["diff"] = []
        if item["kind"] in ("mapping", "workflow") and not release.rollback_of_id:
            evidence = _tested(db, release.source_entity_id, item)
            line["tested"] = evidence
            if evidence is None:
                line["warnings"].append("Never run in the source company with this version. Try it there on synthetic data first.")
            elif evidence["status"] == "failed":
                line["warnings"].append("Its last run in the source company failed.")
        out.append(line)
    return {"items": out, "blocking": sum(len(i["blocking"]) for i in out),
            "warnings": sum(len(i["warnings"]) for i in out)}


def _flow_diff(before: dict | None, after: dict) -> list[dict[str, Any]]:
    if before is None:
        return [{"part": "workflow", "change": "new"}]
    diff = []
    if before.get("trigger") != after.get("trigger"):
        diff.append({"part": "trigger", "before": before.get("trigger"), "after": after.get("trigger")})
    if before.get("conditions") != after.get("conditions"):
        diff.append({"part": "conditions", "before": before.get("conditions"), "after": after.get("conditions")})
    b, a = before.get("actions") or [], after.get("actions") or []
    for i in range(max(len(b), len(a))):
        if i >= len(b):
            diff.append({"part": f"step {i + 1}", "change": "added", "after": a[i]["type"]})
        elif i >= len(a):
            diff.append({"part": f"step {i + 1}", "change": "removed", "before": b[i]["type"]})
        elif b[i] != a[i]:
            diff.append({"part": f"step {i + 1}", "change": "changed", "before": b[i]["type"], "after": a[i]["type"]})
    if before.get("on_failure") != after.get("on_failure"):
        diff.append({"part": "failure branch", "change": "changed"})
    return diff


# ---------------------------------------------------------------------------
# The path
# ---------------------------------------------------------------------------
def create(db: Session, actor: User, source: Entity, target: Entity, *, title: str, notes: str | None,
           items: list[dict[str, Any]]) -> StudioRelease:
    if source.org_id != target.org_id:
        raise ReleaseError("Company not found.", 404)
    if source.id == target.id:
        raise ReleaseError("A release goes from one company to another.")
    if not (_manages(db, actor, source) and _manages(db, actor, target)):
        raise ReleaseError("You must be an owner or manager of both companies.", 403)
    src_env, dst_env = environment_of(db, source.id), environment_of(db, target.id)
    if RANK[src_env] >= RANK[dst_env]:
        raise ReleaseError(f"Releases go upward: {source.name} is {src_env} and {target.name} is {dst_env}. "
                           "Mark the source company development or test first.")
    if not items:
        raise ReleaseError("Choose at least one mapping or workflow.")
    snaps, seen = [], set()
    for it in items:
        key = (it.get("kind"), it.get("name"))
        if key in seen:
            continue
        seen.add(key)
        if it.get("kind") == "mapping":
            snaps.append(_snapshot_mapping(db, source, str(it.get("name")), it.get("version")))
        elif it.get("kind") == "workflow":
            snaps.append(_snapshot_workflow(db, source, str(it.get("name"))))
        else:
            raise ReleaseError("A release carries mappings and workflows only — never data, connections or secrets.")
    release = StudioRelease(org_id=source.org_id, source_entity_id=source.id, target_entity_id=target.id,
                            title=title.strip()[:200], notes=(notes or "").strip() or None, status="draft",
                            items=snaps, created_by=actor.id)
    db.add(release)
    db.flush()
    for e in (source, target):
        audit.record(db, entity_id=e.id, user=actor, action="studio.release.drafted", object_type="studio_release",
                     object_id=str(release.id),
                     summary=f"Release “{release.title}” drafted: {source.name} → {target.name}, {len(snaps)} item(s)")
    return release


def get(db: Session, user: User, release_id: str) -> StudioRelease:
    try:
        release = db.get(StudioRelease, uuid.UUID(release_id))
    except ValueError:
        release = None
    if release is None:
        raise ReleaseError("Release not found.", 404)
    reachable = {e.id for e in tenancy.accessible_entities(db, user)}
    if release.source_entity_id not in reachable or release.target_entity_id not in reachable:
        raise ReleaseError("Release not found.", 404)
    return release


def submit(db: Session, release: StudioRelease, actor: User) -> StudioRelease:
    if release.status != "draft":
        raise ReleaseError("Only a draft can be submitted.", 409)
    state = impact(db, release)
    if state["blocking"]:
        raise ReleaseError(f"{state['blocking']} blocking problem(s) in the impact preview. Fix them first.", 409)
    release.status = "awaiting_approval"
    release.submitted_at = _now()
    audit.record(db, entity_id=release.target_entity_id, user=actor, action="studio.release.submitted",
                 object_type="studio_release", object_id=str(release.id), summary=f"Release “{release.title}” submitted")
    return release


def decide(db: Session, release: StudioRelease, actor: User, approve: bool, note: str | None) -> StudioRelease:
    if release.status != "awaiting_approval":
        raise ReleaseError("Only a submitted release can be approved or rejected.", 409)
    target = db.get(Entity, release.target_entity_id)
    if not _manages(db, actor, target):
        raise ReleaseError("Only an owner or manager of the target company can decide.", 403)
    if actor.id == release.created_by:
        raise ReleaseError("A release is approved by someone other than its author. Ask another owner or manager.", 409)
    if not approve and not (note or "").strip():
        raise ReleaseError("Say why it is rejected.")
    release.status = "approved" if approve else "rejected"
    release.decided_by = actor.id
    release.decided_at = _now()
    release.decision_note = (note or "").strip() or None
    audit.record(db, entity_id=target.id, user=actor, action="studio.release." + ("approved" if approve else "rejected"),
                 object_type="studio_release", object_id=str(release.id),
                 summary=f"Release “{release.title}” {'approved' if approve else 'rejected'}"
                 + (f": {release.decision_note}" if release.decision_note else ""))
    return release


def promote(db: Session, release: StudioRelease, actor: User) -> StudioRelease:
    """Apply an approved release to its target, all or nothing. Does not commit."""
    if release.status != "approved":
        raise ReleaseError("Only an approved release can be promoted.", 409)
    target = db.get(Entity, release.target_entity_id)
    if not _manages(db, actor, target):
        raise ReleaseError("Only an owner or manager of the target company can promote.", 403)
    state = impact(db, release)  # again: the target may have changed since approval
    if state["blocking"]:
        raise ReleaseError("The target has changed since approval and the release no longer applies: "
                           + "; ".join(b for i in state["items"] for b in i["blocking"]), 409)
    replaced, result = [], []
    reason = f"Release “{release.title}”"
    for item, line in zip(release.items, state["items"], strict=True):
        snap = item["snapshot"]
        if item["kind"] == "mapping":
            current = profiles.in_force(db, target.id, item["name"])
            replaced.append({"kind": "mapping", "name": item["name"],
                             "previous": {"version": current.version, "id": str(current.id),
                                          "spec": copy.deepcopy(current.spec), "name": current.name,
                                          "object_type": current.object_type,
                                          "effective_from": current.effective_from.isoformat()
                                          if current.effective_from else None} if current else None})
            if line["change"] == "unchanged":
                result.append({"kind": "mapping", "name": item["name"], "outcome": "unchanged",
                               "version": current.version})
                continue
            from datetime import date as _date

            row = profiles.create(db, target, actor, key=snap["key"], name=snap["name"], object_type=snap["object_type"],
                                  spec=snap["spec"], change_reason=reason,
                                  effective_from=_date.fromisoformat(snap["effective_from"]) if snap.get("effective_from") else None)
            # The release's independent approval is this version's approval.
            row.status = "published"
            row.published_by = actor.id
            row.published_at = _now()
            result.append({"kind": "mapping", "name": item["name"], "outcome": "published", "version": row.version,
                           "id": str(row.id)})
        elif item["kind"] == "mapping_retire":
            row = db.get(StudioMapping, uuid.UUID(item["target_id"]))
            if row is not None and row.status == "published":
                row.status = "retired"
                row.retired_at = _now()
            result.append({"kind": "mapping", "name": item["name"], "outcome": "retired"})
        elif item["kind"] == "workflow":
            current = (db.query(StudioWorkflow)
                       .filter(StudioWorkflow.entity_id == target.id, StudioWorkflow.name == item["name"]).first())
            definition = snap["definition"] if item.get("resolved") else \
                _resolve(db, target, snap["definition"], snap.get("references") or {})[0]
            definition = workflows.check_definition(db, target, definition)
            replaced.append({"kind": "workflow", "name": item["name"],
                             "previous": {"id": str(current.id), "version": current.active_version,
                                          "definition": copy.deepcopy(current.active_definition),
                                          "status": current.status} if current and current.active_definition else None})
            if current is not None and line["change"] == "unchanged":
                result.append({"kind": "workflow", "name": item["name"], "outcome": "unchanged",
                               "version": current.active_version})
                continue
            if current is None:
                current = StudioWorkflow(org_id=target.org_id, entity_id=target.id, name=snap["name"],
                                         description=snap.get("description"), environment=environment_of(db, target.id),
                                         status="disabled", definition=definition, created_by=actor.id,
                                         max_runs_per_hour=snap.get("max_runs_per_hour", 20),
                                         timeout_minutes=snap.get("timeout_minutes", 120))
                db.add(current)
            current.definition = definition
            current.active_definition = definition
            current.active_version = (current.active_version or 0) + 1
            current.has_changes = False
            current.updated_by = actor.id
            current.published_by = actor.id
            current.published_at = _now()
            if item.get("status_after"):
                current.status = item["status_after"]
            db.flush()
            result.append({"kind": "workflow", "name": item["name"], "outcome": "published",
                           "version": current.active_version, "id": str(current.id), "status": current.status})
        elif item["kind"] == "workflow_disable":
            wf = db.get(StudioWorkflow, uuid.UUID(item["target_id"]))
            if wf is not None:
                wf.status = "disabled"
            result.append({"kind": "workflow", "name": item["name"], "outcome": "disabled"})
    release.replaced = replaced
    release.result = result
    release.status = "promoted"
    release.promoted_by = actor.id
    release.promoted_at = _now()
    for eid in {release.source_entity_id, release.target_entity_id}:
        audit.record(db, entity_id=eid, user=actor, action="studio.release.promoted", object_type="studio_release",
                     object_id=str(release.id),
                     summary=f"Release “{release.title}” promoted: "
                     + ", ".join(f"{r['kind']} {r['name']} {r['outcome']}" for r in result),
                     detail={"approved_by": str(release.decided_by), "items": result})
    return release


def rollback(db: Session, release: StudioRelease, actor: User) -> StudioRelease:
    """A new release, within the target, that restores what this one replaced. Approved like any release."""
    if release.status != "promoted" or not release.replaced:
        raise ReleaseError("Only a promoted release can be rolled back.", 409)
    target = db.get(Entity, release.target_entity_id)
    if not _manages(db, actor, target):
        raise ReleaseError("Only an owner or manager of the target company can roll back.", 403)
    items = []
    for prev, done in zip(release.replaced, release.result or [], strict=False):
        before = prev.get("previous")
        if done.get("outcome") == "unchanged":
            continue
        if prev["kind"] == "mapping":
            if before is None:
                items.append({"kind": "mapping_retire", "name": prev["name"], "target_id": done.get("id"),
                              "source_version": None, "snapshot": {}})
            else:
                items.append({"kind": "mapping", "name": prev["name"], "source_version": before["version"],
                              "source_id": before["id"],
                              "snapshot": {"key": prev["name"], "name": before["name"],
                                           "object_type": before["object_type"], "spec": before["spec"],
                                           "effective_from": before["effective_from"]}})
        else:
            if before is None:
                items.append({"kind": "workflow_disable", "name": prev["name"], "target_id": done.get("id"),
                              "source_version": None, "snapshot": {}})
            else:
                items.append({"kind": "workflow", "name": prev["name"], "source_version": before["version"],
                              "source_id": before["id"], "resolved": True, "status_after": before["status"],
                              "snapshot": {"name": prev["name"], "definition": before["definition"]}})
    if not items:
        raise ReleaseError("Nothing to restore: the release changed nothing.", 409)
    back = StudioRelease(org_id=release.org_id, source_entity_id=target.id, target_entity_id=target.id,
                         title=f"Roll back “{release.title}”"[:200], status="draft", items=items,
                         rollback_of_id=release.id, created_by=actor.id,
                         notes="Restores what the release replaced, as new versions. History is not edited.")
    db.add(back)
    db.flush()
    audit.record(db, entity_id=target.id, user=actor, action="studio.release.rollback_drafted",
                 object_type="studio_release", object_id=str(back.id), summary=back.title)
    return back


def describe(db: Session, release: StudioRelease, with_impact: bool = False) -> dict[str, Any]:
    def email(uid: Any) -> str | None:
        u = db.get(User, uid) if uid else None
        return u.email if u else None

    src, dst = db.get(Entity, release.source_entity_id), db.get(Entity, release.target_entity_id)
    out = {
        "id": str(release.id), "title": release.title, "notes": release.notes, "status": release.status,
        "source": {"id": str(src.id), "name": src.name, "environment": environment_of(db, src.id)},
        "target": {"id": str(dst.id), "name": dst.name, "environment": environment_of(db, dst.id)},
        "items": [{"kind": i["kind"], "name": i["name"], "source_version": i.get("source_version")}
                  for i in release.items or []],
        "result": release.result, "rollback_of_id": str(release.rollback_of_id) if release.rollback_of_id else None,
        "created_by": email(release.created_by), "decided_by": email(release.decided_by),
        "decision_note": release.decision_note, "promoted_by": email(release.promoted_by),
        "created_at": release.created_at.isoformat() if release.created_at else None,
        "decided_at": release.decided_at.isoformat() if release.decided_at else None,
        "promoted_at": release.promoted_at.isoformat() if release.promoted_at else None,
        "can_roll_back": release.status == "promoted" and bool(release.replaced)
        and any(r.get("outcome") != "unchanged" for r in (release.result or [])),
    }
    if with_impact and release.status in ("draft", "awaiting_approval", "approved"):
        out["impact"] = impact(db, release)
    return out
