from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import require_internal_service_token
from app.db.models import IngestJob, IngestJobStatus, IntegrationOutbox, OutboxStatus
from app.db.session import get_db

router = APIRouter(
    prefix="/internal/v2",
    tags=["internal-ingest-metrics"],
    dependencies=[Depends(require_internal_service_token({"ops", "ingest"}))],
)


@router.get("/metrics")
def get_ingest_metrics(db: Session = Depends(get_db)) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    one_hour_ago = now - timedelta(hours=1)

    ingest_jobs_pending = int(
        db.scalar(select(func.count(IngestJob.id)).where(IngestJob.status == IngestJobStatus.PENDING)) or 0
    )
    ingest_jobs_dead_letter = int(
        db.scalar(select(func.count(IngestJob.id)).where(IngestJob.status == IngestJobStatus.DEAD_LETTER)) or 0
    )

    dead_letter_1h = int(
        db.scalar(
            select(func.count(IngestJob.id)).where(
                IngestJob.status == IngestJobStatus.DEAD_LETTER,
                IngestJob.updated_at >= one_hour_ago,
            )
        )
        or 0
    )
    processed_1h = int(
        db.scalar(
            select(func.count(IngestJob.id)).where(
                IngestJob.status.in_(
                    [IngestJobStatus.SUCCEEDED, IngestJobStatus.FAILED, IngestJobStatus.DEAD_LETTER]
                ),
                IngestJob.updated_at >= one_hour_ago,
            )
        )
        or 0
    )
    dead_letter_rate_1h = round(dead_letter_1h / processed_1h, 6) if processed_1h > 0 else 0.0

    lag_seconds_expr = func.extract("epoch", func.now() - IntegrationOutbox.created_at)
    event_lag_seconds_p95_raw = db.scalar(
        select(func.percentile_cont(0.95).within_group(lag_seconds_expr)).where(
            IntegrationOutbox.status == OutboxStatus.PENDING
        )
    )
    event_lag_seconds_p95 = float(event_lag_seconds_p95_raw or 0.0)

    return {
        "service_name": "ingest-service",
        "timestamp": now.isoformat(),
        "metrics": {
            "ingest_jobs_pending": ingest_jobs_pending,
            "ingest_jobs_dead_letter": ingest_jobs_dead_letter,
            "dead_letter_rate_1h": dead_letter_rate_1h,
            "event_lag_seconds_p95": event_lag_seconds_p95,
        },
    }
