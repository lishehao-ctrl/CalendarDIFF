from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import require_internal_service_token
from app.db.models import Change, IntegrationOutbox, OutboxStatus, ReviewStatus
from app.db.session import get_db

router = APIRouter(
    prefix="/internal/v2",
    tags=["internal-review-metrics"],
    dependencies=[Depends(require_internal_service_token({"ops", "review"}))],
)


@router.get("/metrics")
def get_review_metrics(db: Session = Depends(get_db)) -> dict[str, object]:
    now = datetime.now(timezone.utc)

    pending_changes = int(db.scalar(select(func.count(Change.id)).where(Change.review_status == ReviewStatus.PENDING)) or 0)
    max_age_seconds_raw = db.scalar(
        select(func.max(func.extract("epoch", func.now() - Change.detected_at))).where(
            Change.review_status == ReviewStatus.PENDING
        )
    )
    pending_backlog_age_seconds_max = float(max_age_seconds_raw or 0.0)
    apply_queue_pending = int(
        db.scalar(
            select(func.count(IntegrationOutbox.id)).where(
                IntegrationOutbox.event_type == "ingest.result.ready",
                IntegrationOutbox.status == OutboxStatus.PENDING,
            )
        )
        or 0
    )

    return {
        "service_name": "review-service",
        "timestamp": now.isoformat(),
        "metrics": {
            "pending_changes": pending_changes,
            "pending_backlog_age_seconds_max": pending_backlog_age_seconds_max,
            "apply_queue_pending": apply_queue_pending,
        },
    }
