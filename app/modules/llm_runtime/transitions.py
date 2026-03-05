from __future__ import annotations

from datetime import timedelta

import redis
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.ingestion import ConnectorResultStatus, IngestJobStatus
from app.db.models.input import SyncRequestStatus
from app.modules.runtime_kernel import (
    apply_dead_letter_transition,
    apply_retry_transition,
    apply_success_transition,
    compute_retry_delay_seconds,
    load_job_context,
    upsert_ingest_result_and_outbox_once,
    utcnow,
)
from app.modules.llm_runtime.queue import increment_metric_counter, schedule_retry_task


def apply_llm_failure_transition(
    db: Session,
    *,
    redis_client: redis.Redis,
    stream_key: str,
    request_id: str,
    next_attempt: int,
    error_code: str,
    error_message: str,
    reason: str,
    retryable: bool = True,
) -> None:
    now = utcnow()
    settings = get_settings()
    context = load_job_context(db, request_id=request_id, lock_job=True)
    if context is None:
        return
    if context.sync_request is None or context.source is None:
        apply_dead_letter_transition(
            context=context,
            error_code="llm_retry_context_missing",
            error_message="missing context during retry scheduling",
            attempt=next_attempt,
            dead_lettered_at=now,
            workflow_stage="LLM_DEAD_LETTER",
            clear_claim=False,
            attempt_mode="max",
        )
        db.commit()
        return

    max_attempts = max(1, int(settings.llm_max_retry_attempts))
    if retryable and next_attempt < max_attempts:
        delay_seconds = compute_retry_delay_seconds(
            attempt=next_attempt,
            base_seconds=int(settings.llm_retry_base_seconds),
            max_seconds=int(settings.llm_retry_max_seconds),
            jitter_seconds=int(settings.llm_retry_jitter_seconds),
        )
        due_at = now + timedelta(seconds=delay_seconds)
        try:
            schedule_retry_task(
                redis_client,
                stream_key=stream_key,
                request_id=request_id,
                source_id=context.job.source_id,
                attempt=next_attempt,
                reason=reason,
                due_at=due_at,
            )
        except Exception as exc:
            apply_dead_letter_transition(
                context=context,
                error_code="llm_retry_schedule_failed",
                error_message=str(exc),
                attempt=next_attempt,
                dead_lettered_at=now,
                workflow_stage="LLM_DEAD_LETTER",
                clear_claim=False,
                attempt_mode="max",
            )
            db.commit()
            return

        increment_metric_counter(redis_client, metric_name="llm_retry_scheduled")
        apply_retry_transition(
            context=context,
            error_code=error_code,
            error_message=error_message,
            next_attempt=next_attempt,
            due_at=due_at,
            workflow_stage="LLM_RETRY_WAITING",
            payload_extra={
                "last_retry_scheduled_at": now.isoformat(),
                "llm_next_due_at": due_at.isoformat(),
            },
            sync_status=SyncRequestStatus.RUNNING,
            job_status=IngestJobStatus.CLAIMED,
            clear_claim=False,
        )
        db.commit()
        return

    apply_dead_letter_transition(
        context=context,
        error_code=error_code,
        error_message=error_message,
        attempt=next_attempt,
        dead_lettered_at=now,
        workflow_stage="LLM_DEAD_LETTER",
        clear_claim=False,
        attempt_mode="max",
    )
    db.commit()


def mark_llm_success(
    db: Session,
    *,
    request_id: str,
    records: list[dict],
    result_status: ConnectorResultStatus,
    cursor_patch: dict,
) -> None:
    now = utcnow()
    context = load_job_context(db, request_id=request_id, lock_job=True)
    if context is None or context.sync_request is None:
        return
    if context.source is None:
        apply_dead_letter_transition(
            context=context,
            error_code="llm_source_missing_on_success",
            error_message="source row disappeared before success commit",
            attempt=context.job.attempt + 1,
            dead_lettered_at=now,
            workflow_stage="LLM_DEAD_LETTER",
            clear_claim=False,
            attempt_mode="max",
        )
        db.commit()
        return

    upsert_ingest_result_and_outbox_once(
        db,
        request_id=request_id,
        source_id=context.source.id,
        provider=context.source.provider,
        result_status=result_status,
        cursor_patch=cursor_patch,
        records=records,
        fetched_at=now,
    )
    apply_success_transition(
        context=context,
        completed_at=now,
        cursor_patch=cursor_patch,
        payload_workflow_stage="LLM_SUCCEEDED",
        payload_updates={"llm_finished_at": now.isoformat()},
        payload_remove_keys=["llm_parse_payload"],
    )
    db.commit()


__all__ = [
    "apply_llm_failure_transition",
    "mark_llm_success",
]
