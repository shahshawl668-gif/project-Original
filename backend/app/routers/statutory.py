from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.envelope import ok
from app.models import StatutorySettings, User
from app.schemas.statutory import StatutorySettingsOut, StatutorySettingsUpdate

router = APIRouter()


def _get_or_create(db: Session, user_id) -> StatutorySettings:
    row = db.query(StatutorySettings).filter(StatutorySettings.user_id == user_id).first()
    if row:
        return row
    row = StatutorySettings(user_id=user_id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("")
def get_statutory(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = _get_or_create(db, user.id)
    return ok(StatutorySettingsOut.model_validate(row).model_dump())


@router.put("")
def update_statutory(
    body: StatutorySettingsUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = _get_or_create(db, user.id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(row, k, v)
    db.add(row)
    db.commit()
    db.refresh(row)
    return ok(StatutorySettingsOut.model_validate(row).model_dump())
