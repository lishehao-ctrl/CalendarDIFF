from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator


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


class UserTermSummary(BaseModel):
    id: int
    code: str
    label: str
    starts_on: date
    ends_on: date
    is_active: bool


class UserTermResponse(UserTermSummary):
    user_id: int
    created_at: datetime
    updated_at: datetime


class UserTermCreateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=128)
    starts_on: date
    ends_on: date
    is_active: bool = True

    model_config = {"extra": "forbid"}

    @field_validator("code", "label")
    @classmethod
    def validate_term_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class UserTermUpdateRequest(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=64)
    label: str | None = Field(default=None, min_length=1, max_length=128)
    starts_on: date | None = None
    ends_on: date | None = None
    is_active: bool | None = None

    model_config = {"extra": "forbid"}

    @field_validator("code", "label")
    @classmethod
    def validate_optional_term_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped
