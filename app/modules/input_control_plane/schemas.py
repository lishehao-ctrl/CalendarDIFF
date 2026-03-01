from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


SourceKindLiteral = Literal["calendar", "email", "task", "exam", "announcement"]
TriggerTypeLiteral = Literal["manual", "scheduler", "webhook"]
SyncRequestStatusLiteral = Literal["PENDING", "QUEUED", "RUNNING", "SUCCEEDED", "FAILED"]
LlmApiModeLiteral = Literal["chat_completions", "responses"]


class SourceLlmBindingCreateRequest(BaseModel):
    provider_id: str = Field(min_length=1, max_length=64)
    model_override: str | None = Field(default=None, max_length=255)
    api_mode_override: LlmApiModeLiteral | None = None
    prompt_profile: str | None = Field(default=None, max_length=128)
    enabled: bool = True

    model_config = {"extra": "forbid"}


class SourceLlmBindingPatchRequest(BaseModel):
    provider_id: str | None = Field(default=None, min_length=1, max_length=64)
    model_override: str | None = Field(default=None, max_length=255)
    api_mode_override: LlmApiModeLiteral | None = None
    prompt_profile: str | None = Field(default=None, max_length=128)
    enabled: bool | None = None

    model_config = {"extra": "forbid"}


class SourceLlmBindingResponse(BaseModel):
    provider_id: str
    provider_name: str
    vendor: str
    api_mode: LlmApiModeLiteral
    model: str
    model_override: str | None
    api_mode_override: LlmApiModeLiteral | None
    prompt_profile: str | None
    enabled: bool
    updated_at: datetime


class InputSourceCreateRequest(BaseModel):
    source_kind: SourceKindLiteral
    provider: str = Field(min_length=1, max_length=64)
    source_key: str | None = Field(default=None, max_length=255)
    display_name: str | None = Field(default=None, max_length=255)
    poll_interval_seconds: int = Field(default=900, ge=30, le=86400)
    config: dict = Field(default_factory=dict)
    secrets: dict = Field(default_factory=dict)
    llm_binding: SourceLlmBindingCreateRequest | None = None

    model_config = {"extra": "forbid"}


class InputSourcePatchRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None
    poll_interval_seconds: int | None = Field(default=None, ge=30, le=86400)
    config: dict | None = None
    secrets: dict | None = None
    llm_binding: SourceLlmBindingPatchRequest | None = None

    model_config = {"extra": "forbid"}


class InputSourceResponse(BaseModel):
    source_id: int
    user_id: int
    source_kind: SourceKindLiteral
    provider: str
    source_key: str
    display_name: str | None
    is_active: bool
    poll_interval_seconds: int
    last_polled_at: datetime | None
    next_poll_at: datetime | None
    last_error_code: str | None
    last_error_message: str | None
    created_at: datetime
    updated_at: datetime
    config: dict
    llm_binding: SourceLlmBindingResponse | None = None


class SyncRequestCreateResponse(BaseModel):
    request_id: str
    source_id: int
    trigger_type: TriggerTypeLiteral
    status: SyncRequestStatusLiteral
    created_at: datetime
    idempotency_key: str


class SyncRequestCreateRequest(BaseModel):
    source_id: int = Field(ge=1)
    trace_id: str | None = Field(default=None, max_length=64)
    metadata: dict = Field(default_factory=dict)

    model_config = {"extra": "forbid"}


class SyncRequestStatusResponse(BaseModel):
    request_id: str
    source_id: int
    trigger_type: TriggerTypeLiteral
    status: SyncRequestStatusLiteral
    idempotency_key: str
    trace_id: str | None
    error_code: str | None
    error_message: str | None
    metadata: dict
    created_at: datetime
    updated_at: datetime
    connector_result: dict | None = None
    applied: bool = False
    applied_at: datetime | None = None


class OAuthStartResponse(BaseModel):
    authorization_url: str
    expires_at: datetime


class OAuthSessionCreateRequest(BaseModel):
    source_id: int = Field(ge=1)
    provider: str = Field(min_length=1, max_length=64)

    model_config = {"extra": "forbid"}


class OAuthSessionCreateResponse(BaseModel):
    source_id: int
    provider: str
    authorization_url: str
    expires_at: datetime


class OAuthCallbackResponse(BaseModel):
    source_id: int
    provider: str
    request_id: str
    status: str


class WebhookEnqueueResponse(BaseModel):
    request_id: str
    status: SyncRequestStatusLiteral


class IngestJobReplayResponse(BaseModel):
    job_id: int
    request_id: str
    status: str
    next_retry_at: datetime | None


class DeadLetterReplayResponse(BaseModel):
    replayed_jobs: list[IngestJobReplayResponse]


class LlmProviderCreateRequest(BaseModel):
    provider_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    vendor: str = Field(min_length=1, max_length=64)
    base_url: str = Field(min_length=1, max_length=512)
    api_mode: LlmApiModeLiteral
    model: str = Field(min_length=1, max_length=255)
    api_key_ref: str = Field(min_length=1, max_length=128)
    timeout_seconds: float = Field(default=12.0, ge=1.0, le=120.0)
    max_retries: int = Field(default=1, ge=0, le=5)
    max_input_chars: int = Field(default=12000, ge=512, le=200000)
    enabled: bool = True
    is_default: bool = False
    extra_config: dict = Field(default_factory=dict)

    model_config = {"extra": "forbid"}


class LlmProviderPatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    vendor: str | None = Field(default=None, min_length=1, max_length=64)
    base_url: str | None = Field(default=None, min_length=1, max_length=512)
    api_mode: LlmApiModeLiteral | None = None
    model: str | None = Field(default=None, min_length=1, max_length=255)
    api_key_ref: str | None = Field(default=None, min_length=1, max_length=128)
    timeout_seconds: float | None = Field(default=None, ge=1.0, le=120.0)
    max_retries: int | None = Field(default=None, ge=0, le=5)
    max_input_chars: int | None = Field(default=None, ge=512, le=200000)
    enabled: bool | None = None
    is_default: bool | None = None
    extra_config: dict | None = None

    model_config = {"extra": "forbid"}


class LlmProviderResponse(BaseModel):
    provider_id: str
    name: str
    vendor: str
    base_url: str
    api_mode: LlmApiModeLiteral
    model: str
    api_key_ref: str
    timeout_seconds: float
    max_retries: int
    max_input_chars: int
    enabled: bool
    is_default: bool
    extra_config: dict
    created_at: datetime
    updated_at: datetime


class LlmProviderValidationResponse(BaseModel):
    provider_id: str
    api_mode: LlmApiModeLiteral
    endpoint: str
    ok: bool
    latency_ms: int | None = None
    error_code: str | None = None
    error_message: str | None = None


class LlmDefaultProviderRequest(BaseModel):
    provider_id: str = Field(min_length=1, max_length=64)

    model_config = {"extra": "forbid"}
