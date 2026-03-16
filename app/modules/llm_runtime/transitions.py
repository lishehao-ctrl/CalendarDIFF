from __future__ import annotations

from datetime import timedelta

import redis
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.ingestion import ConnectorResultStatus, IngestJobStatus
from app.db.models.input import SyncRequestStatus
from app.modules.input_control_plane.source_term_rebind import apply_pending_term_rebind_if_terminal
from app.modules.runtime_kernel import (
    apply_dead_letter_transition,
    apply_retry_transition,
    apply_success_transition,
    compute_retry_delay_seconds,
    copy_job_payload,
    load_job_context,
    upsert_ingest_result_and_outbox_once,
    utcnow,
)
from app.modules.runtime_kernel.parse_task_queue import increment_parse_metric_counter, schedule_parse_retry


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
        if context.source is not None:
            apply_pending_term_rebind_if_terminal(
                db=db,
                source=context.source,
                terminal_status=SyncRequestStatus.FAILED,
                applied_at=now,
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
            schedule_parse_retry(
                redis_client,
                request_id=request_id,
                source_id=context.job.source_id,
                attempt=next_attempt,
                reason=reason,
                available_at=due_at,
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
            if context.source is not None:
                apply_pending_term_rebind_if_terminal(
                    db=db,
                    source=context.source,
                    terminal_status=SyncRequestStatus.FAILED,
                    applied_at=now,
                )
            db.commit()
            return

        increment_parse_metric_counter(redis_client, metric_name="llm_retry_scheduled")
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
    if context.source is not None:
        apply_pending_term_rebind_if_terminal(
            db=db,
            source=context.source,
            terminal_status=SyncRequestStatus.FAILED,
            applied_at=now,
        )
    db.commit()


def apply_llm_backpressure_transition(
    db: Session,
    *,
    redis_client: redis.Redis,
    request_id: str,
    source_id: int,
    attempt: int,
    reason: str,
) -> None:
    now = utcnow()
    due_at = now + timedelta(seconds=1)
    context = load_job_context(db, request_id=request_id, lock_job=True)
    if context is None:
        return
    schedule_parse_retry(
        redis_client,
        request_id=request_id,
        source_id=source_id,
        attempt=max(attempt, 0),
        reason=reason,
        available_at=due_at,
    )
    payload = copy_job_payload(context.job)
    payload["workflow_stage"] = "LLM_RATE_LIMIT_BACKPRESSURE"
    payload["llm_backpressure_until"] = due_at.isoformat()
    context.job.payload_json = payload
    context.job.next_retry_at = due_at
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
        apply_cursor_patch=False,
        touch_source_success_state=False,
        sync_status=SyncRequestStatus.RUNNING,
    )
    db.commit()


__all__ = [
    "apply_llm_backpressure_transition",
    "apply_llm_failure_transition",
    "mark_llm_success",
]
