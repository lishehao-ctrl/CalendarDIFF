from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.modules.users.email_utils import is_valid_email_address


class UserResponse(BaseModel):
    id: int
    email: str | None
    notify_email: str | None
    calendar_delay_seconds: int
    created_at: datetime


class UserUpdateRequest(BaseModel):
    email: str | None = Field(default=None, max_length=255)
    notify_email: str | None = Field(default=None, max_length=255)
    calendar_delay_seconds: int | None = Field(default=None, ge=0, le=3600)

    model_config = {"extra": "forbid"}

    @field_validator("email", "notify_email")
    @classmethod
    def validate_optional_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            return None
        if not is_valid_email_address(stripped):
            raise ValueError("must be a valid email address")
        return stripped
