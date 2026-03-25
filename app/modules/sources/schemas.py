from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


SourceKindLiteral = Literal["calendar", "email", "task", "exam", "announcement"]
TriggerTypeLiteral = Literal["manual", "scheduler", "webhook"]
SyncRequestStatusLiteral = Literal["PENDING", "QUEUED", "RUNNING", "SUCCEEDED", "FAILED"]
SyncRequestStageLiteral = Literal[
    "connector_fetch",
    "llm_queue",
    "llm_parse",
    "provider_reduce",
    "result_ready",
    "applying",
    "completed",
    "failed",
]
OAuthConnectionStatusLiteral = Literal["connected", "not_connected"]
SourceListStatusLiteral = Literal["active", "archived", "all"]
SourceLifecycleStateLiteral = Literal["active", "inactive", "archived"]
SourceSyncStateLiteral = Literal["idle", "queued", "running"]
SourceConfigStateLiteral = Literal["stable", "rebind_pending"]
SourceRuntimeStateLiteral = Literal["active", "inactive", "archived", "queued", "running", "rebind_pending"]
SourceOperatorActionLiteral = Literal["continue_review", "continue_review_with_caution", "wait_for_runtime", "investigate_runtime"]
SourceOperatorSeverityLiteral = Literal["info", "warning", "blocking"]
SourceBootstrapStateLiteral = Literal["idle", "running", "review_required", "completed"]
SourceProductPhaseLiteral = Literal["importing_baseline", "needs_initial_review", "monitoring_live", "needs_attention"]
SourceRecoveryTrustStateLiteral = Literal["trusted", "stale", "partial", "blocked"]
SourceRecoveryActionLiteral = Literal["reconnect_gmail", "update_ics", "retry_sync", "wait"]


class SourceOperatorGuidanceResponse(BaseModel):
    recommended_action: SourceOperatorActionLiteral
    severity: SourceOperatorSeverityLiteral
    reason_code: str
    message: str
    message_code: str
    message_params: dict = Field(default_factory=dict)
    related_request_id: str | None = None
    progress_age_seconds: int | None = None


class SourceRecoveryResponse(BaseModel):
    trust_state: SourceRecoveryTrustStateLiteral
    impact_summary: str
    impact_code: str
    next_action: SourceRecoveryActionLiteral
    next_action_label: str
    last_good_sync_at: datetime | None = None
    degraded_since: datetime | None = None
    recovery_steps: list[str] = Field(default_factory=list)
    recovery_step_codes: list[str] = Field(default_factory=list)


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
    oauth_connection_status: OAuthConnectionStatusLiteral | None = None
    oauth_account_email: str | None = None
    lifecycle_state: SourceLifecycleStateLiteral
    sync_state: SourceSyncStateLiteral
    config_state: SourceConfigStateLiteral
    runtime_state: SourceRuntimeStateLiteral
    active_request_id: str | None = None
    sync_progress: dict | None = None
    operator_guidance: SourceOperatorGuidanceResponse | None = None
    source_product_phase: SourceProductPhaseLiteral | None = None
    source_recovery: SourceRecoveryResponse | None = None


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
    stage: SyncRequestStageLiteral | None = None
    substage: str | None = None
    stage_updated_at: datetime | None = None
    connector_result: dict | None = None
    llm_usage: dict | None = None
    elapsed_ms: int | None = None
    applied: bool = False
    applied_at: datetime | None = None
    progress: dict | None = None


class LlmInvocationLogResponse(BaseModel):
    request_id: str | None = None
    source_id: int | None = None
    task_name: str
    profile_family: str
    route_id: str
    route_index: int
    provider_id: str
    vendor: str
    protocol: str
    model: str
    session_cache_enabled: bool
    success: bool
    latency_ms: int | None = None
    upstream_request_id: str | None = None
    response_id: str | None = None
    error_code: str | None = None
    retryable: bool | None = None
    http_status: int | None = None
    usage: dict | None = None
    created_at: datetime


class LlmInvocationSummaryResponse(BaseModel):
    total_count: int
    success_count: int
    failure_count: int
    avg_latency_ms: int | None = None
    input_tokens: int = 0
    cached_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    task_counts: dict[str, int] = Field(default_factory=dict)
    model_counts: dict[str, int] = Field(default_factory=dict)
    protocol_counts: dict[str, int] = Field(default_factory=dict)


class SyncRequestLlmInvocationsResponse(BaseModel):
    request_id: str
    items: list[LlmInvocationLogResponse]
    summary: LlmInvocationSummaryResponse


class SourceLlmInvocationsResponse(BaseModel):
    source_id: int
    request_id: str | None = None
    items: list[LlmInvocationLogResponse]
    summary: LlmInvocationSummaryResponse


class SourceObservabilitySyncResponse(BaseModel):
    request_id: str
    phase: Literal["bootstrap", "replay"]
    trigger_type: TriggerTypeLiteral
    status: SyncRequestStatusLiteral
    created_at: datetime
    updated_at: datetime
    stage: SyncRequestStageLiteral | None = None
    substage: str | None = None
    stage_updated_at: datetime | None = None
    applied: bool = False
    applied_at: datetime | None = None
    elapsed_ms: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    connector_result: dict | None = None
    llm_usage: dict | None = None
    progress: dict | None = None


class SourceBootstrapSummaryResponse(BaseModel):
    imported_count: int
    review_required_count: int
    ignored_count: int
    conflict_count: int
    state: SourceBootstrapStateLiteral


class SourceObservabilityResponse(BaseModel):
    source_id: int
    active_request_id: str | None = None
    bootstrap: SourceObservabilitySyncResponse | None = None
    bootstrap_summary: SourceBootstrapSummaryResponse | None = None
    latest_replay: SourceObservabilitySyncResponse | None = None
    active: SourceObservabilitySyncResponse | None = None
    operator_guidance: SourceOperatorGuidanceResponse | None = None
    source_product_phase: SourceProductPhaseLiteral | None = None
    source_recovery: SourceRecoveryResponse | None = None


class SourceSyncHistoryResponse(BaseModel):
    source_id: int
    items: list[SourceObservabilitySyncResponse]


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
