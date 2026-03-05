from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import require_internal_service_token
from app.db.models.notify import DigestSendLog, Notification, NotificationStatus
from app.db.session import get_db

router = APIRouter(
    prefix="/internal",
    tags=["internal-notify-metrics"],
    dependencies=[Depends(require_internal_service_token({"ops", "notification"}))],
)


@router.get("/metrics")
def get_notify_metrics(db: Session = Depends(get_db)) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(hours=24)

    notifications_pending = int(
        db.scalar(select(func.count(Notification.id)).where(Notification.status == NotificationStatus.PENDING)) or 0
    )
    digest_sent_24h = int(
        db.scalar(
            select(func.count(DigestSendLog.id)).where(
                DigestSendLog.status == "sent",
                DigestSendLog.sent_at >= day_ago,
            )
        )
        or 0
    )
    digest_failed_24h = int(
        db.scalar(
            select(func.count(DigestSendLog.id)).where(
                DigestSendLog.status == "failed",
                DigestSendLog.sent_at >= day_ago,
            )
        )
        or 0
    )
    total_attempts = digest_sent_24h + digest_failed_24h
    notify_fail_rate_24h = round(digest_failed_24h / total_attempts, 6) if total_attempts > 0 else 0.0

    return {
        "service_name": "notification-service",
        "timestamp": now.isoformat(),
        "metrics": {
            "notifications_pending": notifications_pending,
            "digest_sent_24h": digest_sent_24h,
            "digest_failed_24h": digest_failed_24h,
            "notify_fail_rate_24h": notify_fail_rate_24h,
        },
    }
