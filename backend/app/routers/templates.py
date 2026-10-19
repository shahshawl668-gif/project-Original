"""Download the import templates as CSV or Excel, built from this company's components."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_entity, get_current_user
from app.models import Entity, User
from app.services import templates as template_service

router = APIRouter()

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/{filename}")
def download_template(
    filename: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    """``/api/templates/register.csv`` or ``.xlsx``; also ctc, attendance and master."""
    kind, _, fmt = filename.rpartition(".")
    if fmt not in ("csv", "xlsx"):
        raise HTTPException(status_code=404, detail="Templates are offered as .csv or .xlsx")
    try:
        spec = template_service.table(db, entity, kind)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown template") from None
    if fmt == "csv":
        body, media = template_service.as_csv(spec), "text/csv; charset=utf-8"
    else:
        body, media = template_service.as_xlsx(spec), XLSX
    return Response(
        content=body, media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{spec["file"]}-template.{fmt}"'},
    )
