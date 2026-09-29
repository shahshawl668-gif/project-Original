"""
Saved dashboards and custom KPIs, per company.

Who sees what:

* A **private** dashboard or KPI is its owner's alone. Anyone who can open the
  company — a viewer included — can keep private ones.
* A **shared** one is visible to everyone who can open the company. Sharing
  needs a write role (analyst, manager, owner).
* The owner edits and deletes; an owner or manager of the company may also edit
  or delete a shared one, so a departed colleague's shared board is not stuck.
* Everything is scoped to the company in ``X-Entity-Id``. Another company's
  dashboard answers 404 — its existence is not confirmed.

A shared dashboard may not use a private KPI: its other viewers could not see
what the tile computes.
"""
from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_entity, get_current_user
from app.envelope import ok
from app.models import CustomKpi, Dashboard, Entity, User
from app.services import audit, dashboards as svc, tenancy

router = APIRouter()

WRITE_ROLES = ("owner", "manager", "analyst")
ADMIN_ROLES = ("owner", "manager")
CHARTS = ("kpi", "bar", "line", "pie", "table")
MAX_TILES = 24


class PeriodSpec(BaseModel):
    preset: Literal["last_3", "last_6", "last_12", "all", "custom"] | None = None
    inherit: bool = False
    from_: str | None = Field(default=None, alias="from", pattern=r"^\d{4}-\d{2}$")
    to: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")

    model_config = {"populate_by_name": True}

    def as_dict(self) -> dict[str, Any]:
        return {"preset": self.preset, "inherit": self.inherit, "from": self.from_, "to": self.to}


class QueryRequest(BaseModel):
    dataset: str = Field(max_length=32)
    metric: str | None = Field(default=None, max_length=48)
    kpi_id: uuid.UUID | None = None
    breakdown: str = Field(default="period", max_length=32)
    granularity: Literal["month", "quarter", "year"] = "month"
    filters: dict[str, list[str]] = Field(default_factory=dict)
    period: PeriodSpec | None = None


class Tile(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12], max_length=32)
    title: str = Field(min_length=1, max_length=120)
    dataset: str = Field(max_length=32)
    metric: str | None = Field(default=None, max_length=48)
    kpi_id: uuid.UUID | None = None
    breakdown: str = Field(default="period", max_length=32)
    chart: Literal["kpi", "bar", "line", "pie", "table"] = "bar"
    granularity: Literal["month", "quarter", "year"] = "month"
    filters: dict[str, list[str]] = Field(default_factory=dict)
    period: PeriodSpec = Field(default_factory=lambda: PeriodSpec(inherit=True))


class DashboardBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    visibility: Literal["private", "shared"] = "private"
    period: PeriodSpec = Field(default_factory=lambda: PeriodSpec(preset="last_6"))
    tiles: list[Tile] = Field(default_factory=list, max_length=MAX_TILES)


class KpiBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    dataset: str = Field(max_length=32)
    formula: str = Field(min_length=1, max_length=500)
    unit: Literal["inr", "number", "pct"] = "number"
    visibility: Literal["private", "shared"] = "private"


def _role(db: Session, user: User, entity: Entity) -> str | None:
    return tenancy.effective_entity_role(db, user, entity)


def _visible(model, db: Session, user: User, entity: Entity):
    return db.query(model).filter(
        model.entity_id == entity.id,
        or_(model.owner_user_id == user.id, model.visibility == "shared"),
    )


def _can_edit(row, user: User, role: str | None) -> bool:
    return row.owner_user_id == user.id or (row.visibility == "shared" and role in ADMIN_ROLES)


def _kpi_for(db: Session, user: User, entity: Entity, kpi_id: uuid.UUID | None) -> CustomKpi | None:
    if kpi_id is None:
        return None
    kpi = _visible(CustomKpi, db, user, entity).filter(CustomKpi.id == kpi_id).first()
    if kpi is None:
        raise HTTPException(status_code=404, detail="KPI not found")
    return kpi


def _check_tiles(db: Session, user: User, entity: Entity, tiles: list[Tile], visibility: str) -> None:
    for t in tiles:
        ds = svc.DATASETS.get(t.dataset)
        if ds is None:
            raise HTTPException(status_code=400, detail=f"Tile “{t.title}”: unknown dataset")
        if t.breakdown not in {k for k, _ in ds.breakdowns}:
            raise HTTPException(status_code=400, detail=f"Tile “{t.title}”: {ds.label} cannot be broken down by {t.breakdown}")
        if t.kpi_id is not None:
            kpi = _kpi_for(db, user, entity, t.kpi_id)
            if kpi.dataset != t.dataset:
                raise HTTPException(status_code=400, detail=f"Tile “{t.title}”: that KPI belongs to another dataset")
            if visibility == "shared" and kpi.visibility != "shared":
                raise HTTPException(status_code=400, detail=f"Tile “{t.title}” uses the private KPI “{kpi.name}”. Share the KPI first, or keep the dashboard private.")
        elif ds.metric(t.metric or "") is None:
            raise HTTPException(status_code=400, detail=f"Tile “{t.title}”: {ds.label} has no metric {t.metric}")
        bad = {k for k, v in t.filters.items() if v} - set(ds.filters)
        if bad:
            raise HTTPException(status_code=400, detail=f"Tile “{t.title}”: cannot filter {ds.label} by {', '.join(sorted(bad))}")


def _out(d: Dashboard, user: User, role: str | None, owners: dict | None = None) -> dict:
    return {
        "id": str(d.id), "name": d.name, "description": d.description, "visibility": d.visibility,
        "layout": d.layout, "template_key": d.template_key,
        "owner_user_id": str(d.owner_user_id) if d.owner_user_id else None,
        "owner_email": (owners or {}).get(d.owner_user_id),
        "mine": d.owner_user_id == user.id, "can_edit": _can_edit(d, user, role),
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
    }


def _kpi_out(k: CustomKpi, user: User, role: str | None) -> dict:
    return {
        "id": str(k.id), "name": k.name, "description": k.description, "dataset": k.dataset,
        "formula": k.formula, "unit": k.unit, "visibility": k.visibility,
        "owner_user_id": str(k.owner_user_id) if k.owner_user_id else None,
        "mine": k.owner_user_id == user.id, "can_edit": _can_edit(k, user, role),
    }


def _layout(body: DashboardBody) -> dict:
    return {"period": body.period.as_dict(), "tiles": [
        {**t.model_dump(exclude={"period", "kpi_id"}), "kpi_id": str(t.kpi_id) if t.kpi_id else None,
         "period": t.period.as_dict()} for t in body.tiles]}


# ---------------------------------------------------------------------------
# Catalogue and query
# ---------------------------------------------------------------------------
@router.get("/datasets")
def datasets(db: Session = Depends(get_db), user: User = Depends(get_current_user),
             entity: Entity = Depends(get_current_entity)):
    role = _role(db, user, entity)
    kpis = _visible(CustomKpi, db, user, entity).order_by(CustomKpi.name).all()
    return ok({"datasets": svc.catalogue(), "kpis": [_kpi_out(k, user, role) for k in kpis],
               "charts": list(CHARTS),
               "templates": [{"key": k, "name": t["name"], "description": t["description"], "tiles": len(t["tiles"])}
                             for k, t in svc.TEMPLATES.items()]})


@router.post("/query")
def run_query(body: QueryRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user),
              entity: Entity = Depends(get_current_entity)):
    """One tile's answer, computed now from the company's data."""
    kpi = _kpi_for(db, user, entity, body.kpi_id)
    try:
        return ok(svc.query(db, entity, dataset=body.dataset, metric=body.metric, kpi=kpi,
                            breakdown=body.breakdown, granularity=body.granularity,
                            filters=body.filters, period=body.period.as_dict() if body.period else None))
    except svc.QueryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Dashboards
# ---------------------------------------------------------------------------
@router.get("")
def list_dashboards(db: Session = Depends(get_db), user: User = Depends(get_current_user),
                    entity: Entity = Depends(get_current_entity)):
    role = _role(db, user, entity)
    rows = _visible(Dashboard, db, user, entity).order_by(Dashboard.name).all()
    owners = dict(db.query(User.id, User.email).filter(User.id.in_({r.owner_user_id for r in rows if r.owner_user_id})).all()) if rows else {}
    return ok([_out(r, user, role, owners) for r in rows])


def _load(db: Session, user: User, entity: Entity, dashboard_id: uuid.UUID) -> Dashboard:
    row = _visible(Dashboard, db, user, entity).filter(Dashboard.id == dashboard_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    return row


@router.get("/{dashboard_id}")
def get_dashboard(dashboard_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user),
                  entity: Entity = Depends(get_current_entity)):
    return ok(_out(_load(db, user, entity, dashboard_id), user, _role(db, user, entity)))


@router.post("")
def create_dashboard(body: DashboardBody, db: Session = Depends(get_db), user: User = Depends(get_current_user),
                     entity: Entity = Depends(get_current_entity)):
    role = _role(db, user, entity)
    if body.visibility == "shared" and role not in WRITE_ROLES:
        raise HTTPException(status_code=403, detail="Your role can keep private dashboards but not share them")
    _check_tiles(db, user, entity, body.tiles, body.visibility)
    row = Dashboard(org_id=entity.org_id, entity_id=entity.id, owner_user_id=user.id, name=body.name.strip(),
                    description=body.description, visibility=body.visibility, layout=_layout(body))
    db.add(row)
    db.flush()
    audit.record(db, entity_id=entity.id, org_id=entity.org_id, user=user, action="dashboard.created",
                 object_type="dashboard", object_id=str(row.id), summary=f"Created dashboard “{row.name}” ({row.visibility})")
    db.commit()
    return ok(_out(row, user, role))


class FromTemplate(BaseModel):
    template: str = Field(max_length=48)
    name: str | None = Field(default=None, max_length=120)


@router.post("/from-template")
def from_template(body: FromTemplate, db: Session = Depends(get_db), user: User = Depends(get_current_user),
                  entity: Entity = Depends(get_current_entity)):
    """A private copy of a template, to use as is or change."""
    t = svc.TEMPLATES.get(body.template)
    if t is None:
        raise HTTPException(status_code=404, detail="No such template")
    tiles = [Tile(**{**tile, "period": PeriodSpec(inherit=True)}) for tile in t["tiles"]]
    row = Dashboard(org_id=entity.org_id, entity_id=entity.id, owner_user_id=user.id,
                    name=(body.name or t["name"]).strip(), description=t["description"], visibility="private",
                    template_key=body.template,
                    layout=_layout(DashboardBody(name=t["name"], tiles=tiles, period=PeriodSpec(preset="last_6"))))
    db.add(row)
    db.flush()
    audit.record(db, entity_id=entity.id, org_id=entity.org_id, user=user, action="dashboard.created",
                 object_type="dashboard", object_id=str(row.id), summary=f"Created “{row.name}” from a template")
    db.commit()
    return ok(_out(row, user, _role(db, user, entity)))


@router.put("/{dashboard_id}")
def update_dashboard(dashboard_id: uuid.UUID, body: DashboardBody, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user), entity: Entity = Depends(get_current_entity)):
    role = _role(db, user, entity)
    row = _load(db, user, entity, dashboard_id)
    if not _can_edit(row, user, role):
        raise HTTPException(status_code=403, detail="Only its owner, or an owner or manager for a shared one, can change this dashboard")
    if body.visibility == "shared" and role not in WRITE_ROLES:
        raise HTTPException(status_code=403, detail="Your role can keep private dashboards but not share them")
    _check_tiles(db, user, entity, body.tiles, body.visibility)
    before = row.visibility
    row.name, row.description, row.visibility, row.layout = body.name.strip(), body.description, body.visibility, _layout(body)
    db.add(row)
    audit.record(db, entity_id=entity.id, org_id=entity.org_id, user=user, action="dashboard.updated",
                 object_type="dashboard", object_id=str(row.id),
                 summary=f"Updated dashboard “{row.name}”" + (f" ({before} → {row.visibility})" if before != row.visibility else ""))
    db.commit()
    return ok(_out(row, user, role))


@router.post("/{dashboard_id}/duplicate")
def duplicate(dashboard_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user),
              entity: Entity = Depends(get_current_entity)):
    src = _load(db, user, entity, dashboard_id)
    row = Dashboard(org_id=entity.org_id, entity_id=entity.id, owner_user_id=user.id, name=f"{src.name} (copy)"[:120],
                    description=src.description, visibility="private", layout=src.layout, template_key=src.template_key)
    db.add(row)
    db.commit()
    return ok(_out(row, user, _role(db, user, entity)))


@router.delete("/{dashboard_id}")
def delete_dashboard(dashboard_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user),
                     entity: Entity = Depends(get_current_entity)):
    role = _role(db, user, entity)
    row = _load(db, user, entity, dashboard_id)
    if not _can_edit(row, user, role):
        raise HTTPException(status_code=403, detail="Only its owner, or an owner or manager for a shared one, can delete this dashboard")
    audit.record(db, entity_id=entity.id, org_id=entity.org_id, user=user, action="dashboard.deleted",
                 object_type="dashboard", object_id=str(row.id), summary=f"Deleted dashboard “{row.name}”")
    db.delete(row)
    db.commit()
    return ok({"deleted": True})


# ---------------------------------------------------------------------------
# Custom KPIs
# ---------------------------------------------------------------------------
kpi_router = APIRouter()


@kpi_router.post("")
def create_kpi(body: KpiBody, db: Session = Depends(get_db), user: User = Depends(get_current_user),
               entity: Entity = Depends(get_current_entity)):
    role = _role(db, user, entity)
    if body.visibility == "shared" and role not in WRITE_ROLES:
        raise HTTPException(status_code=403, detail="Your role can keep private KPIs but not share them")
    try:
        svc.validate_kpi(body.dataset, body.formula)
    except svc.QueryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    k = CustomKpi(org_id=entity.org_id, entity_id=entity.id, owner_user_id=user.id, **body.model_dump())
    db.add(k)
    db.flush()
    audit.record(db, entity_id=entity.id, org_id=entity.org_id, user=user, action="kpi.created",
                 object_type="custom_kpi", object_id=str(k.id), summary=f"Created KPI “{k.name}” = {k.formula}")
    db.commit()
    return ok(_kpi_out(k, user, role))


@kpi_router.put("/{kpi_id}")
def update_kpi(kpi_id: uuid.UUID, body: KpiBody, db: Session = Depends(get_db), user: User = Depends(get_current_user),
               entity: Entity = Depends(get_current_entity)):
    role = _role(db, user, entity)
    k = _kpi_for(db, user, entity, kpi_id)
    if not _can_edit(k, user, role):
        raise HTTPException(status_code=403, detail="Only its owner, or an owner or manager for a shared one, can change this KPI")
    if body.visibility == "shared" and role not in WRITE_ROLES:
        raise HTTPException(status_code=403, detail="Your role can keep private KPIs but not share them")
    if body.visibility == "private" and k.visibility == "shared":
        users = [d.name for d in db.query(Dashboard).filter(Dashboard.entity_id == entity.id, Dashboard.visibility == "shared")
                 if any(t.get("kpi_id") == str(k.id) for t in (d.layout or {}).get("tiles", []))]
        if users:
            raise HTTPException(status_code=409, detail=f"Shared dashboards use this KPI: {', '.join(users)}")
    try:
        svc.validate_kpi(body.dataset, body.formula)
    except svc.QueryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    before = k.formula
    for key, value in body.model_dump().items():
        setattr(k, key, value)
    db.add(k)
    audit.record(db, entity_id=entity.id, org_id=entity.org_id, user=user, action="kpi.updated",
                 object_type="custom_kpi", object_id=str(k.id), summary=f"Updated KPI “{k.name}”: {before} → {k.formula}")
    db.commit()
    return ok(_kpi_out(k, user, role))


@kpi_router.delete("/{kpi_id}")
def delete_kpi(kpi_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user),
               entity: Entity = Depends(get_current_entity)):
    role = _role(db, user, entity)
    k = _kpi_for(db, user, entity, kpi_id)
    if not _can_edit(k, user, role):
        raise HTTPException(status_code=403, detail="Only its owner, or an owner or manager for a shared one, can delete this KPI")
    used = [d.name for d in db.query(Dashboard).filter(Dashboard.entity_id == entity.id)
            if any(t.get("kpi_id") == str(k.id) for t in (d.layout or {}).get("tiles", []))]
    if used:
        raise HTTPException(status_code=409, detail=f"Dashboards use this KPI: {', '.join(used)}. Remove those tiles first.")
    audit.record(db, entity_id=entity.id, org_id=entity.org_id, user=user, action="kpi.deleted",
                 object_type="custom_kpi", object_id=str(k.id), summary=f"Deleted KPI “{k.name}”")
    db.delete(k)
    db.commit()
    return ok({"deleted": True})
