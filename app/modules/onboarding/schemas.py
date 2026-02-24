from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator

from app.modules.users.schemas import EMAIL_PATTERN

class OnboardingIcsPayload(BaseModel):
    url: HttpUrl

    model_config = {"extra": "forbid"}


class OnboardingRegisterRequest(BaseModel):
    notify_email: str = Field(min_length=3, max_length=255)
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
    stage: Literal["needs_user", "needs_ics", "needs_baseline", "ready"]
    message: str
    registered_user_id: int | None = None
    first_input_id: int | None = None
    last_error: str | None = None


class OnboardingRegisterResponse(BaseModel):
    status: Literal["ready"]
    user_id: int
    input_id: int
    is_baseline_sync: bool
    changes_created: int
