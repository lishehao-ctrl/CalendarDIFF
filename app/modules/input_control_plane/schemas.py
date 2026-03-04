from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


SourceKindLiteral = Literal["calendar", "email", "task", "exam", "announcement"]
TriggerTypeLiteral = Literal["manual", "scheduler", "webhook"]
SyncRequestStatusLiteral = Literal["PENDING", "QUEUED", "RUNNING", "SUCCEEDED", "FAILED"]


class InputSourceCreateRequest(BaseModel):
    source_kind: SourceKindLiteral
    provider: str = Field(min_length=1, max_length=64)
    source_key: str | None = Field(default=None, max_length=255)
    display_name: str | None = Field(default=None, max_length=255)
    poll_interval_seconds: int = Field(default=900, ge=30, le=86400)
    config: dict = Field(default_factory=dict)
    secrets: dict = Field(default_factory=dict)

    model_config = {"extra": "forbid"}


class InputSourcePatchRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None
    poll_interval_seconds: int | None = Field(default=None, ge=30, le=86400)
    config: dict | None = None
    secrets: dict | None = None

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


class SyncRequestCreateResponse(BaseModel):
    request_id: str
    source_id: int
    trigger_type: TriggerTypeLiteral
    status: SyncRequestStatusLiteral
    created_at: datetime
    idempotency_key: str


class SyncRequestCreateRequest(BaseModel):
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
    provider: str = Field(min_length=1, max_length=64)

    model_config = {"extra": "forbid"}


class OAuthSessionCreateResponse(BaseModel):
    source_id: int
    provider: str
    authorization_url: str
    expires_at: datetime


class OAuthCallbackResponse(BaseModel):
    source_id: int | None = None
    provider: str
    request_id: str | None = None
    status: str
    sync_request_status: SyncRequestStatusLiteral | None = None
    message: str | None = None


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
