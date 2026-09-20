from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_entity, get_current_user, require_entity_write
from app.envelope import ok
from app.models import Entity, StatutorySettings, User
from app.schemas.statutory import StatutorySettingsOut, StatutorySettingsUpdate

router = APIRouter()


def _get_or_create(db: Session, entity_id) -> StatutorySettings:
    row = db.query(StatutorySettings).filter(StatutorySettings.entity_id == entity_id).first()
    if row:
        return row
    row = StatutorySettings(entity_id=entity_id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("")
def get_statutory(db: Session = Depends(get_db), entity: Entity = Depends(get_current_entity)):
    row = _get_or_create(db, entity.id)
    return ok(StatutorySettingsOut.model_validate(row).model_dump())


@router.put("")
def update_statutory(
    body: StatutorySettingsUpdate,
    db: Session = Depends(get_db),
    entity: Entity = Depends(require_entity_write),
):
    row = _get_or_create(db, entity.id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(row, k, v)
    db.add(row)
    db.commit()
    db.refresh(row)
    return ok(StatutorySettingsOut.model_validate(row).model_dump())
