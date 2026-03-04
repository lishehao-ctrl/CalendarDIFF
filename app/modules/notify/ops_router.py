from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends

from app.core.security import require_internal_service_token
from app.db.models import DigestSendLog, Notification, NotificationStatus
from app.db.session import get_db

router = APIRouter(
    prefix="/internal",
    tags=["internal-notify-ops"],
    dependencies=[Depends(require_internal_service_token({"ops", "notification"}))],
)


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
