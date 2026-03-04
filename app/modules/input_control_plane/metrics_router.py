from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import require_internal_service_token
from app.db.models import InputSource, SyncRequest, SyncRequestStatus
from app.db.session import get_db

router = APIRouter(
    prefix="/internal",
    tags=["internal-input-metrics"],
    dependencies=[Depends(require_internal_service_token({"ops", "input"}))],
)


@router.get("/metrics")
def get_input_metrics(db: Session = Depends(get_db)) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    one_hour_ago = now - timedelta(hours=1)

    active_sources = int(db.scalar(select(func.count(InputSource.id)).where(InputSource.is_active.is_(True))) or 0)
    due_sources = int(
        db.scalar(
            select(func.count(InputSource.id)).where(
                InputSource.is_active.is_(True),
                InputSource.next_poll_at.is_not(None),
                InputSource.next_poll_at <= now,
            )
        )
        or 0
    )
    sync_requests_pending = int(
        db.scalar(
            select(func.count(SyncRequest.id)).where(
                SyncRequest.status.in_(
                    [SyncRequestStatus.PENDING, SyncRequestStatus.QUEUED, SyncRequestStatus.RUNNING]
                )
            )
        )
        or 0
    )
    sync_requests_failed_1h = int(
        db.scalar(
            select(func.count(SyncRequest.id)).where(
                SyncRequest.status == SyncRequestStatus.FAILED,
                SyncRequest.updated_at >= one_hour_ago,
            )
        )
        or 0
    )

    return {
        "service_name": "input-service",
        "timestamp": now.isoformat(),
        "metrics": {
            "active_sources": active_sources,
            "due_sources": due_sources,
            "sync_requests_pending": sync_requests_pending,
            "sync_requests_failed_1h": sync_requests_failed_1h,
        },
    }
