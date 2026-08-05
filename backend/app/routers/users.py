from fastapi import APIRouter, Depends
from pydantic import BaseModel
from pymongo.database import Database

from app.database import get_db
from app.deps import get_current_user
from app.envelope import ok
from app.models import User
from app.schemas.auth import UserOut

router = APIRouter()


class UserProfileUpdate(BaseModel):
    company_name: str | None = None


@router.patch("/me")
def update_me(
    body: UserProfileUpdate,
    db: Database = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if body.company_name is not None:
        user.company_name = body.company_name
    user.save(db)
    return ok(UserOut.model_validate(user).model_dump())
