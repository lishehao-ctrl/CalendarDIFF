from __future__ import annotations

from datetime import datetime
from email.utils import parseaddr
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator

from app.modules.onboarding.schemas import OnboardingStageLiteral


class AuthRegisterRequest(BaseModel):
    notify_email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    timezone_name: str | None = Field(default=None, max_length=64)

    model_config = {"extra": "forbid"}

    @field_validator("notify_email")
    @classmethod
    def _validate_notify_email(cls, value: str) -> str:
        stripped = value.strip().lower()
        if not stripped:
            raise ValueError("notify_email must not be blank")
        if not _is_valid_email_address(stripped):
            raise ValueError("notify_email must be a valid email address")
        return stripped

    @field_validator("timezone_name")
    @classmethod
    def _validate_timezone_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_timezone_name(value)


class AuthLoginRequest(AuthRegisterRequest):
    password: str = Field(min_length=1, max_length=128)


class AuthSessionUserResponse(BaseModel):
    id: int
    notify_email: str
    timezone_name: str
    timezone_source: str
    created_at: datetime
    onboarding_stage: OnboardingStageLiteral
    first_source_id: int | None


class AuthSessionResponse(BaseModel):
    authenticated: Literal[True] = True
    user: AuthSessionUserResponse


class AuthLogoutResponse(BaseModel):
    logged_out: bool


def _is_valid_email_address(value: str | None) -> bool:
    if value is None:
        return False
    candidate = value.strip()
    if not candidate:
        return False
    if any(ch.isspace() for ch in candidate):
        return False
    _, parsed = parseaddr(candidate)
    if parsed != candidate:
        return False
    local, separator, domain = candidate.rpartition("@")
    if separator != "@":
        return False
    if not local or not domain or "." not in domain:
        return False
    if domain.startswith(".") or domain.endswith(".") or ".." in domain:
        return False
    return True


def _normalize_timezone_name(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("timezone_name must not be blank")
    try:
        ZoneInfo(stripped)
    except Exception as exc:
        raise ValueError("timezone_name must be a valid IANA timezone") from exc
    return stripped
