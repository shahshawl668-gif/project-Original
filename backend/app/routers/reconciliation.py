"""
Bank file and journal voucher reconciliation.

Three groups of endpoints, and the split matters:

* **configuration** — bank file profiles and JV templates. Editable by an
  analyst, because getting a column mapping right is operational work;
* **evidence** — uploading a bank file, previewing a voucher, running a
  reconciliation and keeping the result;
* **approval** — making a JV template the current one, and closing a
  reconciliation. Owners and managers only: approving the mapping that posts to
  the general ledger is not an analyst's decision, for the same reason
  approving a budget is not.
"""
from __future__ import annotations

import io
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_entity, get_current_user, require_entity_write, require_entity_admin
from app.envelope import ok
from app.models import (
    BankFile,
    BankFileProfile,
    BankFileRow,
    Entity,
    JvRule,
    JvTemplate,
    ReconException,
    ReconRun,
    User,
)
from app.services import audit, bank_file as bank_file_service, jv_builder, reconciliation
from app.services.dimensions import DIMENSION_KEYS

router = APIRouter()

MAX_STORED_ROWS = 50_000


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------
class ProfileBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    bank_label: str | None = Field(default=None, max_length=120)
    note: str | None = Field(default=None, max_length=2000)
    kind: str = "payment_advice"
    layout: str = "delimited"
    delimiter: str = Field(default=",", max_length=4)
    encoding: str = Field(default="utf-8", max_length=32)
    has_header: bool = True
    skip_rows: int = Field(default=0, ge=0, le=100)
    trailer_rows: int = Field(default=0, ge=0, le=100)
    column_map: dict[str, Any] = Field(default_factory=dict)
    amount_unit: str = "rupees"
    amount_sign: str = "as_is"
    date_format: str | None = Field(default=None, max_length=32)
    employee_id_transform: str = "trim"
    row_filter: dict[str, Any] = Field(default_factory=dict)
    is_default: bool = False


class RuleBody(BaseModel):
    label: str = Field(min_length=1, max_length=160)
    account_code: str = Field(default="", max_length=64)
    account_name: str | None = Field(default=None, max_length=160)
    side: str = "debit"
    measures: list[str] = Field(default_factory=list)
    filters: dict[str, list[str]] = Field(default_factory=dict)
    cost_center_from: str | None = None
    active: bool = True
    note: str | None = Field(default=None, max_length=2000)


class TemplateBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    note: str | None = Field(default=None, max_length=2000)
    posting_basis: str = "accrual"
    split_mode: str = "consolidated"
    group_by: str | None = None
    detail_level: str = "summary"
    sign_convention: str = "two_column"
    net_pay_source: str = "computed"
    voucher_date_rule: str = "month_end"
    voucher_type: str = Field(default="Journal", max_length=32)
    narration_template: str = Field(
        default="Payroll for {period_label}{scope_suffix}", max_length=255
    )
    export_format: str = "generic_csv"
    balance_tolerance: float = Field(default=1.0, ge=0, le=1_000_000)
    rounding_mode: str = "none"
    rounding_account: str | None = Field(default=None, max_length=64)
    rules: list[RuleBody] = Field(default_factory=list)
    # Start from a supplied template instead of writing every rule out.
    from_preset: str | None = None


class RunBody(BaseModel):
    period_month: date
    kind: str = "bank"
    bank_file_id: uuid.UUID | None = None
    jv_template_id: uuid.UUID | None = None


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
_PROFILE_CHOICES: dict[str, tuple[str, ...]] = {
    "kind": tuple(k for k, _, _ in bank_file_service.FILE_KINDS),
    "layout": tuple(k for k, _, _ in bank_file_service.LAYOUTS),
    "amount_unit": tuple(k for k, _ in bank_file_service.AMOUNT_UNITS),
    "amount_sign": tuple(k for k, _, _ in bank_file_service.AMOUNT_SIGNS),
    "employee_id_transform": tuple(k for k, _, _ in bank_file_service.ID_TRANSFORMS),
}

_TEMPLATE_CHOICES: dict[str, tuple[str, ...]] = {
    "posting_basis": tuple(k for k, _, _ in jv_builder.POSTING_BASES),
    "split_mode": tuple(k for k, _, _ in jv_builder.SPLIT_MODES),
    "detail_level": tuple(k for k, _, _ in jv_builder.DETAIL_LEVELS),
    "sign_convention": tuple(k for k, _, _ in jv_builder.SIGN_CONVENTIONS),
    "net_pay_source": tuple(k for k, _, _ in jv_builder.NET_PAY_SOURCES),
    "voucher_date_rule": tuple(k for k, _, _ in jv_builder.VOUCHER_DATE_RULES),
    "rounding_mode": tuple(k for k, _, _ in jv_builder.ROUNDING_MODES),
    "export_format": tuple(k for k, _, _ in jv_builder.EXPORT_FORMATS),
}


def _check_choices(body: Any, choices: dict[str, tuple[str, ...]]) -> None:
    for field_name, allowed in choices.items():
        value = getattr(body, field_name, None)
        if value is not None and value not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"'{value}' is not a valid {field_name.replace('_', ' ')}. "
                       f"Choose one of: {', '.join(allowed)}.",
            )


def _check_template(body: TemplateBody) -> None:
    _check_choices(body, _TEMPLATE_CHOICES)
    if body.group_by and body.group_by not in DIMENSION_KEYS:
        raise HTTPException(status_code=400, detail=f"Unknown grouping dimension: {body.group_by}")
    if body.split_mode == "per_group" and not body.group_by:
        raise HTTPException(
            status_code=400,
            detail="A voucher per cost centre needs a grouping dimension. Choose which "
                   "dimension is the cost centre, or switch to a single voucher.",
        )
    if body.rounding_mode == "account" and not body.rounding_account:
        raise HTTPException(
            status_code=400,
            detail="Rounding to an account needs the account code to round into.",
        )
    valid = set(jv_builder.MEASURE_KEYS) | {"gross", "employer_cost", "ctc", "deductions", "net"}
    for index, rule in enumerate(body.rules, start=1):
        if rule.side not in ("debit", "credit"):
            raise HTTPException(
                status_code=400, detail=f"Rule {index}: side must be debit or credit."
            )
        unknown = [m for m in rule.measures if m not in valid]
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=f"Rule {index} maps measures this product does not have: "
                       f"{', '.join(unknown)}.",
            )
        if rule.cost_center_from and rule.cost_center_from not in DIMENSION_KEYS:
            raise HTTPException(
                status_code=400,
                detail=f"Rule {index}: unknown dimension {rule.cost_center_from}.",
            )
        for key in rule.filters:
            if key not in DIMENSION_KEYS:
                raise HTTPException(
                    status_code=400, detail=f"Rule {index}: unknown filter dimension {key}."
                )


def _period(value: str | None, field_name: str = "period") -> date:
    from app.services.budgeting import parse_period

    parsed = parse_period(value) if value else None
    if parsed is None:
        raise HTTPException(status_code=400, detail=f"'{field_name}' is not a readable month")
    return parsed


# ---------------------------------------------------------------------------
# Catalogues — everything the UI would otherwise hard-code
# ---------------------------------------------------------------------------
@router.get("/bank/fields")
def bank_fields():
    """The fields a bank profile maps, and the options each setting accepts."""
    return ok(bank_file_service.field_catalogue())


@router.get("/bank/presets")
def bank_presets():
    """
    Layouts to start from.

    Starting points, not bank specifications. A corporate account can be
    provisioned with a different column set and banks revise their formats, so
    every preset must be checked against the file your bank actually sends —
    which is what the test-against-a-file step is for.
    """
    return ok({
        "presets": [dict(p) for p in bank_file_service.PRESETS],
        "caveat": "These are common layouts offered as a starting point. Verify every "
                  "one against your bank's own file specification before relying on it.",
    })


@router.get("/jv/options")
def jv_options():
    """Every choice a JV template exposes, including the measures a rule can map."""
    return ok(jv_builder.option_catalogue())


@router.get("/jv/presets")
def jv_presets():
    return ok({
        "presets": jv_builder.preset_catalogue(),
        "caveat": "Account codes in these templates are placeholders. Replace them with "
                  "codes from your own chart of accounts before posting anything.",
    })


@router.get("/exceptions")
def exception_catalogue():
    """Every exception this module can raise, what it means and what to do."""
    return ok({"kinds": reconciliation.exception_catalogue()})


# ---------------------------------------------------------------------------
# Bank profiles
# ---------------------------------------------------------------------------
def _profile_out(profile: BankFileProfile) -> dict:
    return {
        "id": str(profile.id), "name": profile.name, "bank_label": profile.bank_label,
        "note": profile.note, "kind": profile.kind, "layout": profile.layout,
        "delimiter": profile.delimiter, "encoding": profile.encoding,
        "has_header": profile.has_header, "skip_rows": profile.skip_rows,
        "trailer_rows": profile.trailer_rows, "column_map": profile.column_map or {},
        "amount_unit": profile.amount_unit, "amount_sign": profile.amount_sign,
        "date_format": profile.date_format,
        "employee_id_transform": profile.employee_id_transform,
        "row_filter": profile.row_filter or {}, "is_default": profile.is_default,
        "created_at": profile.created_at.isoformat() if profile.created_at else None,
    }


def _load_profile(db: Session, entity: Entity, profile_id: uuid.UUID) -> BankFileProfile:
    profile = db.get(BankFileProfile, profile_id)
    if profile is None or profile.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Bank file profile not found")
    return profile


@router.get("/bank/profiles")
def list_profiles(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    profiles = (
        db.query(BankFileProfile)
        .filter(BankFileProfile.entity_id == entity.id)
        .order_by(BankFileProfile.is_default.desc(), BankFileProfile.name)
        .all()
    )
    return ok({"profiles": [_profile_out(p) for p in profiles]})


@router.post("/bank/profiles")
def create_profile(
    body: ProfileBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_entity_write),
):
    _check_choices(body, _PROFILE_CHOICES)
    existing = (
        db.query(BankFileProfile)
        .filter(BankFileProfile.entity_id == entity.id, BankFileProfile.name == body.name.strip())
        .first()
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"A profile named {body.name!r} already exists")

    profile = BankFileProfile(
        entity_id=entity.id, created_by_user_id=user.id,
        **body.model_dump(exclude={"name"}), name=body.name.strip(),
    )
    if profile.is_default:
        _clear_default(db, entity.id)
    db.add(profile)
    db.flush()
    audit.record(
        db, entity_id=entity.id, user=user, action="bank_profile.created",
        object_type="bank_file_profile", object_id=str(profile.id),
        summary=f"Created bank file profile {profile.name!r}",
        detail={"column_map": profile.column_map},
    )
    db.commit()
    db.refresh(profile)
    return ok(_profile_out(profile))


@router.put("/bank/profiles/{profile_id}")
def update_profile(
    profile_id: uuid.UUID,
    body: ProfileBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_entity_write),
):
    _check_choices(body, _PROFILE_CHOICES)
    profile = _load_profile(db, entity, profile_id)
    before = dict(profile.column_map or {})
    for key, value in body.model_dump().items():
        setattr(profile, key, value.strip() if key == "name" else value)
    if profile.is_default:
        _clear_default(db, entity.id, keep=profile.id)
    audit.record(
        db, entity_id=entity.id, user=user, action="bank_profile.updated",
        object_type="bank_file_profile", object_id=str(profile.id),
        summary=f"Updated bank file profile {profile.name!r}",
        detail={"column_map_before": before, "column_map_after": profile.column_map},
    )
    db.commit()
    db.refresh(profile)
    return ok(_profile_out(profile))


@router.delete("/bank/profiles/{profile_id}")
def delete_profile(
    profile_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_entity_write),
):
    profile = _load_profile(db, entity, profile_id)
    audit.record(
        db, entity_id=entity.id, user=user, action="bank_profile.deleted",
        object_type="bank_file_profile", object_id=str(profile.id),
        summary=f"Deleted bank file profile {profile.name!r}",
    )
    db.delete(profile)
    db.commit()
    return ok({"deleted": True})


def _clear_default(db: Session, entity_id: uuid.UUID, keep: uuid.UUID | None = None) -> None:
    query = db.query(BankFileProfile).filter(
        BankFileProfile.entity_id == entity_id, BankFileProfile.is_default.is_(True)
    )
    for other in query.all():
        if keep is None or other.id != keep:
            other.is_default = False


@router.post("/bank/profiles/suggest")
async def suggest_profile(
    file: UploadFile = File(...),
    delimiter: str = Form(default=","),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_entity_write),
):
    """
    Read a file's header row and propose a mapping.

    A proposal, returned with the headers it was drawn from. Nothing is saved
    and nothing is reconciled until someone confirms it.
    """
    content = await file.read()
    try:
        return ok(
            bank_file_service.suggest_mapping(
                content, file.filename or "bank.csv", delimiter=delimiter
            )
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"That file could not be read: {exc}")


@router.post("/bank/profiles/test")
async def test_profile(
    file: UploadFile = File(...),
    profile_id: uuid.UUID | None = Form(default=None),
    profile_json: str | None = Form(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_entity_write),
):
    """
    Run a profile against a real file without storing anything.

    The step that makes a preset safe to use: what the mapping actually
    produced, row by row, before it is trusted with a month of payments.
    """
    import json

    if profile_json:
        try:
            profile: Any = json.loads(profile_json)
        except ValueError:
            raise HTTPException(status_code=400, detail="profile_json is not valid JSON")
    elif profile_id is not None:
        profile = _load_profile(db, entity, profile_id)
    else:
        raise HTTPException(status_code=400, detail="Give either profile_id or profile_json")

    content = await file.read()
    try:
        parsed = bank_file_service.parse_bank_file(content, file.filename or "bank.csv", profile)
    except bank_file_service.ProfileError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return ok({
        "filename": file.filename,
        "row_count": len(parsed.rows),
        "skipped_by_filter": parsed.skipped,
        "total": float(parsed.total),
        "stated_total": None if parsed.stated_total is None else float(parsed.stated_total),
        "header": parsed.header,
        "problems": parsed.problems,
        "rows": [
            {
                "row_number": r.row_number, "employee_id": r.employee_id,
                "employee_name": r.employee_name, "account_number": r.account_number,
                "ifsc": r.ifsc, "amount": float(r.amount), "reference": r.reference,
                "status": r.status,
                "value_date": r.value_date.isoformat() if r.value_date else None,
            }
            for r in parsed.rows[:25]
        ],
        "truncated": len(parsed.rows) > 25,
    })


# ---------------------------------------------------------------------------
# Bank files
# ---------------------------------------------------------------------------
def _file_out(bank: BankFile, rows: int | None = None) -> dict:
    return {
        "id": str(bank.id), "period": bank.period_month.isoformat(),
        "period_label": bank.period_month.strftime("%b %Y"),
        "kind": bank.kind, "filename": bank.filename,
        "row_count": rows if rows is not None else bank.row_count,
        "total": float(bank.total_amount),
        "stated_total": None if bank.stated_total is None else float(bank.stated_total),
        "problems": bank.problems or [], "note": bank.note,
        "profile_id": str(bank.profile_id) if bank.profile_id else None,
        "uploaded_by": bank.uploaded_by_email,
        "created_at": bank.created_at.isoformat() if bank.created_at else None,
    }


@router.post("/bank/files")
async def upload_bank_file(
    file: UploadFile = File(...),
    period: str = Form(...),
    profile_id: uuid.UUID = Form(...),
    note: str | None = Form(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_entity_write),
):
    """Store a bank file, read through a profile, ready to reconcile."""
    period_month = _period(period)
    profile = _load_profile(db, entity, profile_id)

    content = await file.read()
    try:
        parsed = bank_file_service.parse_bank_file(content, file.filename or "bank.csv", profile)
    except bank_file_service.ProfileError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if len(parsed.rows) > MAX_STORED_ROWS:
        raise HTTPException(
            status_code=413,
            detail=f"This file has {len(parsed.rows):,} rows, beyond the {MAX_STORED_ROWS:,} "
                   "this product stores in one upload. Split it by cost centre.",
        )

    bank = BankFile(
        entity_id=entity.id, profile_id=profile.id, period_month=period_month,
        kind=profile.kind, filename=file.filename, row_count=len(parsed.rows),
        total_amount=parsed.total, stated_total=parsed.stated_total,
        problems=list(parsed.problems), note=note,
        uploaded_by_user_id=user.id, uploaded_by_email=user.email,
    )
    db.add(bank)
    db.flush()

    for row in parsed.rows:
        db.add(
            BankFileRow(
                file_id=bank.id, entity_id=entity.id, period_month=period_month,
                row_number=row.row_number, employee_id=row.employee_id,
                employee_name=row.employee_name, account_number=row.account_number,
                ifsc=row.ifsc, amount=row.amount, reference=row.reference,
                status=row.status, value_date=row.value_date, raw=row.raw,
            )
        )

    audit.record(
        db, entity_id=entity.id, user=user, action="bank_file.uploaded",
        object_type="bank_file", object_id=str(bank.id),
        summary=f"Uploaded {file.filename} — {len(parsed.rows)} payments totalling "
                f"₹{parsed.total:,.2f} for {period_month:%b %Y}",
        detail={"profile": profile.name, "problems": parsed.problems},
    )
    db.commit()
    db.refresh(bank)
    return ok(_file_out(bank))


@router.get("/bank/files")
def list_bank_files(
    period: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    query = db.query(BankFile).filter(BankFile.entity_id == entity.id)
    if period:
        query = query.filter(BankFile.period_month == _period(period))
    files = query.order_by(BankFile.period_month.desc(), BankFile.created_at.desc()).all()
    return ok({"files": [_file_out(f) for f in files]})


def _load_file(db: Session, entity: Entity, file_id: uuid.UUID) -> BankFile:
    bank = db.get(BankFile, file_id)
    if bank is None or bank.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Bank file not found")
    return bank


@router.get("/bank/files/{file_id}")
def get_bank_file(
    file_id: uuid.UUID,
    limit: int = Query(default=200, ge=1, le=2000),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    bank = _load_file(db, entity, file_id)
    rows = (
        db.query(BankFileRow)
        .filter(BankFileRow.file_id == bank.id)
        .order_by(BankFileRow.row_number)
        .limit(limit)
        .all()
    )
    payload = _file_out(bank)
    payload["rows"] = [
        {
            "row_number": r.row_number, "employee_id": r.employee_id,
            "employee_name": r.employee_name, "account_number": r.account_number,
            "ifsc": r.ifsc, "amount": float(r.amount), "reference": r.reference,
            "status": r.status,
            "value_date": r.value_date.isoformat() if r.value_date else None,
        }
        for r in rows
    ]
    payload["truncated"] = bank.row_count > len(rows)
    return ok(payload)


@router.delete("/bank/files/{file_id}")
def delete_bank_file(
    file_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_entity_write),
):
    bank = _load_file(db, entity, file_id)
    audit.record(
        db, entity_id=entity.id, user=user, action="bank_file.deleted",
        object_type="bank_file", object_id=str(bank.id),
        summary=f"Deleted bank file {bank.filename!r} for {bank.period_month:%b %Y}",
    )
    db.delete(bank)
    db.commit()
    return ok({"deleted": True})


@router.get("/bank/reconcile")
def reconcile_bank(
    file_id: uuid.UUID,
    tolerance: float = Query(default=1.0, ge=0, le=100000),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    """The bank file against the register, employee by employee."""
    bank = _load_file(db, entity, file_id)
    profile = db.get(BankFileProfile, bank.profile_id) if bank.profile_id else None
    return ok(
        reconciliation.bank_reconciliation(
            db, entity.id, bank.period_month, bank,
            tolerance=Decimal(str(tolerance)),
            id_transform=getattr(profile, "employee_id_transform", "trim"),
        )
    )


# ---------------------------------------------------------------------------
# JV templates
# ---------------------------------------------------------------------------
def _rule_out(rule: JvRule) -> dict:
    return {
        "id": str(rule.id), "sequence": rule.sequence, "label": rule.label,
        "account_code": rule.account_code, "account_name": rule.account_name,
        "side": rule.side, "measures": list(rule.measures or []),
        "filters": rule.filters or {}, "cost_center_from": rule.cost_center_from,
        "active": rule.active, "note": rule.note,
    }


def _template_out(template: JvTemplate, with_rules: bool = True) -> dict:
    payload = {
        "id": str(template.id), "name": template.name, "note": template.note,
        "state": template.state, "is_current": template.is_current,
        "posting_basis": template.posting_basis, "split_mode": template.split_mode,
        "group_by": template.group_by, "detail_level": template.detail_level,
        "sign_convention": template.sign_convention,
        "net_pay_source": template.net_pay_source,
        "voucher_date_rule": template.voucher_date_rule,
        "voucher_type": template.voucher_type,
        "narration_template": template.narration_template,
        "export_format": template.export_format,
        "balance_tolerance": float(template.balance_tolerance),
        "rounding_mode": template.rounding_mode,
        "rounding_account": template.rounding_account,
        "approved_by": template.approved_by_email,
        "approved_at": template.approved_at.isoformat() if template.approved_at else None,
        "created_at": template.created_at.isoformat() if template.created_at else None,
        "rule_count": len(template.rules or []),
    }
    if with_rules:
        payload["rules"] = [_rule_out(r) for r in (template.rules or [])]
    return payload


def _load_template(db: Session, entity: Entity, template_id: uuid.UUID) -> JvTemplate:
    template = db.get(JvTemplate, template_id)
    if template is None or template.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="JV template not found")
    return template


def _apply_rules(db: Session, template: JvTemplate, rules: list[Any]) -> None:
    for existing in list(template.rules or []):
        db.delete(existing)
    template.rules = []
    for index, rule in enumerate(rules):
        data = rule if isinstance(rule, dict) else rule.model_dump()
        db.add(
            JvRule(
                template_id=template.id, entity_id=template.entity_id, sequence=index,
                label=str(data.get("label") or f"Line {index + 1}")[:160],
                account_code=str(data.get("account_code") or "")[:64],
                account_name=(data.get("account_name") or None),
                side=str(data.get("side") or "debit"),
                measures=list(data.get("measures") or []),
                filters=dict(data.get("filters") or {}),
                cost_center_from=data.get("cost_center_from"),
                active=bool(data.get("active", True)),
                note=data.get("note"),
            )
        )


@router.get("/jv/templates")
def list_templates(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    templates = (
        db.query(JvTemplate)
        .filter(JvTemplate.entity_id == entity.id)
        .order_by(JvTemplate.is_current.desc(), JvTemplate.created_at.desc())
        .all()
    )
    return ok({"templates": [_template_out(t, with_rules=False) for t in templates]})


@router.get("/jv/templates/{template_id}")
def get_template(
    template_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    return ok(_template_out(_load_template(db, entity, template_id)))


@router.post("/jv/templates")
def create_template(
    body: TemplateBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_entity_write),
):
    """Create a template, either rule by rule or from one of the supplied ones."""
    rules: list[Any] = list(body.rules)
    if body.from_preset:
        preset_rules = jv_builder.preset_rules(body.from_preset)
        if not preset_rules:
            raise HTTPException(status_code=400, detail=f"Unknown template: {body.from_preset}")
        rules = preset_rules
    _check_template(body.model_copy(update={"rules": [
        RuleBody(**r) if isinstance(r, dict) else r for r in rules
    ]}))

    existing = (
        db.query(JvTemplate)
        .filter(JvTemplate.entity_id == entity.id, JvTemplate.name == body.name.strip())
        .first()
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"A template named {body.name!r} already exists")

    data = body.model_dump(exclude={"rules", "from_preset", "name", "balance_tolerance"})
    template = JvTemplate(
        entity_id=entity.id, created_by_user_id=user.id, name=body.name.strip(),
        balance_tolerance=Decimal(str(body.balance_tolerance)), **data,
    )
    db.add(template)
    db.flush()
    _apply_rules(db, template, rules)
    audit.record(
        db, entity_id=entity.id, user=user, action="jv_template.created",
        object_type="jv_template", object_id=str(template.id),
        summary=f"Created JV template {template.name!r} with {len(rules)} rules",
        detail={"from_preset": body.from_preset},
    )
    db.commit()
    db.refresh(template)
    return ok(_template_out(template))


@router.put("/jv/templates/{template_id}")
def update_template(
    template_id: uuid.UUID,
    body: TemplateBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_entity_write),
):
    """
    Change a template.

    An approved template edited back to a draft rather than silently changed
    under the approval it already has: the mapping that posts to the ledger is
    re-approved when it changes, which is the point of approving it at all.
    """
    _check_template(body)
    template = _load_template(db, entity, template_id)
    was_approved = template.state == "approved"

    for key, value in body.model_dump(
        exclude={"rules", "from_preset", "name", "balance_tolerance"}
    ).items():
        setattr(template, key, value)
    template.name = body.name.strip()
    template.balance_tolerance = Decimal(str(body.balance_tolerance))
    if was_approved:
        template.state = "draft"
        template.is_current = False
        template.approved_at = None
        template.approved_by_email = None
        template.approved_by_user_id = None

    _apply_rules(db, template, list(body.rules))
    audit.record(
        db, entity_id=entity.id, user=user, action="jv_template.updated",
        object_type="jv_template", object_id=str(template.id),
        summary=f"Updated JV template {template.name!r}"
                + (" — approval withdrawn, it needs approving again" if was_approved else ""),
    )
    db.commit()
    db.refresh(template)
    return ok(_template_out(template))


@router.post("/jv/templates/{template_id}/approve")
def approve_template(
    template_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_entity_admin),
    entity: Entity = Depends(get_current_entity),
):
    """
    Approve a template as the one this entity posts with.

    Owners and managers only. This mapping decides what reaches the general
    ledger, and an analyst who can edit it is deliberately not the person who
    can bless it.
    """
    template = _load_template(db, entity, template_id)
    if not template.rules:
        raise HTTPException(
            status_code=409,
            detail="A template with no rules cannot be approved — it would post nothing.",
        )

    for other in db.query(JvTemplate).filter(
        JvTemplate.entity_id == entity.id, JvTemplate.is_current.is_(True)
    ).all():
        other.is_current = False

    template.state = "approved"
    template.is_current = True
    template.approved_by_user_id = user.id
    template.approved_by_email = user.email
    template.approved_at = datetime.now(UTC)

    audit.record(
        db, entity_id=entity.id, user=user, action="jv_template.approved",
        object_type="jv_template", object_id=str(template.id),
        summary=f"Approved JV template {template.name!r} as the current mapping",
    )
    db.commit()
    db.refresh(template)
    return ok(_template_out(template))


@router.delete("/jv/templates/{template_id}")
def delete_template(
    template_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_entity_admin),
    entity: Entity = Depends(get_current_entity),
):
    template = _load_template(db, entity, template_id)
    if template.state == "approved":
        raise HTTPException(
            status_code=409,
            detail="An approved template cannot be deleted. Approve a newer one to "
                   "supersede it — the vouchers posted under this mapping stay explainable.",
        )
    audit.record(
        db, entity_id=entity.id, user=user, action="jv_template.deleted",
        object_type="jv_template", object_id=str(template.id),
        summary=f"Deleted draft JV template {template.name!r}",
    )
    db.delete(template)
    db.commit()
    return ok({"deleted": True})


# ---------------------------------------------------------------------------
# The voucher itself
# ---------------------------------------------------------------------------
def _resolve_template(db: Session, entity: Entity, template_id: uuid.UUID | None) -> JvTemplate:
    if template_id is not None:
        return _load_template(db, entity, template_id)
    current = (
        db.query(JvTemplate)
        .filter(JvTemplate.entity_id == entity.id, JvTemplate.is_current.is_(True))
        .first()
    )
    if current is None:
        raise HTTPException(
            status_code=404,
            detail="No JV template is approved for this entity. Create one from a "
                   "supplied template and approve it, or name a template explicitly.",
        )
    return current


@router.get("/jv/preview")
def preview_jv(
    period: str,
    template_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    """The voucher for a month, built but not posted."""
    template = _resolve_template(db, entity, template_id)
    document = jv_builder.build_jv(db, entity.id, _period(period), template)
    payload = document.as_dict()
    payload["template"] = _template_out(template, with_rules=False)
    return ok(payload)


@router.get("/jv/reconcile")
def reconcile_jv(
    period: str,
    template_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    """The voucher against the month's payroll cost, and what does not agree."""
    template = _resolve_template(db, entity, template_id)
    payload = reconciliation.jv_reconciliation(db, entity.id, _period(period), template)
    payload["template"] = _template_out(template, with_rules=False)
    return ok(payload)


@router.get("/jv/export")
def export_jv(
    period: str,
    template_id: uuid.UUID | None = Query(default=None),
    fmt: str | None = Query(default=None, alias="format"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    """
    The voucher as an import file.

    Shaped like the target system's import layout, which is not the same as
    being that system's specification. Run the first month through the target
    system's own import preview before trusting it.
    """
    template = _resolve_template(db, entity, template_id)
    period_month = _period(period)
    chosen = fmt or template.export_format
    allowed = {k for k, _, _ in jv_builder.EXPORT_FORMATS}
    if chosen not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown export format {chosen!r}. Choose one of: {', '.join(sorted(allowed))}.",
        )

    document = jv_builder.build_jv(db, entity.id, period_month, template)
    if chosen == "json":
        return ok(document.as_dict())

    body = jv_builder.export_csv(document, chosen, template.sign_convention)
    name = f"payroll-jv-{period_month:%Y-%m}-{chosen}.csv"
    return StreamingResponse(
        io.BytesIO(body.encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------
def _run_out(run: ReconRun, count: int | None = None) -> dict:
    return {
        "id": str(run.id), "period": run.period_month.isoformat(),
        "period_label": run.period_month.strftime("%b %Y"),
        "kind": run.kind, "state": run.state, "summary": run.summary or {},
        "bank_file_id": str(run.bank_file_id) if run.bank_file_id else None,
        "jv_template_id": str(run.jv_template_id) if run.jv_template_id else None,
        "exception_count": count if count is not None else len(run.exceptions or []),
        "created_by": run.created_by_email,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "closed_by": run.closed_by_email,
        "closed_at": run.closed_at.isoformat() if run.closed_at else None,
    }


@router.post("/runs")
def create_run(
    body: RunBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_entity_write),
):
    """
    Run a reconciliation and keep the result.

    Kept rather than recomputed: the register, the bank file and the template
    can all change afterwards, and what the reconciliation said at the time is
    the thing anyone will later be asked about.
    """
    if body.kind not in ("bank", "jv"):
        raise HTTPException(status_code=400, detail="kind must be 'bank' or 'jv'")

    if body.kind == "bank":
        if body.bank_file_id is None:
            raise HTTPException(status_code=400, detail="A bank reconciliation needs a bank file")
        bank = _load_file(db, entity, body.bank_file_id)
        profile = db.get(BankFileProfile, bank.profile_id) if bank.profile_id else None
        result = reconciliation.bank_reconciliation(
            db, entity.id, bank.period_month, bank,
            id_transform=getattr(profile, "employee_id_transform", "trim"),
        )
        run = reconciliation.save_run(
            db, entity.id, bank.period_month, kind="bank", result=result, user=user,
            bank_file_id=bank.id,
        )
    else:
        template = _resolve_template(db, entity, body.jv_template_id)
        result = reconciliation.jv_reconciliation(db, entity.id, body.period_month, template)
        run = reconciliation.save_run(
            db, entity.id, body.period_month, kind="jv", result=result, user=user,
            jv_template_id=template.id,
        )

    counts = result.get("counts", {})
    audit.record(
        db, entity_id=entity.id, user=user, action=f"reconciliation.{body.kind}",
        object_type="recon_run", object_id=str(run.id),
        summary=f"Reconciled {body.kind} for {run.period_month:%b %Y} — "
                f"{counts.get('total', 0)} exception(s)",
        detail=counts,
    )
    db.commit()
    db.refresh(run)
    payload = _run_out(run)
    payload["result"] = result
    return ok(payload)


@router.get("/runs")
def list_runs(
    period: str | None = Query(default=None),
    kind: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    query = db.query(ReconRun).filter(ReconRun.entity_id == entity.id)
    if period:
        query = query.filter(ReconRun.period_month == _period(period))
    if kind:
        query = query.filter(ReconRun.kind == kind)
    runs = query.order_by(ReconRun.period_month.desc(), ReconRun.created_at.desc()).all()
    return ok({"runs": [_run_out(r) for r in runs]})


@router.get("/runs/{run_id}")
def get_run(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    run = db.get(ReconRun, run_id)
    if run is None or run.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Reconciliation not found")
    items = (
        db.query(ReconException)
        .filter(ReconException.run_id == run.id)
        .order_by(ReconException.severity, ReconException.code)
        .all()
    )
    payload = _run_out(run, count=len(items))
    payload["exceptions"] = [
        {
            "code": e.code, "severity": e.severity, "title": e.title, "detail": e.detail,
            "label": reconciliation.KIND_BY_CODE[e.code].label
            if e.code in reconciliation.KIND_BY_CODE else e.code,
            "action": reconciliation.KIND_BY_CODE[e.code].action
            if e.code in reconciliation.KIND_BY_CODE else None,
            "employee_id": e.employee_id, "employee_name": e.employee_name,
            "scope": e.scope,
            "expected": None if e.expected is None else float(e.expected),
            "actual": None if e.actual is None else float(e.actual),
            "difference": None if e.difference is None else float(e.difference),
            "context": e.context or {},
        }
        for e in items
    ]
    return ok(payload)


@router.post("/runs/{run_id}/close")
def close_run(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_entity_admin),
    entity: Entity = Depends(get_current_entity),
):
    """
    Mark a reconciliation reviewed.

    Closing does not mean the exceptions went away — they stay on the record
    exactly as found. It means a named person looked at them and accepted the
    position, which is a different and more useful claim.
    """
    run = db.get(ReconRun, run_id)
    if run is None or run.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Reconciliation not found")
    if run.state == "closed":
        return ok(_run_out(run))

    run.state = "closed"
    run.closed_by_email = user.email
    run.closed_at = datetime.now(UTC)
    audit.record(
        db, entity_id=entity.id, user=user, action="reconciliation.closed",
        object_type="recon_run", object_id=str(run.id),
        summary=f"Closed the {run.kind} reconciliation for {run.period_month:%b %Y}",
        detail=run.summary or {},
    )
    db.commit()
    db.refresh(run)
    return ok(_run_out(run))


# ---------------------------------------------------------------------------
# Where the month stands
# ---------------------------------------------------------------------------
@router.get("/overview")
def overview(
    period: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    """
    One month, from register to bank to ledger.

    Deliberately says what is *missing* as well as what does not match: a month
    with no bank file uploaded is unreconciled, and reporting it as clean
    because nothing disagreed would be the most dangerous answer this module
    could give.
    """
    from app.services.analytics import available_periods

    periods = available_periods(db, entity.id)
    period_list = periods.get("periods", []) if isinstance(periods, dict) else []
    if period:
        period_month = _period(period)
    elif period_list:
        period_month = _period(str(period_list[-1].get("key") or period_list[-1]))
    else:
        return ok({
            "period": None,
            "ready": False,
            "message": "No salary register has been uploaded yet, so there is nothing "
                       "to reconcile.",
            "periods": period_list,
        })

    register = reconciliation.register_net(db, entity.id, period_month)
    due_total = sum((e.expected for e in register), Decimal("0"))

    files = (
        db.query(BankFile)
        .filter(BankFile.entity_id == entity.id, BankFile.period_month == period_month)
        .order_by(BankFile.created_at.desc())
        .all()
    )
    template = (
        db.query(JvTemplate)
        .filter(JvTemplate.entity_id == entity.id, JvTemplate.is_current.is_(True))
        .first()
    )
    runs = (
        db.query(ReconRun)
        .filter(ReconRun.entity_id == entity.id, ReconRun.period_month == period_month)
        .order_by(ReconRun.created_at.desc())
        .all()
    )

    return ok({
        "period": period_month.isoformat(),
        "period_label": period_month.strftime("%b %Y"),
        "periods": period_list,
        "register": {
            "employees": len(register),
            "net_due": float(due_total),
            "stated_net_available": any(e.stated_net is not None for e in register),
        },
        "bank": {
            "files": [_file_out(f) for f in files],
            "paid_total": float(sum((f.total_amount for f in files), Decimal("0"))),
            "ready": bool(files),
            "message": None if files else
            "No bank file has been uploaded for this month, so payments are unreconciled.",
        },
        "jv": {
            "template": _template_out(template, with_rules=False) if template else None,
            "ready": template is not None,
            "message": None if template else
            "No JV template is approved, so nothing can be posted to the ledger.",
        },
        "runs": [_run_out(r) for r in runs],
        "reconciled": bool(files) and template is not None and any(
            r.state == "closed" for r in runs
        ),
    })
