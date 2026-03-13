from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import require_internal_service_token
from app.db.models.notify import Notification, NotificationStatus
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
    notifications_sent_24h = int(
        db.scalar(
            select(func.count(Notification.id)).where(
                Notification.status == NotificationStatus.SENT,
                Notification.sent_at >= day_ago,
            )
        )
        or 0
    )
    notifications_failed_24h = int(
        db.scalar(
            select(func.count(Notification.id)).where(
                Notification.status == NotificationStatus.FAILED,
                Notification.notified_at >= day_ago,
            )
        )
        or 0
    )
    total_attempts = notifications_sent_24h + notifications_failed_24h
    notify_fail_rate_24h = round(notifications_failed_24h / total_attempts, 6) if total_attempts > 0 else 0.0

    return {
        "service_name": "notification-service",
        "timestamp": now.isoformat(),
        "metrics": {
            "notifications_pending": notifications_pending,
            "notifications_sent_24h": notifications_sent_24h,
            "notifications_failed_24h": notifications_failed_24h,
            "digest_sent_24h": notifications_sent_24h,
            "digest_failed_24h": notifications_failed_24h,
            "notify_fail_rate_24h": notify_fail_rate_24h,
        },
    }
