import json
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.envelope import ok
from app.models import ComponentConfig, CtcRecord, CtcUpload, User
from app.schemas.ctc import CtcCommitRequest, CtcParseResponse, CtcRecordOut, CtcUploadOut
from app.services.ctc_parse import parse_ctc_file
from app.services.payroll_parse import normalize_col

router = APIRouter()


@router.post("/upload")
async def upload_ctc(
    file: UploadFile = File(...),
    meta: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        payload = json.loads(meta)
        eff = payload.get("default_effective_from")
        eff_d = date.fromisoformat(eff) if eff else None
    except (ValueError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="Invalid meta JSON")

    comps = db.query(ComponentConfig).filter(ComponentConfig.user_id == user.id).all()
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
):
    if not body.records:
        raise HTTPException(status_code=400, detail="No records to commit.")

    eff = body.default_effective_from or min(r.effective_from for r in body.records)

    upload = CtcUpload(
        user_id=user.id,
        effective_from=eff,
        filename=body.filename,
        employee_count=len(body.records),
    )
    db.add(upload)
    db.flush()

    for rec in body.records:
        existing = (
            db.query(CtcRecord)
            .filter(
                CtcRecord.user_id == user.id,
                CtcRecord.employee_id == rec.employee_id,
                CtcRecord.effective_from == rec.effective_from,
            )
            .first()
        )
        if existing:
            existing.upload_id = upload.id
            existing.employee_name = rec.employee_name
            existing.annual_components = rec.annual_components
            existing.annual_ctc = rec.annual_ctc
            db.add(existing)
        else:
            db.add(
                CtcRecord(
                    upload_id=upload.id,
                    user_id=user.id,
                    employee_id=rec.employee_id,
                    employee_name=rec.employee_name,
                    effective_from=rec.effective_from,
                    annual_components=rec.annual_components,
                    annual_ctc=rec.annual_ctc,
                )
            )

    db.commit()
    db.refresh(upload)
    return ok(CtcUploadOut.model_validate(upload).model_dump())


@router.get("/uploads")
def list_uploads(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (
        db.query(CtcUpload)
        .filter(CtcUpload.user_id == user.id)
        .order_by(CtcUpload.created_at.desc())
        .all()
    )
    return ok([CtcUploadOut.model_validate(r).model_dump() for r in rows])


@router.get("/uploads/{upload_id}")
def list_records(
    upload_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = (
        db.query(CtcRecord)
        .filter(CtcRecord.user_id == user.id, CtcRecord.upload_id == upload_id)
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
):
    q = db.query(CtcRecord).filter(CtcRecord.user_id == user.id, CtcRecord.employee_id == employee_id)
    if as_of:
        q = q.filter(CtcRecord.effective_from <= as_of)
    row = q.order_by(CtcRecord.effective_from.desc()).first()
    if row is None:
        return ok(None)
    return ok(CtcRecordOut.model_validate(row).model_dump())
