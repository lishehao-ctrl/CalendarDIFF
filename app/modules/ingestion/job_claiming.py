from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session, aliased

from app.core.config import get_settings
from app.db.models import IngestJob, IngestJobStatus, InputSource, SyncRequest, SyncRequestStatus
from app.modules.ingestion.job_lifecycle import (
    JobContext,
    apply_dead_letter_transition,
    apply_retry_transition,
    compute_retry_delay_seconds,
    utcnow,
)


CONNECTOR_BATCH_SIZE = 50


def requeue_stale_claimed_jobs(db: Session) -> int:
    settings = get_settings()
    now = utcnow()
    timeout_seconds = max(30, int(settings.llm_claim_timeout_seconds))
    cutoff = now - timedelta(seconds=timeout_seconds)
    rows = db.scalars(
        select(IngestJob)
        .where(
            IngestJob.status == IngestJobStatus.CLAIMED,
            IngestJob.updated_at <= cutoff,
            or_(IngestJob.next_retry_at.is_(None), IngestJob.next_retry_at <= now),
        )
        .order_by(IngestJob.id.asc())
        .with_for_update(skip_locked=True)
        .limit(CONNECTOR_BATCH_SIZE)
    ).all()
    if not rows:
        return 0

    max_attempts = max(1, int(settings.llm_max_retry_attempts))
    for row in rows:
        sync_request = db.scalar(select(SyncRequest).where(SyncRequest.request_id == row.request_id))
        source = db.get(InputSource, row.source_id)
        context = JobContext(job=row, sync_request=sync_request, source=source)
        attempt = row.attempt + 1
        error_code = "llm_claim_timeout_requeue"
        error_message = "claimed job timed out before completion"

        if attempt < max_attempts:
            due_at = now + timedelta(
                seconds=compute_retry_delay_seconds(
                    attempt=attempt,
                    base_seconds=int(settings.llm_retry_base_seconds),
                    max_seconds=int(settings.llm_retry_max_seconds),
                    jitter_seconds=int(settings.llm_retry_jitter_seconds),
                )
            )
            apply_retry_transition(
                context=context,
                error_code=error_code,
                error_message=error_message,
                next_attempt=attempt,
                due_at=due_at,
                workflow_stage="CLAIM_TIMEOUT_REQUEUED",
                payload_extra={"next_retry_at": due_at.isoformat()},
                sync_status=SyncRequestStatus.QUEUED,
                job_status=IngestJobStatus.PENDING,
                clear_claim=True,
            )
            continue

        apply_dead_letter_transition(
            context=context,
            error_code=error_code,
            error_message=error_message,
            attempt=attempt,
            dead_lettered_at=now,
            workflow_stage="CLAIM_TIMEOUT_DEAD_LETTER",
            clear_claim=True,
            attempt_mode="set",
        )
    db.commit()
    return len(rows)


def claim_jobs(db: Session, *, worker_id: str, batch_size: int = CONNECTOR_BATCH_SIZE) -> list[IngestJob]:
    now = utcnow()
    older = aliased(IngestJob)
    rows = db.scalars(
        select(IngestJob)
        .where(
            IngestJob.status == IngestJobStatus.PENDING,
            or_(IngestJob.next_retry_at.is_(None), IngestJob.next_retry_at <= now),
            ~exists(
                select(1).where(
                    older.source_id == IngestJob.source_id,
                    older.id < IngestJob.id,
                    older.status.in_([IngestJobStatus.PENDING, IngestJobStatus.CLAIMED]),
                )
            ),
        )
        .order_by(IngestJob.id.asc())
        .with_for_update(skip_locked=True)
        .limit(batch_size)
    ).all()
    claimed: list[IngestJob] = []
    for row in rows:
        row.status = IngestJobStatus.CLAIMED
        row.claimed_by = worker_id
        row.claim_token = uuid4().hex
        row.updated_at = now
        sync_request = db.scalar(select(SyncRequest).where(SyncRequest.request_id == row.request_id))
        if sync_request is not None:
            sync_request.status = SyncRequestStatus.RUNNING
            sync_request.error_code = None
            sync_request.error_message = None
        claimed.append(row)
    db.commit()
    return claimed


def extract_ics_component_fingerprints(cursor: dict) -> dict[str, str]:
    raw = cursor.get("ics_component_fingerprints_v1")
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not key.strip():
            continue
        if not isinstance(value, str) or not value.strip():
            continue
        normalized[key.strip()] = value.strip()
    return normalized


__all__ = [
    "CONNECTOR_BATCH_SIZE",
    "claim_jobs",
    "extract_ics_component_fingerprints",
    "requeue_stale_claimed_jobs",
]
