from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.modules.users.email_utils import is_valid_email_address

class OnboardingRegisterRequest(BaseModel):
    notify_email: str = Field(min_length=3, max_length=255)

    model_config = {"extra": "forbid"}

    @field_validator("notify_email")
    @classmethod
    def validate_notify_email(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("notify_email must not be blank")
        if not is_valid_email_address(stripped):
            raise ValueError("notify_email must be a valid email address")
        return stripped


class OnboardingStatusResponse(BaseModel):
    stage: Literal["needs_user", "needs_source_connection", "ready"]
    message: str
    registered_user_id: int | None = None
    first_source_id: int | None = None
    last_error: str | None = None


class OnboardingRegisterResponse(BaseModel):
    status: Literal["accepted"]
    user_id: int
    stage: Literal["needs_source_connection", "ready"]
    first_source_id: int | None = None
