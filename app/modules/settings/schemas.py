from __future__ import annotations

from datetime import datetime
from email.utils import parseaddr
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator

from app.modules.common.language import DEFAULT_LANGUAGE_CODE, LanguageCodeLiteral, normalize_language_code


class UserResponse(BaseModel):
    id: int
    email: str | None
    notify_email: str | None
    timezone_name: str
    timezone_source: str
    language_code: LanguageCodeLiteral = DEFAULT_LANGUAGE_CODE
    calendar_delay_seconds: int
    created_at: datetime


class UserUpdateRequest(BaseModel):
    email: str | None = Field(default=None, max_length=255)
    notify_email: str | None = Field(default=None, max_length=255)
    timezone_name: str | None = Field(default=None, max_length=64)
    timezone_source: str | None = Field(default=None, max_length=16)
    language_code: LanguageCodeLiteral | None = Field(default=None)
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
        if not _is_valid_email_address(stripped):
            raise ValueError("must be a valid email address")
        return stripped

    @field_validator("timezone_name")
    @classmethod
    def validate_timezone_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_timezone_name(value)

    @field_validator("timezone_source")
    @classmethod
    def validate_timezone_source(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip().lower()
        if stripped not in {"auto", "manual"}:
            raise ValueError("timezone_source must be either 'auto' or 'manual'")
        return stripped

    @field_validator("language_code")
    @classmethod
    def validate_language_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_language_code(value)


class McpAccessTokenCreateRequest(BaseModel):
    label: str = Field(min_length=1, max_length=128)
    expires_in_days: int | None = Field(default=30, ge=1, le=365)

    model_config = {"extra": "forbid"}


class McpAccessTokenResponse(BaseModel):
    token_id: str
    label: str
    scopes: list[str] = Field(default_factory=list)
    last_used_at: datetime | None = None
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime


class McpAccessTokenCreateResponse(McpAccessTokenResponse):
    token: str


ChannelAccountTypeLiteral = Literal["telegram", "slack", "wechat", "wecom"]
ChannelAccountStatusLiteral = Literal["active", "paused", "revoked"]
ChannelAccountVerificationStatusLiteral = Literal["pending", "verified", "revoked"]
ChannelDeliveryStatusLiteral = Literal["pending", "sent", "acknowledged", "failed", "canceled"]


class ChannelAccountCreateRequest(BaseModel):
    channel_type: ChannelAccountTypeLiteral
    account_label: str = Field(min_length=1, max_length=128)
    external_user_id: str | None = Field(default=None, max_length=255)
    external_workspace_id: str | None = Field(default=None, max_length=255)

    model_config = {"extra": "forbid"}


class ChannelAccountResponse(BaseModel):
    id: int
    channel_type: ChannelAccountTypeLiteral
    account_label: str
    external_user_id: str | None = None
    external_workspace_id: str | None = None
    status: ChannelAccountStatusLiteral
    verification_status: ChannelAccountVerificationStatusLiteral
    last_seen_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ChannelDeliveryResponse(BaseModel):
    delivery_id: str
    channel_account_id: int | None = None
    proposal_id: int | None = None
    ticket_id: str | None = None
    delivery_kind: str
    status: ChannelDeliveryStatusLiteral
    attempt_count: int
    summary_code: str | None = None
    detail_code: str | None = None
    cta_code: str | None = None
    payload: dict = Field(default_factory=dict)
    origin_kind: str
    origin_label: str
    external_message_id: str | None = None
    sent_at: datetime | None = None
    acknowledged_at: datetime | None = None
    failed_at: datetime | None = None
    error_text: str | None = None
    created_at: datetime
    updated_at: datetime


class McpToolInvocationResponse(BaseModel):
    invocation_id: str
    transport_request_id: str | None = None
    tool_name: str
    transport: str
    auth_mode: str
    status: Literal["started", "succeeded", "failed"]
    proposal_id: int | None = None
    ticket_id: str | None = None
    target_kind: str | None = None
    target_id: str | None = None
    summary_code: str | None = None
    output_summary: dict = Field(default_factory=dict)
    error_text: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


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


__all__ = [
    "ChannelAccountCreateRequest",
    "ChannelAccountResponse",
    "ChannelDeliveryResponse",
    "McpToolInvocationResponse",
    "McpAccessTokenCreateRequest",
    "McpAccessTokenCreateResponse",
    "McpAccessTokenResponse",
    "UserResponse",
    "UserUpdateRequest",
]
