from fastapi import APIRouter, Depends
from pymongo.database import Database

from app.database import get_db
from app.deps import get_current_user
from app.envelope import ok
from app.models import StatutorySettings, User
from app.schemas.statutory import StatutorySettingsOut, StatutorySettingsUpdate

router = APIRouter()


def _get_or_create(db: Database, user_id) -> StatutorySettings:
    row = StatutorySettings.find_one(db, {"user_id": user_id})
    if row:
        return row
    row = StatutorySettings(user_id=user_id)
    row.insert(db)
    return row


@router.get("")
def get_statutory(db: Database = Depends(get_db), user: User = Depends(get_current_user)):
    row = _get_or_create(db, user.id)
    return ok(StatutorySettingsOut.model_validate(row).model_dump())


@router.put("")
def update_statutory(
    body: StatutorySettingsUpdate,
    db: Database = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = _get_or_create(db, user.id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(row, k, v)
    row.save(db)
    return ok(StatutorySettingsOut.model_validate(row).model_dump())
