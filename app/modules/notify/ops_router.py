from __future__ import annotations

from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import require_internal_service_token
from app.db.models.notify import DigestSendLog, Notification, NotificationStatus
from app.db.session import get_db
from app.modules.notify.consumer import run_notification_enqueue_tick
from app.modules.notify.digest_service import process_due_digests
from app.modules.notify.runtime_context import notification_runtime_context

router = APIRouter(
    prefix="/internal",
    tags=["internal-notify-ops"],
    dependencies=[Depends(require_internal_service_token({"ops", "notification"}))],
)


class NotificationFlushRequest(BaseModel):
    run_id: str | None = Field(default=None, max_length=128)
    semester: int | None = Field(default=None, ge=1, le=9)
    batch: int | None = Field(default=None, ge=0, le=99)
    force_due: bool = True

    model_config = {"extra": "forbid"}


@router.get("/notifications/status")
def get_notification_status(db: Session = Depends(get_db)) -> dict[str, int]:
    pending = int(
        db.scalar(select(func.count(Notification.id)).where(Notification.status == NotificationStatus.PENDING)) or 0
    )
    sent = int(db.scalar(select(func.count(Notification.id)).where(Notification.status == NotificationStatus.SENT)) or 0)
    failed = int(db.scalar(select(func.count(Notification.id)).where(Notification.status == NotificationStatus.FAILED)) or 0)
    digest_sent = int(db.scalar(select(func.count(DigestSendLog.id)).where(DigestSendLog.status == "sent")) or 0)
    digest_failed = int(db.scalar(select(func.count(DigestSendLog.id)).where(DigestSendLog.status == "failed")) or 0)

    return {
        "notification_pending": pending,
        "notification_sent": sent,
        "notification_failed": failed,
        "digest_sent": digest_sent,
        "digest_failed": digest_failed,
    }


@router.post("/notifications/flush")
def flush_notifications(
    payload: NotificationFlushRequest,
    db: Session = Depends(get_db),
) -> dict[str, int | bool | str | None]:
    sent_before, failed_before = _count_digest_results(db)
    with notification_runtime_context(
        run_id=payload.run_id,
        semester=payload.semester,
        batch=payload.batch,
    ):
        enqueued_notifications = run_notification_enqueue_tick(db)
        process_now = _build_force_due_now() if payload.force_due else None
        processed_slots = process_due_digests(db, now=process_now)
    sent_after, failed_after = _count_digest_results(db)
    pending_after = int(
        db.scalar(select(func.count(Notification.id)).where(Notification.status == NotificationStatus.PENDING)) or 0
    )

    return {
        "enqueued_notifications": int(enqueued_notifications),
        "processed_slots": int(processed_slots),
        "sent_count": max(sent_after - sent_before, 0),
        "failed_count": max(failed_after - failed_before, 0),
        "pending_after": pending_after,
        "force_due": payload.force_due,
        "run_id": payload.run_id,
        "semester": payload.semester,
        "batch": payload.batch,
    }


def _count_digest_results(db: Session) -> tuple[int, int]:
    sent = 0
    failed = 0
    rows = db.execute(select(DigestSendLog.status, func.count()).group_by(DigestSendLog.status)).all()
    for status, count in rows:
        if status == "sent":
            sent = int(count)
        elif status == "failed":
            failed = int(count)
    return sent, failed


def _build_force_due_now() -> datetime:
    settings = get_settings()
    try:
        tz = ZoneInfo(settings.digest_fixed_timezone)
    except Exception:
        tz = ZoneInfo("UTC")
    local_now = datetime.now(tz)
    forced_local = datetime.combine(local_now.date(), time(hour=23, minute=59), tzinfo=tz)
    return forced_local.astimezone(UTC)
