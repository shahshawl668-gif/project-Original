import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.services.password_policy import check as _password_policy


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    company_name: str | None = None

    _policy = field_validator("password")(_password_policy)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(max_length=256)
    workspace_slug: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$|^[a-z0-9]$")


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class PlatformInviteAccept(BaseModel):
    token: str
    password: str = Field(min_length=8, max_length=128)

    _policy = field_validator("password")(_password_policy)


class SupportSessionRequest(BaseModel):
    org_id: uuid.UUID


class UserOut(BaseModel):
    id: uuid.UUID
    email: EmailStr
    company_name: str | None
    role: str
    platform_role: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)

    _policy = field_validator("new_password")(_password_policy)


class AdminRoleUpdate(BaseModel):
    """Body for admin-only PATCH to change a human user's role."""

    role: Literal["admin", "user"]


class MfaChallenge(BaseModel):
    """Answer to a correct password when the account has two-step sign-in."""

    mfa_required: Literal[True] = True
    mfa_token: str


class MfaVerify(BaseModel):
    mfa_token: str
    code: str = Field(min_length=6, max_length=32)


class PasswordConfirm(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class MfaEnable(BaseModel):
    code: str = Field(min_length=6, max_length=12)


class MfaChange(BaseModel):
    password: str = Field(min_length=1, max_length=256)
    code: str = Field(min_length=6, max_length=32)
