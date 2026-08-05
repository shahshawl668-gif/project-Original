"""User, refresh-token and password-reset documents."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from app.models.base import Document, utcnow


@dataclass
class User(Document):
    COLLECTION = "users"

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    email: str = ""
    password_hash: str = ""
    company_name: str | None = None
    # system | admin | user — system user is the built-in tenant fallback
    role: str = "user"
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)


@dataclass
class RefreshToken(Document):
    COLLECTION = "refresh_tokens"

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    user_id: uuid.UUID | None = None
    token_hash: str = ""
    expires_at: datetime | None = None
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class PasswordResetToken(Document):
    COLLECTION = "password_reset_tokens"

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    user_id: uuid.UUID | None = None
    token_hash: str = ""
    expires_at: datetime | None = None
    used_at: datetime | None = None
    created_at: datetime = field(default_factory=utcnow)
