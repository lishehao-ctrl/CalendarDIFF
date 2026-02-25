from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import require_api_key
from app.db.models import Notification, NotificationStatus, Input, SyncRun, SyncRunStatus
from app.db.session import get_db
from app.modules.scheduler.runner import SchedulerRunner
from app.modules.sync.service import list_due_inputs

router = APIRouter(prefix="/v1", tags=["status"], dependencies=[Depends(require_api_key)])


class StatusResponse(BaseModel):
    scheduler_last_tick_at: datetime | None
    scheduler_lock_acquired: bool | None
    due_inputs_count: int
    checked_in_last_5m_count: int
    failed_in_last_1h_count: int
    pending_delayed_notifications_count: int
    schema_guard_blocked: bool
    schema_guard_message: str | None


@router.get("/status", response_model=StatusResponse)
def get_status(request: Request, db: Session = Depends(get_db)) -> StatusResponse:
    now = datetime.now(timezone.utc)
    checked_window_start = now - timedelta(minutes=5)
    failed_window_start = now - timedelta(hours=1)

    due_inputs_count = _count_due_inputs(db, now=now)
    checked_in_last_5m_count = int(
        db.scalar(
            select(func.count(Input.id)).where(
                Input.last_checked_at.is_not(None),
                Input.last_checked_at >= checked_window_start,
            )
        )
        or 0
    )
    failed_in_last_1h_count = int(
        db.scalar(
            select(func.count(SyncRun.id)).where(
                SyncRun.status.in_(
                    [
                        SyncRunStatus.FETCH_FAILED,
                        SyncRunStatus.PARSE_FAILED,
                        SyncRunStatus.DIFF_FAILED,
                        SyncRunStatus.EMAIL_FAILED,
                    ]
                ),
                SyncRun.started_at >= failed_window_start,
            )
        )
        or 0
    )
    pending_delayed_notifications_count = int(
        db.scalar(
            select(func.count(Notification.id)).where(
                Notification.status == NotificationStatus.PENDING,
                Notification.deliver_after > now,
            )
        )
        or 0
    )

    runner: SchedulerRunner | None = getattr(request.app.state, "scheduler_runner", None)
    scheduler_last_tick_at = runner.status.last_tick_at if runner is not None else None
    scheduler_lock_acquired = runner.status.last_tick_lock_acquired if runner is not None else None

    schema_guard_message = getattr(request.app.state, "schema_guard_error", None)
    schema_guard_blocked = bool(schema_guard_message)
    if runner is not None:
        schema_guard_blocked = bool(runner.status.schema_guard_blocked or schema_guard_blocked)
        if schema_guard_message is None:
            schema_guard_message = runner.status.schema_guard_message

    return StatusResponse(
        scheduler_last_tick_at=scheduler_last_tick_at,
        scheduler_lock_acquired=scheduler_lock_acquired,
        due_inputs_count=due_inputs_count,
        checked_in_last_5m_count=checked_in_last_5m_count,
        failed_in_last_1h_count=failed_in_last_1h_count,
        pending_delayed_notifications_count=pending_delayed_notifications_count,
        schema_guard_blocked=schema_guard_blocked,
        schema_guard_message=schema_guard_message,
    )


def _count_due_inputs(db: Session, *, now: datetime) -> int:
    return len(list_due_inputs(db, now=now))
