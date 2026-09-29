"""
What a validation run depended on, captured so it can be compared later.

A run's result is a function of more than the register. It also reads the
employee master as it stood at period end, the month's attendance, CTC records,
the previous month's register (for month-on-month checks) and a good deal of
configuration: component flags, PF/ESIC settings, PT/LWF schedules, minimum
wages, published decision-matrix rules, suppressed rules and tolerances.

Each of those gets its own digest. Storing them separately is what lets the
product say *which* input changed since a run — "the attendance register was
re-uploaded" is actionable; "something changed" is not.

The configuration is also kept whole, as data (``snapshot``), so an approved
month can show the rates and slabs it was validated under after they change.

Digests exclude row ids and timestamps: re-saving an identical configuration
must not make every signed-off month look stale.
"""
from __future__ import annotations

import calendar
import hashlib
import json
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models import (
    AttendanceRow,
    ComponentConfig,
    CtcRecord,
    EmployeeRecord,
    Entity,
    LwfRate,
    MinimumWageApplicability,
    MinimumWageRate,
    PtSlab,
    SalaryRegisterRow,
    SlabRule,
    StatutoryConfig,
    TenantRulePreference,
    ValidationRuleVersion,
)
from app.models.findings import ENGINE_VERSION

#: Columns that identify or timestamp a row rather than describe it.
_IGNORED = {
    "id", "created_at", "updated_at", "user_id", "entity_id", "register_id",
    "upload_id", "created_by_user_id", "updated_by_user_id", "approved_by_user_id",
    "published_by_user_id", "published_at", "approved_at", "submitted_at",
    "submitted_by_user_id", "decided_by_user_id",
}

#: The inputs a run is fingerprinted on, in the order people read them.
INPUT_LABELS = {
    "register": "Salary register rows",
    "master": "Employee master as at period end",
    "attendance": "Attendance register for the period",
    "ctc": "CTC records",
    "prior_register": "Previous month's register",
    "configuration": "Configuration (components, statutory settings, slabs, rules)",
    "engine": "Validation engine version",
}


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value.normalize()) if value == value.to_integral() else str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple, set)):
        return [_plain(v) for v in value]
    return value


def row_as_data(obj: Any, extra_ignore: set[str] | None = None) -> dict[str, Any]:
    ignore = _IGNORED | (extra_ignore or set())
    return {
        column.key: _plain(getattr(obj, column.key))
        for column in obj.__table__.columns
        if column.key not in ignore
    }


def digest(value: Any) -> str:
    text = json.dumps(_plain(value), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _rows(objs: list[Any], key=None, extra_ignore: set[str] | None = None) -> list[dict[str, Any]]:
    data = [row_as_data(o, extra_ignore) for o in objs]
    return sorted(data, key=key or (lambda d: json.dumps(d, sort_keys=True, default=str)))


def _cell(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(_plain(value), sort_keys=True, separators=(",", ":"), default=str)
    return str(_plain(value))


def _table_digest(db: Session, model: Any, *criteria: Any) -> tuple[str, int]:
    """Digest of the rows a filter selects, straight from column tuples.

    Large inputs — a 20,000-row master — are digested on every results page
    load to decide whether a run is still current. Materialising ORM objects
    and re-serialising each as a dict cost seconds; reading the columns and
    hashing sorted text lines costs a fraction of that, with the same
    property: identical data, identical digest, whatever the row order or ids.
    """
    columns = [c for c in model.__table__.columns if c.key not in _IGNORED]
    lines = sorted(
        "\x1f".join(_cell(value) for value in row)
        for row in db.query(*columns).filter(*criteria)
    )
    h = hashlib.sha256()
    for line in lines:
        h.update(line.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest(), len(lines)


def _period_end(period: date) -> date:
    return period.replace(day=calendar.monthrange(period.year, period.month)[1])


def _prev(period: date) -> date:
    if period.month == 1:
        return date(period.year - 1, 12, 1)
    return date(period.year, period.month - 1, 1)


def configuration_snapshot(db: Session, entity: Entity, period_month: date) -> dict[str, Any]:
    """Every configuration value validation reads for this entity and period, as data."""
    period_month = period_month.replace(day=1)
    eid = entity.id

    # The engine creates default settings rows the first time it reads them.
    # Materialise them the same way *before* capturing, or a run's own reads
    # would change the configuration it is fingerprinted against, and every
    # first run would be stale the moment it finished.
    from app.services.config_service import ConfigService
    from app.services.tax_year_defaults import fy_label_for_date
    from app.services.validation import _get_or_default_settings

    settings = _get_or_default_settings(db, entity)
    service = ConfigService(db)
    effective: dict[str, Any] = {
        "pf": service.get_pf_config(eid).model_dump(mode="json"),
        "esic": service.get_esic_config(eid).model_dump(mode="json"),
        "component_mapping": service.get_component_mapping(eid).model_dump(mode="json"),
        "rule_thresholds": service.get_rule_thresholds(eid).model_dump(mode="json"),
    }
    try:
        year = service.get_tax_year(eid, fy_label_for_date(period_month))
        effective["income_tax_year"] = year.model_dump(mode="json") if year is not None else None
    except Exception:  # noqa: BLE001 — recorded as unknown, not guessed
        effective["income_tax_year"] = "unavailable"
    statutory = db.get(StatutoryConfig, eid)
    matrix = (
        db.query(ValidationRuleVersion)
        .filter(ValidationRuleVersion.entity_id == eid, ValidationRuleVersion.status == "published")
        .all()
    )
    from app.services.validation_matrix import published_for

    in_force = {v.id for v in published_for(db, eid, period_month)}

    return {
        "engine_version": ENGINE_VERSION,
        "period_month": period_month.isoformat(),
        "components": _rows(
            db.query(ComponentConfig).filter(ComponentConfig.entity_id == eid).all(),
            key=lambda d: str(d.get("component_name", "")).lower(),
        ),
        # What the engine applies, defaults included — the rates as used.
        "effective_statutory": effective,
        "statutory_config": row_as_data(statutory) if statutory else None,
        "statutory_settings": row_as_data(settings) if settings else None,
        "slab_rules": _rows(db.query(SlabRule).filter(SlabRule.entity_id == eid).all()),
        "minimum_wage_rates": _rows(
            db.query(MinimumWageRate).filter(MinimumWageRate.entity_id == eid).all()
        ),
        "minimum_wage_applicability": _rows(
            db.query(MinimumWageApplicability)
            .filter(MinimumWageApplicability.entity_id == eid)
            .all()
        ),
        "suppressed_rules": sorted(
            rule_id
            for (rule_id,) in db.query(TenantRulePreference.rule_id)
            .filter(TenantRulePreference.entity_id == eid, TenantRulePreference.suppressed.is_(True))
            .all()
        ),
        # Rule versions are identified by key and version number, which is what
        # a reader recognises; the in-force flag records which applied here.
        "matrix_rules": sorted(
            (
                {
                    "rule_key": v.rule_key,
                    "version": v.version,
                    "effective_from": _plain(v.effective_from),
                    "effective_to": _plain(v.effective_to),
                    "in_force": v.id in in_force,
                    "definition_digest": digest(row_as_data(v, {"status"})),
                }
                for v in matrix
            ),
            key=lambda d: (d["rule_key"], d["version"]),
        ),
        # Seeded reference schedules are shared across tenants; their digest is
        # enough to notice they changed under a run.
        "reference_pt_digest": digest(_rows(db.query(PtSlab).all())),
        "reference_lwf_digest": digest(_rows(db.query(LwfRate).all())),
    }


def input_digests(
    db: Session,
    entity: Entity,
    period_month: date,
    *,
    rows_sha256: str | None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One digest per input. ``rows_sha256`` is the frozen upload's own digest."""
    period_month = period_month.replace(day=1)
    eid = entity.id
    end = _period_end(period_month)
    prior = _prev(period_month)
    config = config if config is not None else configuration_snapshot(db, entity, period_month)

    master, n_master = _table_digest(
        db, EmployeeRecord, EmployeeRecord.entity_id == eid, EmployeeRecord.effective_from <= end
    )
    attendance, n_attendance = _table_digest(
        db, AttendanceRow, AttendanceRow.entity_id == eid, AttendanceRow.period_month == period_month
    )
    ctc, n_ctc = _table_digest(
        db, CtcRecord, CtcRecord.entity_id == eid, CtcRecord.effective_from <= end
    )
    prior_register, n_prior = _table_digest(
        db, SalaryRegisterRow,
        SalaryRegisterRow.entity_id == eid, SalaryRegisterRow.period_month == prior,
    )
    return {
        "register": rows_sha256,
        "master": master,
        "attendance": attendance,
        "ctc": ctc,
        "prior_register": prior_register,
        "configuration": digest(config),
        "engine": ENGINE_VERSION,
        "counts": {
            "master_records": n_master,
            "attendance_rows": n_attendance,
            "ctc_records": n_ctc,
            "prior_register_rows": n_prior,
        },
    }


def changed_inputs(then: dict[str, Any] | None, now: dict[str, Any]) -> list[dict[str, str]]:
    """Which inputs differ between a run's digests and the present.

    A run recorded before digests existed has none; that is reported as its own
    reason rather than treated as "nothing changed" — an unknown is not a match.
    """
    if not then:
        return [{
            "input": "unrecorded",
            "label": "This run predates input tracking",
            "detail": "Its inputs were not fingerprinted, so it cannot be shown to be current.",
        }]
    changes = []
    for key, label in INPUT_LABELS.items():
        if key == "register" and not now.get("register"):
            continue
        if then.get(key) != now.get(key):
            changes.append({"input": key, "label": label, "detail": f"{label} changed since this run."})
    return changes


def run_freshness(db: Session, entity: Entity, run: Any) -> dict[str, Any]:
    """Is this run still the answer for its inputs? If not, which input moved?

    Compared against the latest upload for the period — a re-upload is exactly
    the change that makes a run stale — and against today's master,
    attendance, CTC and configuration.
    """
    from app.services.register_uploads import latest_for_period

    latest = latest_for_period(db, entity.id, run.period_month, getattr(run, "run_type", None) or "regular")
    now = input_digests(
        db, entity, run.period_month,
        rows_sha256=latest.rows_sha256 if latest else (run.input_digests or {}).get("register"),
    )
    changes = changed_inputs(run.input_digests, now)
    return {
        "is_current_for_inputs": not changes,
        "revalidation_required": bool(changes),
        "changes": changes,
        "latest_upload_id": str(latest.id) if latest else None,
    }
