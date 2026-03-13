from __future__ import annotations

from email.utils import parseaddr
from typing import Literal

from pydantic import BaseModel, Field, field_validator

SourceHealthStatusLiteral = Literal["healthy", "attention", "disconnected"]


class OnboardingRegisterRequest(BaseModel):
    notify_email: str = Field(min_length=3, max_length=255)

    model_config = {"extra": "forbid"}

    @field_validator("notify_email")
    @classmethod
    def validate_notify_email(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("notify_email must not be blank")
        if not _is_valid_email_address(stripped):
            raise ValueError("notify_email must be a valid email address")
        return stripped


class SourceHealthSummaryResponse(BaseModel):
    status: SourceHealthStatusLiteral
    message: str
    affected_source_id: int | None = None
    affected_provider: str | None = None


class OnboardingStatusResponse(BaseModel):
    stage: Literal["needs_user", "needs_source_connection", "ready"]
    message: str
    registered_user_id: int | None = None
    first_source_id: int | None = None
    source_health: SourceHealthSummaryResponse | None = None


class OnboardingRegisterResponse(BaseModel):
    status: Literal["accepted"]
    user_id: int
    stage: Literal["needs_source_connection", "ready"]
    first_source_id: int | None = None


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
