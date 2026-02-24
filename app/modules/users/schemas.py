from __future__ import annotations

from datetime import date, datetime
import re

from pydantic import BaseModel, Field, field_validator

EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$")


class UserResponse(BaseModel):
    id: int
    email: str | None
    notify_email: str | None
    calendar_delay_seconds: int
    created_at: datetime


class UserCreateRequest(BaseModel):
    notify_email: str = Field(min_length=3, max_length=255)

    model_config = {"extra": "forbid"}

    @field_validator("notify_email")
    @classmethod
    def validate_notify_email(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("notify_email must not be blank")
        if not EMAIL_PATTERN.fullmatch(stripped):
            raise ValueError("notify_email must be a valid email address")
        return stripped


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
        if not EMAIL_PATTERN.fullmatch(stripped):
            raise ValueError("must be a valid email address")
        return stripped


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
