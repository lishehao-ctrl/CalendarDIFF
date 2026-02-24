from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator

from app.modules.users.schemas import EMAIL_PATTERN


class OnboardingTermPayload(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=128)
    starts_on: date
    ends_on: date

    model_config = {"extra": "forbid"}

    @field_validator("code", "label")
    @classmethod
    def validate_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class OnboardingIcsPayload(BaseModel):
    url: HttpUrl

    model_config = {"extra": "forbid"}


class OnboardingRegisterRequest(BaseModel):
    notify_email: str = Field(min_length=3, max_length=255)
    term: OnboardingTermPayload
    ics: OnboardingIcsPayload

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


class OnboardingStatusResponse(BaseModel):
    stage: Literal["needs_user", "needs_term", "needs_ics", "needs_baseline", "ready"]
    message: str
    registered_user_id: int | None = None
    first_input_id: int | None = None
    last_error: str | None = None


class OnboardingRegisterResponse(BaseModel):
    status: Literal["ready"]
    user_id: int
    term_id: int
    input_id: int
    is_baseline_sync: bool
    changes_created: int
