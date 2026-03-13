from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import require_internal_service_token
from app.db.models.notify import Notification, NotificationStatus
from app.db.session import get_db
from app.modules.notify.consumer import run_notification_enqueue_tick
from app.modules.notify.digest_service import dispatch_pending_notifications
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

    return {
        "notification_pending": pending,
        "notification_sent": sent,
        "notification_failed": failed,
        "digest_sent": sent,
        "digest_failed": failed,
    }


@router.post("/notifications/flush")
def flush_notifications(
    payload: NotificationFlushRequest,
    db: Session = Depends(get_db),
) -> dict[str, int | bool | str | None]:
    with notification_runtime_context(
        run_id=payload.run_id,
        semester=payload.semester,
        batch=payload.batch,
    ):
        enqueued_notifications = run_notification_enqueue_tick(db)
        dispatch_result = dispatch_pending_notifications(db)
    pending_after = int(
        db.scalar(select(func.count(Notification.id)).where(Notification.status == NotificationStatus.PENDING)) or 0
    )

    return {
        "enqueued_notifications": int(enqueued_notifications),
        "processed_slots": int(dispatch_result.processed_batches),
        "processed_batches": int(dispatch_result.processed_batches),
        "sent_count": int(dispatch_result.sent_count),
        "failed_count": int(dispatch_result.failed_count),
        "sent_notification_count": int(dispatch_result.sent_notification_count),
        "failed_notification_count": int(dispatch_result.failed_notification_count),
        "pending_after": pending_after,
        "force_due": payload.force_due,
        "run_id": payload.run_id,
        "semester": payload.semester,
        "batch": payload.batch,
    }
