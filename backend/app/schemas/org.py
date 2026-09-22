from __future__ import annotations

import uuid
from datetime import datetime

from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class EntityCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    legal_name: str | None = Field(default=None, max_length=255)
    code: str | None = Field(default=None, max_length=64)
    pf_establishment_code: str | None = Field(default=None, max_length=64)
    esic_employer_code: str | None = Field(default=None, max_length=64)
    tan: str | None = Field(default=None, max_length=16)
    pan: str | None = Field(default=None, max_length=16)
    cin: str | None = Field(default=None, max_length=32)
    primary_state: str | None = Field(default=None, max_length=100)


class EntityUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    legal_name: str | None = Field(default=None, max_length=255)
    pf_establishment_code: str | None = Field(default=None, max_length=64)
    esic_employer_code: str | None = Field(default=None, max_length=64)
    tan: str | None = Field(default=None, max_length=16)
    pan: str | None = Field(default=None, max_length=16)
    cin: str | None = Field(default=None, max_length=32)
    primary_state: str | None = Field(default=None, max_length=100)
    is_active: bool | None = None


class EntityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    legal_name: str | None
    code: str
    pf_establishment_code: str | None
    esic_employer_code: str | None
    tan: str | None
    pan: str | None
    cin: str | None
    primary_state: str | None
    is_active: bool
    created_at: datetime | None


class OrganizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    org_type: str
    created_at: datetime | None


class OrganizationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    org_type: str | None = Field(default=None, pattern="^(practice|enterprise)$")


class MembershipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    role: str
    email: str | None = None


class ContextOut(BaseModel):
    """Everything the client needs to render the entity switcher on first load."""

    organization: OrganizationOut | None
    role: str | None
    active_entity: EntityOut | None
    entities: list[EntityOut]


class InvitationCreate(BaseModel):
    """An offer of a seat. The token it produces is shown once and never again."""

    email: EmailStr
    role: Literal["owner", "manager", "analyst", "viewer"] = "viewer"
    # Empty means the whole organization, which is how EntityAccess already reads.
    entity_ids: list[uuid.UUID] = Field(default_factory=list)
    note: str | None = Field(default=None, max_length=500)
    expiry_days: int = Field(default=7, ge=1, le=90)


class InvitationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    role: str
    state: str
    entity_ids: list[str] = Field(default_factory=list)
    note: str | None = None
    invited_by: str | None = None
    created_at: datetime | None = None
    expires_at: datetime | None = None
    accepted_at: datetime | None = None


class InvitationIssued(InvitationOut):
    """
    The one and only sight of the token.

    Returned on create and resend. Nothing else in the API can produce it again,
    because only its hash is stored.
    """

    token: str


class InvitationPreview(BaseModel):
    """What an invitee is shown before they decide — deliberately minimal."""

    organization: str
    role: str
    email: str
    invited_by: str | None = None
    expires_at: datetime | None = None
    entity_names: list[str] = Field(default_factory=list)
    account_exists: bool


class InvitationAccept(BaseModel):
    token: str = Field(min_length=1, max_length=512)


class InvitationRegister(BaseModel):
    """Accept an invitation by creating the account it was sent to."""

    token: str = Field(min_length=1, max_length=512)
    password: str = Field(min_length=8, max_length=128)


class MemberUpdate(BaseModel):
    """
    Change a member's seat.

    Both fields are optional and independent: a role change alone leaves entity
    scoping untouched, and an ``entity_ids`` of ``[]`` explicitly widens them to
    the whole organization rather than meaning "no change".
    """

    role: Literal["owner", "manager", "analyst", "viewer"] | None = None
    entity_ids: list[uuid.UUID] | None = None


class MemberOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    email: str | None = None
    role: str
    entity_ids: list[str] = Field(default_factory=list)
    is_you: bool = False
    joined_at: datetime | None = None
