from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from app.db.models.runtime import ConnectorResultStatus, IngestJobStatus
from app.db.models.input import SyncRequestStage, SyncRequestStatus
from app.modules.runtime.connectors.connector_types import ConnectorFailureDecision
from app.modules.sources.source_term_rebind import apply_pending_term_rebind_if_terminal
from app.modules.runtime.kernel import (
    JobContext,
    apply_dead_letter_transition,
    apply_retry_transition,
    apply_success_transition,
    build_sync_progress_payload,
    compute_retry_delay_seconds,
    copy_job_payload,
    upsert_ingest_result_and_outbox_once,
    utcnow,
    set_sync_runtime_state,
)


def apply_success_without_llm(
    db: Session,
    *,
    context: JobContext,
    result_status: ConnectorResultStatus,
    cursor_patch: dict,
) -> None:
    if context.sync_request is None or context.source is None:
        return
    fetched_at = utcnow()
    record_count = 0
    upsert_ingest_result_and_outbox_once(
        db,
        request_id=context.sync_request.request_id,
        source_id=context.source.id,
        provider=context.source.provider,
        result_status=result_status,
        cursor_patch=cursor_patch,
        records=[],
        fetched_at=fetched_at,
    )
    apply_success_transition(
        context=context,
        completed_at=fetched_at,
        cursor_patch=cursor_patch,
        payload_workflow_stage="RESULT_READY",
        payload_remove_keys=["sync_progress", "sync_progress_updated_at", "connector_continuation"],
        apply_cursor_patch=False,
        touch_source_success_state=False,
        sync_status=SyncRequestStatus.RUNNING,
        sync_stage=SyncRequestStage.RESULT_READY,
        sync_substage="connector_result_ready",
        sync_progress=build_sync_progress_payload(
            phase="result_ready",
            label="Result ready to apply",
            detail="Connector fetch finished and the result is ready for canonical apply.",
            current=record_count,
            total=record_count,
            percent=100,
            unit="records",
            updated_at=fetched_at,
        ),
    )


def apply_failure(
    db: Session,
    *,
    context: JobContext,
    decision: ConnectorFailureDecision,
    max_retry_attempts: int,
    retry_base_seconds: int,
    retry_max_seconds: int,
    retry_jitter_seconds: int,
) -> None:
    now = utcnow()
    next_attempt = context.job.attempt + 1
    max_attempts = max(1, int(max_retry_attempts))
    if decision.retryable and next_attempt < max_attempts:
        due_at = now + timedelta(
            seconds=compute_retry_delay_seconds(
                attempt=next_attempt,
                base_seconds=retry_base_seconds,
                max_seconds=retry_max_seconds,
                jitter_seconds=retry_jitter_seconds,
            )
        )
        apply_retry_transition(
            context=context,
            error_code=decision.normalized_code,
            error_message=decision.normalized_message,
            next_attempt=next_attempt,
            due_at=due_at,
            workflow_stage="CONNECTOR_RETRY_WAITING",
            payload_extra={"next_retry_at": due_at.isoformat()},
            sync_status=SyncRequestStatus.QUEUED,
            sync_stage=SyncRequestStage.CONNECTOR_FETCH,
            sync_substage="connector_retry_waiting",
            sync_progress=build_sync_progress_payload(
                phase="connector_fetch",
                label="Retry scheduled",
                detail="Connector fetch failed and has been queued for another attempt.",
            ),
            job_status=IngestJobStatus.PENDING,
            clear_claim=True,
        )
        return

    apply_dead_letter_transition(
        context=context,
        error_code=decision.normalized_code,
        error_message=decision.normalized_message,
        attempt=next_attempt,
        dead_lettered_at=now,
        workflow_stage="CONNECTOR_DEAD_LETTER",
        sync_substage="connector_dead_letter",
        sync_progress=build_sync_progress_payload(
            phase="failed",
            label="Connector fetch failed",
            detail=decision.normalized_message,
        ),
        clear_claim=True,
        attempt_mode="set",
    )
    if context.source is not None:
        apply_pending_term_rebind_if_terminal(
            db=db,
            source=context.source,
            terminal_status=SyncRequestStatus.FAILED,
            applied_at=now,
        )


def mark_llm_enqueue_pending(
    *,
    context: JobContext,
    result_status: ConnectorResultStatus,
    cursor_patch: dict,
    parse_payload: dict,
    claim_timeout_seconds: int,
) -> None:
    if context.sync_request is None or context.source is None:
        return
    now = utcnow()
    payload = copy_job_payload(context.job)
    payload["provider"] = context.source.provider
    payload["workflow_stage"] = "LLM_ENQUEUE_PENDING"
    payload["llm_enqueue_pending_at"] = now.isoformat()
    payload["llm_task_id"] = context.sync_request.request_id
    payload["llm_parse_payload"] = parse_payload
    payload["llm_cursor_patch"] = cursor_patch
    payload["connector_status"] = result_status.value
    payload["llm_enqueue_dispatch_attempt"] = int(payload.get("llm_enqueue_dispatch_attempt") or 0)
    payload.pop("connector_continuation", None)
    payload.pop("sync_progress", None)
    payload.pop("sync_progress_updated_at", None)
    context.job.payload_json = payload
    context.job.status = IngestJobStatus.CLAIMED
    context.job.next_retry_at = now + timedelta(seconds=max(30, int(claim_timeout_seconds)))
    queue_detail = "Connector fetch finished and parser queue dispatch is next."
    if parse_payload.get("kind") == "calendar_delta":
        queue_detail = "Calendar delta is ready to fan out into child parse tasks."
    set_sync_runtime_state(
        context.sync_request,
        status=SyncRequestStatus.RUNNING,
        stage=SyncRequestStage.LLM_QUEUE,
        substage="parse_payload_ready",
        progress=build_sync_progress_payload(
            phase="llm_queue",
            label="Parser queue ready",
            detail=queue_detail,
        ),
        error_code=None,
        error_message=None,
        when=now,
    )


__all__ = [
    "apply_failure",
    "apply_success_without_llm",
    "mark_llm_enqueue_pending",
]
