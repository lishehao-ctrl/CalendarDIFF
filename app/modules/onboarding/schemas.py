from __future__ import annotations

from datetime import date, datetime
from email.utils import parseaddr
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.modules.sources.schemas import SourceRuntimeStateLiteral

SourceHealthStatusLiteral = Literal["healthy", "attention", "disconnected"]
OnboardingStageLiteral = Literal[
    "needs_user",
    "needs_canvas_ics",
    "needs_gmail_or_skip",
    "needs_monitoring_window",
    "ready",
]


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
    message_code: str
    message_params: dict = Field(default_factory=dict)
    affected_source_id: int | None = None
    affected_provider: str | None = None


class OnboardingMonitoringWindowResponse(BaseModel):
    monitor_since: date


class OnboardingSourceResponse(BaseModel):
    source_id: int
    provider: Literal["ics", "gmail"]
    connected: bool
    has_monitoring_window: bool
    runtime_state: SourceRuntimeStateLiteral
    oauth_account_email: str | None = None
    monitoring_window: OnboardingMonitoringWindowResponse | None = None


class OnboardingStatusResponse(BaseModel):
    stage: OnboardingStageLiteral
    message: str
    message_code: str
    message_params: dict = Field(default_factory=dict)
    registered_user_id: int | None = None
    first_source_id: int | None = None
    source_health: SourceHealthSummaryResponse | None = None
    canvas_source: OnboardingSourceResponse | None = None
    gmail_source: OnboardingSourceResponse | None = None
    gmail_skipped: bool = False
    monitoring_window: OnboardingMonitoringWindowResponse | None = None


class OnboardingRegisterResponse(BaseModel):
    status: Literal["accepted"]
    user_id: int
    stage: OnboardingStageLiteral
    first_source_id: int | None = None


class OnboardingCanvasIcsRequest(BaseModel):
    url: str = Field(min_length=1, max_length=4096)

    model_config = {"extra": "forbid"}

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("url must not be blank")
        return stripped


class OnboardingGmailOAuthRequest(BaseModel):
    label_id: str | None = Field(default="INBOX", max_length=128)
    return_to: Literal["onboarding", "sources"] = "onboarding"

    model_config = {"extra": "forbid"}

    @field_validator("label_id")
    @classmethod
    def validate_label_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class OnboardingGmailSkipRequest(BaseModel):
    model_config = {"extra": "forbid"}


class OnboardingMonitoringWindowRequest(BaseModel):
    monitor_since: date

    model_config = {"extra": "forbid"}


class OnboardingOAuthSessionCreateResponse(BaseModel):
    source_id: int
    provider: Literal["gmail"]
    authorization_url: str
    expires_at: datetime


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
