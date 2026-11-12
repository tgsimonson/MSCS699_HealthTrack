"""authentication schemas"""
from __future__ import annotations

import uuid

from pydantic import Field

from app.models.enums import UserRole
from app.schemas.common import ApiModel


class UserSummary(ApiModel):
    user_id: uuid.UUID
    role: UserRole
    first_name: str
    last_name: str
    credentials: str | None = None


class TokenResponse(ApiModel):
    access_token: str = Field(description="Signed JWT, short-lived.")
    token_type: str = Field(default="bearer")
    expires_in: int = Field(description="Seconds until the access token expires.", examples=[900])
    refresh_token: str = Field(description="Opaque token; stored server-side only as a SHA-256 hash; rotated on use.")
    refresh_expires_in: int = Field(examples=[43200])
    user: UserSummary


class RefreshRequest(ApiModel):
    refresh_token: str = Field(min_length=20, max_length=200)


class MeOut(UserSummary):
    email: str
    is_active: bool
    mfa_enabled: bool
