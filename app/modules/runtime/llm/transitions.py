from __future__ import annotations

from datetime import timedelta
from typing import Literal

import redis
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.runtime import ConnectorResultStatus, IngestJobStatus
from app.db.models.input import SyncRequestStage, SyncRequestStatus
from app.modules.sources.source_monitoring_window_rebind import apply_pending_monitoring_window_update_if_terminal
from app.modules.runtime.kernel import (
    apply_dead_letter_transition,
    apply_retry_transition,
    apply_success_transition,
    build_sync_progress_payload,
    compute_retry_delay_seconds,
    copy_job_payload,
    load_job_context,
    set_sync_runtime_state,
    upsert_ingest_result_and_outbox_once,
    utcnow,
)
from app.modules.runtime.kernel.parse_task_queue import increment_parse_metric_counter, schedule_parse_retry


LlmTaskKind = Literal["generic", "gmail", "calendar_component", "calendar_reduce"]


def llm_task_running_state(*, task_kind: LlmTaskKind) -> tuple[SyncRequestStage, str, dict]:
    if task_kind == "calendar_component":
        return (
            SyncRequestStage.LLM_PARSE,
            "calendar_child_parse",
            build_sync_progress_payload(
                phase="calendar_child_parse",
                label="Parsing calendar child event",
                detail="A calendar component child parse task is running.",
            ),
        )
    if task_kind == "calendar_reduce":
        return (
            SyncRequestStage.LLM_PARSE,
            "calendar_reduce_running",
            build_sync_progress_payload(
                phase="calendar_reduce",
                label="Reducing calendar parse results",
                detail="Calendar child parse results are being reduced into one provider result.",
            ),
        )
    if task_kind == "gmail":
        return (
            SyncRequestStage.LLM_PARSE,
            "gmail_parse_running",
            build_sync_progress_payload(
                phase="gmail_llm_parse",
                label="Extracting Gmail events",
                detail="The parser is extracting grade-relevant signals from queued emails.",
            ),
        )
    return (
        SyncRequestStage.LLM_PARSE,
        "llm_parse",
        build_sync_progress_payload(
            phase="llm_parse",
            label="LLM extraction running",
            detail="The parser is extracting semantic records from provider payload.",
        ),
    )


def llm_task_retry_state(*, task_kind: LlmTaskKind) -> tuple[SyncRequestStage, str]:
    if task_kind == "calendar_reduce":
        return SyncRequestStage.PROVIDER_REDUCE, "calendar_reduce_retry"
    return SyncRequestStage.LLM_PARSE, "llm_retry_waiting"


def mark_llm_task_started(
    db: Session,
    *,
    request_id: str,
    worker_id: str,
    task_kind: LlmTaskKind,
) -> None:
    now = utcnow()
    settings = get_settings()
    context = load_job_context(db, request_id=request_id, lock_job=True)
    if context is None or context.sync_request is None:
        return
    payload = copy_job_payload(context.job)
    payload["workflow_stage"] = "LLM_RUNNING"
    payload["llm_worker_id"] = worker_id
    payload["llm_started_at"] = now.isoformat()
    context.job.payload_json = payload
    context.job.next_retry_at = now + timedelta(seconds=max(30, int(settings.llm_claim_timeout_seconds)))
    sync_stage, sync_substage, sync_progress = llm_task_running_state(task_kind=task_kind)
    set_sync_runtime_state(
        context.sync_request,
        status=SyncRequestStatus.RUNNING,
        stage=sync_stage,
        substage=sync_substage,
        progress=sync_progress,
        error_code=None,
        error_message=None,
        when=now,
    )
    db.commit()


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
    task_kind: LlmTaskKind = "generic",
    retryable: bool = True,
) -> None:
    now = utcnow()
    settings = get_settings()
    context = load_job_context(db, request_id=request_id, lock_job=True)
    if context is None:
        return
    sync_stage, sync_substage = llm_task_retry_state(task_kind=task_kind)
    if context.sync_request is None or context.source is None:
        apply_dead_letter_transition(
            context=context,
            error_code="llm_retry_context_missing",
            error_message="missing context during retry scheduling",
            attempt=next_attempt,
            dead_lettered_at=now,
            workflow_stage="LLM_DEAD_LETTER",
            sync_substage="llm_retry_context_missing",
            sync_progress=build_sync_progress_payload(
                phase="failed",
                label="LLM task failed",
                detail="Missing sync/source context during LLM retry scheduling.",
            ),
            clear_claim=False,
            attempt_mode="max",
        )
        if context.source is not None:
            apply_pending_monitoring_window_update_if_terminal(
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
                sync_substage="llm_retry_schedule_failed",
                sync_progress=build_sync_progress_payload(
                    phase="failed",
                    label="LLM retry scheduling failed",
                    detail=str(exc),
                ),
                clear_claim=False,
                attempt_mode="max",
            )
            if context.source is not None:
                apply_pending_monitoring_window_update_if_terminal(
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
            sync_stage=sync_stage,
            sync_substage=sync_substage,
            sync_progress=build_sync_progress_payload(
                phase="llm_retry_waiting",
                label="LLM retry scheduled",
                detail="The LLM task failed and was scheduled for another attempt.",
            ),
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
        sync_substage="llm_dead_letter",
        sync_progress=build_sync_progress_payload(
            phase="failed",
            label="LLM task failed",
            detail=error_message,
        ),
        clear_claim=False,
        attempt_mode="max",
    )
    if context.source is not None:
        apply_pending_monitoring_window_update_if_terminal(
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
    task_kind: LlmTaskKind = "generic",
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
    if context.sync_request is not None:
        sync_stage, _sync_substage, _sync_progress = llm_task_running_state(task_kind=task_kind)
        set_sync_runtime_state(
            context.sync_request,
            status=SyncRequestStatus.RUNNING,
            stage=sync_stage,
            substage="llm_backpressure",
            progress=build_sync_progress_payload(
                phase="llm_backpressure",
                label="Waiting for LLM capacity",
                detail="The runtime is applying short backpressure before retrying LLM work.",
            ),
            when=now,
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
        payload_remove_keys=["llm_parse_payload", "sync_progress", "sync_progress_updated_at", "connector_continuation"],
        apply_cursor_patch=False,
        touch_source_success_state=False,
        sync_status=SyncRequestStatus.RUNNING,
        sync_stage=SyncRequestStage.RESULT_READY,
        sync_substage="llm_result_ready",
        sync_progress=build_sync_progress_payload(
            phase="result_ready",
            label="Result ready to apply",
            detail=f"{len(records)} parsed records are ready for canonical apply.",
            current=len(records),
            total=len(records),
            percent=100,
            unit="records",
            updated_at=now,
        ),
    )
    db.commit()


__all__ = [
    "apply_llm_backpressure_transition",
    "apply_llm_failure_transition",
    "llm_task_retry_state",
    "llm_task_running_state",
    "mark_llm_task_started",
    "mark_llm_success",
]
