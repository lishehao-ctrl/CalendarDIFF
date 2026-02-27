from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import sanitize_log_message
from app.db.models import Input
from app.modules.inputs.presenters import to_input_response
from app.modules.inputs.service import MANUAL_SYNC_RETRY_AFTER_SECONDS, list_inputs_with_runtime_state
from app.modules.onboarding.schemas import OnboardingStatusResponse
from app.modules.onboarding.service import get_onboarding_status
from app.modules.users.schemas import UserResponse
from app.modules.users.service import get_registered_user
from app.state import SchedulerStatus

from .schemas import (
    WorkspaceBootstrapResponse,
    WorkspaceConfigStatusResponse,
    WorkspaceDefaultsResponse,
    WorkspaceHealthSummaryResponse,
)


def build_workspace_bootstrap(
    db: Session,
    *,
    scheduler_status: SchedulerStatus | None,
) -> WorkspaceBootstrapResponse:
    settings = get_settings()
    onboarding = get_onboarding_status(db)
    user = get_registered_user(db)

    input_rows = list_inputs_with_runtime_state(db, user_id=user.id) if user is not None else []
    input_payload = [
        to_input_response(input_row, next_check_at=next_check_at, last_result=last_result)
        for input_row, next_check_at, last_result in input_rows
    ]

    db_ok = False
    db_error: str | None = None
    next_expected_input_id: int | None = None
    next_expected_check_at: datetime | None = None
    now = datetime.now(timezone.utc)
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
        next_expected_input_id, next_expected_check_at = _compute_next_expected_check(db, now=now)
    except Exception as exc:  # pragma: no cover - defensive branch
        db_error = sanitize_log_message(str(exc))

    status = scheduler_status or SchedulerStatus()
    health_summary = WorkspaceHealthSummaryResponse(
        status="ok" if db_ok else "degraded",
        db_ok=db_ok,
        db_error=db_error,
        scheduler_running=status.running,
        scheduler_last_error=status.last_error,
        scheduler_instance_id=status.instance_id,
        next_expected_input_id=next_expected_input_id,
        next_expected_check_at=next_expected_check_at,
    )

    user_payload = (
        UserResponse(
            id=user.id,
            email=user.email,
            notify_email=user.notify_email,
            calendar_delay_seconds=user.calendar_delay_seconds,
            created_at=user.created_at,
        )
        if user is not None
        else None
    )

    return WorkspaceBootstrapResponse(
        config_status=WorkspaceConfigStatusResponse(
            notifications_enabled=settings.enable_notifications,
            gmail_oauth_configured=bool(settings.gmail_oauth_client_secrets_file),
            schema_guard_enabled=settings.schema_guard_enabled,
        ),
        onboarding=OnboardingStatusResponse(
            stage=onboarding.stage,  # type: ignore[arg-type]
            message=onboarding.message,
            registered_user_id=onboarding.registered_user_id,
            first_input_id=onboarding.first_input_id,
            last_error=onboarding.last_error,
        ),
        user=user_payload,
        inputs=input_payload,
        health_summary=health_summary,
        defaults=WorkspaceDefaultsResponse(
            default_changes_limit=settings.default_changes_limit,
            max_changes_limit=settings.max_changes_limit,
            default_sync_interval_minutes=settings.default_sync_interval_minutes,
            scheduler_tick_seconds=settings.scheduler_tick_seconds,
            manual_sync_retry_seconds=MANUAL_SYNC_RETRY_AFTER_SECONDS,
        ),
    )


def _compute_next_expected_check(db: Session, *, now: datetime) -> tuple[int | None, datetime | None]:
    next_check_expr = func.coalesce(
        Input.last_checked_at + func.make_interval(0, 0, 0, 0, 0, Input.interval_minutes, 0),
        now,
    )
    row = db.execute(
        select(Input.id, next_check_expr.label("next_check_at"))
        .where(Input.is_active.is_(True))
        .order_by(next_check_expr.asc(), Input.id.asc())
        .limit(1)
    ).first()
    if row is None:
        return None, None
    input_id, next_check_at = row
    if next_check_at is None:
        return None, None
    return input_id, _as_utc(next_check_at)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
