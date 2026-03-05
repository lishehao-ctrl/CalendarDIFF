from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.orm import aliased
from sqlalchemy.orm import Session

from app.core.security import require_internal_service_token
from app.db.models.ingestion import IngestJob, IngestJobStatus, IngestResult
from app.db.models.input import SyncRequest, SyncRequestStatus
from app.db.models.shared import IntegrationOutbox, OutboxStatus
from app.db.session import get_db

router = APIRouter(
    prefix="/internal",
    tags=["internal-ingest-metrics"],
    dependencies=[Depends(require_internal_service_token({"ops", "ingest"}))],
)


@router.get("/metrics")
def get_ingest_metrics(db: Session = Depends(get_db)) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    one_hour_ago = now - timedelta(hours=1)
    one_minute_ago = now - timedelta(minutes=1)

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

    older = aliased(IngestJob)
    source_fifo_deferred_count_1m = int(
        db.scalar(
            select(func.count(IngestJob.id)).where(
                IngestJob.status == IngestJobStatus.PENDING,
                or_(IngestJob.next_retry_at.is_(None), IngestJob.next_retry_at <= now),
                select(older.id)
                .where(
                    older.source_id == IngestJob.source_id,
                    older.id < IngestJob.id,
                    older.status.in_([IngestJobStatus.PENDING, IngestJobStatus.CLAIMED]),
                )
                .exists(),
            )
        )
        or 0
    )

    llm_rate_limited_1h = int(
        db.scalar(
            select(func.count(SyncRequest.id)).where(
                SyncRequest.updated_at >= one_hour_ago,
                SyncRequest.error_code.is_not(None),
                func.lower(SyncRequest.error_code).like("%rate_limit%"),
            )
        )
        or 0
    )

    retryable_codes = [
        "llm_rate_limited",
        "parse_llm_timeout",
        "parse_llm_upstream_error",
        "parse_llm_calendar_upstream_error",
        "parse_llm_gmail_upstream_error",
        "llm_queue_unavailable",
        "llm_retry_schedule_failed",
    ]
    llm_retry_scheduled_1h = int(
        db.scalar(
            select(func.count(SyncRequest.id)).where(
                SyncRequest.updated_at >= one_hour_ago,
                SyncRequest.status.in_([SyncRequestStatus.QUEUED, SyncRequestStatus.RUNNING]),
                SyncRequest.error_code.in_(retryable_codes),
            )
        )
        or 0
    )

    recent_calendar_results = db.scalars(
        select(IngestResult).where(
            IngestResult.created_at >= one_minute_ago,
            IngestResult.provider.in_(["ics", "calendar"]),
        )
    ).all()
    ics_delta_components_total_1m = 0
    ics_delta_changed_components_1m = 0
    ics_delta_removed_components_1m = 0
    for row in recent_calendar_results:
        row_records = row.records if isinstance(row.records, list) else []
        changed_count = 0
        removed_count = 0
        for record in row_records:
            if not isinstance(record, dict):
                continue
            record_type = record.get("record_type")
            if record_type == "calendar.event.extracted":
                changed_count += 1
            elif record_type == "calendar.event.removed":
                removed_count += 1
        row_cursor_patch = row.cursor_patch if isinstance(row.cursor_patch, dict) else {}
        row_total_raw = row_cursor_patch.get("ics_delta_components_total")
        if isinstance(row_total_raw, (int, float)):
            row_total = max(int(row_total_raw), 0)
        else:
            row_total = changed_count + removed_count
        ics_delta_components_total_1m += row_total
        ics_delta_changed_components_1m += changed_count
        ics_delta_removed_components_1m += removed_count

    ics_delta_parse_failures_1h = int(
        db.scalar(
            select(func.count(SyncRequest.id)).where(
                SyncRequest.updated_at >= one_hour_ago,
                SyncRequest.error_code.is_not(None),
                func.lower(SyncRequest.error_code) == "calendar_delta_parse_failed",
            )
        )
        or 0
    )

    return {
        "service_name": "ingest-service",
        "timestamp": now.isoformat(),
        "metrics": {
            "ingest_jobs_pending": ingest_jobs_pending,
            "ingest_jobs_dead_letter": ingest_jobs_dead_letter,
            "dead_letter_rate_1h": dead_letter_rate_1h,
            "event_lag_seconds_p95": event_lag_seconds_p95,
            "source_fifo_deferred_count_1m": source_fifo_deferred_count_1m,
            "llm_rate_limited_1h": llm_rate_limited_1h,
            "llm_retry_scheduled_1h": llm_retry_scheduled_1h,
            "ics_delta_components_total_1m": ics_delta_components_total_1m,
            "ics_delta_changed_components_1m": ics_delta_changed_components_1m,
            "ics_delta_removed_components_1m": ics_delta_removed_components_1m,
            "ics_delta_parse_failures_1h": ics_delta_parse_failures_1h,
        },
    }
