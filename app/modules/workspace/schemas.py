from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.modules.inputs.schemas import InputResponse
from app.modules.onboarding.schemas import OnboardingStatusResponse
from app.modules.users.schemas import UserResponse


class WorkspaceConfigStatusResponse(BaseModel):
    notifications_enabled: bool
    gmail_oauth_configured: bool
    schema_guard_enabled: bool


class WorkspaceDefaultsResponse(BaseModel):
    default_changes_limit: int
    max_changes_limit: int
    default_sync_interval_minutes: int
    scheduler_tick_seconds: int
    manual_sync_retry_seconds: int


class WorkspaceHealthSummaryResponse(BaseModel):
    status: str
    db_ok: bool
    db_error: str | None
    scheduler_running: bool
    scheduler_last_error: str | None
    scheduler_instance_id: str | None
    next_expected_input_id: int | None
    next_expected_check_at: datetime | None


class WorkspaceBootstrapResponse(BaseModel):
    config_status: WorkspaceConfigStatusResponse
    onboarding: OnboardingStatusResponse
    user: UserResponse | None
    inputs: list[InputResponse]
    health_summary: WorkspaceHealthSummaryResponse
    defaults: WorkspaceDefaultsResponse
