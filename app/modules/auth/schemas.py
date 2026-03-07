from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.modules.users.email_utils import is_valid_email_address


class AuthRegisterRequest(BaseModel):
    notify_email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=128)

    model_config = {"extra": "forbid"}

    @field_validator("notify_email")
    @classmethod
    def _validate_notify_email(cls, value: str) -> str:
        stripped = value.strip().lower()
        if not stripped:
            raise ValueError("notify_email must not be blank")
        if not is_valid_email_address(stripped):
            raise ValueError("notify_email must be a valid email address")
        return stripped


class AuthLoginRequest(AuthRegisterRequest):
    pass


class AuthSessionUserResponse(BaseModel):
    id: int
    notify_email: str
    timezone_name: str
    created_at: datetime
    onboarding_stage: Literal["needs_source_connection", "ready"]
    first_source_id: int | None


class AuthSessionResponse(BaseModel):
    authenticated: Literal[True] = True
    user: AuthSessionUserResponse


class AuthLogoutResponse(BaseModel):
    logged_out: bool
