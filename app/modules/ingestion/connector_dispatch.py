from __future__ import annotations

from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import IngestJob, IngestJobStatus, InputSource, SyncRequest, SyncRequestStatus
from app.modules.ingestion.job_claiming import CONNECTOR_BATCH_SIZE
from app.modules.ingestion.job_lifecycle import (
    JobContext,
    apply_dead_letter_transition,
    apply_retry_transition,
    compute_retry_delay_seconds,
    copy_job_payload,
    truncate_error,
    utcnow,
)
from app.modules.llm_runtime.queue import ensure_stream_group, get_redis_client, queue_group, queue_stream_key
from app.modules.llm_runtime.queue_producer import enqueue_llm_task


def dispatch_pending_llm_enqueues(db: Session) -> int:
    settings = get_settings()
    now = utcnow()
    rows = db.scalars(
        select(IngestJob)
        .where(
            IngestJob.status == IngestJobStatus.CLAIMED,
            or_(IngestJob.next_retry_at.is_(None), IngestJob.next_retry_at <= now),
        )
        .order_by(IngestJob.id.asc())
        .with_for_update(skip_locked=True)
        .limit(CONNECTOR_BATCH_SIZE)
    ).all()
    if not rows:
        return 0

    redis_client = get_redis_client()
    stream_key = queue_stream_key()
    ensure_stream_group(redis_client, stream_key=stream_key, group_name=queue_group())
    dispatched = 0
    dispatch_threshold = 3

    for job in rows:
        payload = copy_job_payload(job)
        if payload.get("workflow_stage") != "LLM_ENQUEUE_PENDING":
            continue
        parse_payload = payload.get("llm_parse_payload")
        if not isinstance(parse_payload, dict):
            continue
        sync_request = db.scalar(select(SyncRequest).where(SyncRequest.request_id == job.request_id))
        source = db.get(InputSource, job.source_id)
        context = JobContext(job=job, sync_request=sync_request, source=source)
        if sync_request is None or source is None:
            apply_dead_letter_transition(
                context=context,
                error_code="llm_enqueue_context_missing",
                error_message="missing sync_request/source for llm enqueue dispatch",
                attempt=job.attempt + 1,
                dead_lettered_at=now,
                workflow_stage="CONNECTOR_DEAD_LETTER",
                clear_claim=True,
                attempt_mode="set",
            )
            continue

        try:
            enqueue_llm_task(
                redis_client=redis_client,
                request_id=sync_request.request_id,
                source_id=source.id,
                attempt=job.attempt,
                reason="initial",
            )
            payload["workflow_stage"] = "LLM_QUEUED"
            payload["llm_enqueued_at"] = now.isoformat()
            payload.pop("llm_enqueue_last_error", None)
            payload.pop("llm_enqueue_last_failed_at", None)
            job.payload_json = payload
            job.next_retry_at = now + timedelta(seconds=max(30, int(settings.llm_claim_timeout_seconds)))
            sync_request.status = SyncRequestStatus.RUNNING
            sync_request.error_code = None
            sync_request.error_message = None
            dispatched += 1
            continue
        except Exception as exc:
            attempts = int(payload.get("llm_enqueue_dispatch_attempt") or 0) + 1
            payload["llm_enqueue_dispatch_attempt"] = attempts
            payload["llm_enqueue_last_error"] = truncate_error(str(exc))
            payload["llm_enqueue_last_failed_at"] = now.isoformat()
            if attempts < dispatch_threshold:
                payload["workflow_stage"] = "LLM_ENQUEUE_PENDING"
                job.payload_json = payload
                retry_due = now + timedelta(
                    seconds=compute_retry_delay_seconds(
                        attempt=attempts,
                        base_seconds=int(settings.llm_retry_base_seconds),
                        max_seconds=int(settings.llm_retry_max_seconds),
                        jitter_seconds=int(settings.llm_retry_jitter_seconds),
                    )
                )
                job.next_retry_at = retry_due
                sync_request.status = SyncRequestStatus.RUNNING
                sync_request.error_code = "llm_queue_unavailable"
                sync_request.error_message = truncate_error(str(exc))
                source.last_error_code = "llm_queue_unavailable"
                source.last_error_message = truncate_error(str(exc))
                continue

            due_at = now + timedelta(
                seconds=compute_retry_delay_seconds(
                    attempt=job.attempt + 1,
                    base_seconds=int(settings.llm_retry_base_seconds),
                    max_seconds=int(settings.llm_retry_max_seconds),
                    jitter_seconds=int(settings.llm_retry_jitter_seconds),
                )
            )
            apply_retry_transition(
                context=context,
                error_code="llm_queue_unavailable",
                error_message=str(exc),
                next_attempt=job.attempt + 1,
                due_at=due_at,
                workflow_stage="CONNECTOR_RETRY_WAITING",
                payload_extra={
                    "next_retry_at": due_at.isoformat(),
                    "llm_enqueue_dispatch_attempt": attempts,
                    "llm_enqueue_last_error": truncate_error(str(exc)),
                },
                sync_status=SyncRequestStatus.QUEUED,
                job_status=IngestJobStatus.PENDING,
                clear_claim=True,
            )
    db.commit()
    return dispatched


__all__ = ["dispatch_pending_llm_enqueues"]
