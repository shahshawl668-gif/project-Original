import json
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_entity, get_current_user, require_entity_write
from app.envelope import ok
from app.models import ComponentConfig, CtcRecord, CtcUpload, Entity, User
from app.schemas.ctc import CtcCommitRequest, CtcParseResponse, CtcRecordOut, CtcUploadOut
from app.services import ingest
from app.services.ctc_parse import parse_ctc_file
from app.services.payroll_parse import normalize_col

router = APIRouter()


@router.post("/upload")
async def upload_ctc(
    file: UploadFile = File(...),
    meta: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_entity_write),
):
    try:
        payload = json.loads(meta)
        eff = payload.get("default_effective_from")
        eff_d = date.fromisoformat(eff) if eff else None
    except (ValueError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="Invalid meta JSON")

    comps = db.query(ComponentConfig).filter(ComponentConfig.entity_id == entity.id).all()
    if not comps:
        raise HTTPException(
            status_code=400,
            detail="Configure salary components before uploading CTC.",
        )
    component_keys = {normalize_col(c.component_name) for c in comps}

    raw = await file.read()
    try:
        columns, records = parse_ctc_file(raw, file.filename or "ctc.csv", component_keys, eff_d)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    known = component_keys | {
        "employee_id",
        "emp_id",
        "employee_code",
        "employee_name",
        "name",
        "effective_from",
        "effective_date",
        "ctc_effective_from",
        "annual_ctc",
        "ctc",
        "location",
        "department",
        "designation",
    }
    unknown = [c for c in columns if c not in known]
    warnings: list[str] = []
    if not records:
        warnings.append("No usable rows found. Ensure employee_id and effective_from are present.")

    out = CtcParseResponse(
        columns=columns,
        records=records,
        unknown_columns=unknown,
        warnings=warnings,
    )
    return ok(out.model_dump())


@router.post("/commit")
def commit_ctc(
    body: CtcCommitRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_entity_write),
):
    if not body.records:
        raise HTTPException(status_code=400, detail="No records to commit.")

    result = ingest.commit_ctc(
        db, entity=entity, user=user,
        records=[r.model_dump() for r in body.records],
        filename=body.filename,
        default_effective_from=body.default_effective_from,
        lineage=ingest.file_lineage(body.filename, actor=user.email),
    )
    db.commit()
    upload = result["upload"]
    db.refresh(upload)
    payload = CtcUploadOut.model_validate(upload).model_dump()
    payload["counts"] = result["counts"]
    payload["duplicates_skipped"] = [
        f"{d['employee_id']} @ {d['effective_from']}" for d in result["duplicates"]
    ]
    return ok(payload)


@router.get("/uploads")
def list_uploads(db: Session = Depends(get_db), user: User = Depends(get_current_user), entity: Entity = Depends(get_current_entity)):
    rows = (
        db.query(CtcUpload)
        .filter(CtcUpload.entity_id == entity.id)
        .order_by(CtcUpload.created_at.desc())
        .all()
    )
    return ok([CtcUploadOut.model_validate(r).model_dump() for r in rows])


@router.get("/uploads/{upload_id}")
def list_records(
    upload_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    rows = (
        db.query(CtcRecord)
        .filter(CtcRecord.entity_id == entity.id, CtcRecord.upload_id == upload_id)
        .order_by(CtcRecord.employee_id)
        .all()
    )
    return ok([CtcRecordOut.model_validate(r).model_dump() for r in rows])


@router.get("/latest")
def latest_for_employee(
    employee_id: str,
    as_of: date | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    q = db.query(CtcRecord).filter(CtcRecord.entity_id == entity.id, CtcRecord.employee_id == employee_id)
    if as_of:
        q = q.filter(CtcRecord.effective_from <= as_of)
    row = q.order_by(CtcRecord.effective_from.desc()).first()
    if row is None:
        return ok(None)
    return ok(CtcRecordOut.model_validate(row).model_dump())
