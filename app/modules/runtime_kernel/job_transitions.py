from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from app.db.models.ingestion import IngestJob, IngestJobStatus
from app.db.models.input import InputSource, SyncRequestStatus
from app.modules.runtime_kernel.job_context import JobContext
from app.modules.runtime_kernel.retry_policy import truncate_error


def copy_job_payload(job: IngestJob) -> dict:
    if isinstance(job.payload_json, dict):
        return dict(job.payload_json)
    return {}


def apply_retry_transition(
    *,
    context: JobContext,
    error_code: str,
    error_message: str,
    next_attempt: int,
    due_at: datetime,
    workflow_stage: str,
    payload_extra: dict | None = None,
    sync_status: SyncRequestStatus,
    job_status: IngestJobStatus,
    clear_claim: bool = True,
) -> None:
    payload = copy_job_payload(context.job)
    payload["workflow_stage"] = workflow_stage
    payload["last_error_code"] = error_code
    payload["last_error_message"] = truncate_error(error_message)
    if payload_extra:
        payload.update(payload_extra)

    context.job.attempt = next_attempt
    context.job.status = job_status
    context.job.next_retry_at = due_at
    context.job.payload_json = payload
    if clear_claim:
        context.job.claimed_by = None
        context.job.claim_token = None

    if context.sync_request is not None:
        context.sync_request.status = sync_status
        context.sync_request.error_code = error_code
        context.sync_request.error_message = truncate_error(error_message)
    if context.source is not None:
        context.source.last_error_code = error_code
        context.source.last_error_message = truncate_error(error_message)


def apply_dead_letter_transition(
    *,
    context: JobContext,
    error_code: str,
    error_message: str,
    attempt: int,
    dead_lettered_at: datetime,
    workflow_stage: str,
    payload_extra: dict | None = None,
    clear_claim: bool = True,
    attempt_mode: Literal["set", "max"] = "set",
) -> None:
    payload = copy_job_payload(context.job)
    payload["workflow_stage"] = workflow_stage
    payload["last_error_code"] = error_code
    payload["last_error_message"] = truncate_error(error_message)
    payload["dead_lettered_at"] = dead_lettered_at.isoformat()
    if payload_extra:
        payload.update(payload_extra)

    context.job.status = IngestJobStatus.DEAD_LETTER
    context.job.dead_lettered_at = dead_lettered_at
    context.job.next_retry_at = None
    context.job.payload_json = payload
    if attempt_mode == "max":
        context.job.attempt = max(attempt, context.job.attempt + 1)
    else:
        context.job.attempt = attempt

    if clear_claim:
        context.job.claimed_by = None
        context.job.claim_token = None

    if context.sync_request is not None:
        context.sync_request.status = SyncRequestStatus.FAILED
        context.sync_request.error_code = error_code
        context.sync_request.error_message = truncate_error(error_message)
    if context.source is not None:
        context.source.last_error_code = error_code
        context.source.last_error_message = truncate_error(error_message)


def apply_success_transition(
    *,
    context: JobContext,
    completed_at: datetime,
    cursor_patch: dict,
    payload_workflow_stage: str | None = None,
    payload_updates: dict | None = None,
    payload_remove_keys: list[str] | None = None,
    min_poll_interval_seconds: int = 30,
) -> None:
    if context.source is not None and context.source.cursor is not None and cursor_patch:
        merged = dict(context.source.cursor.cursor_json or {})
        merged.update(cursor_patch)
        context.source.cursor.cursor_json = merged
        context.source.cursor.version += 1

    if context.source is not None:
        context.source.last_polled_at = completed_at
        context.source.next_poll_at = completed_at + timedelta(
            seconds=max(int(context.source.poll_interval_seconds), min_poll_interval_seconds)
        )
        context.source.last_error_code = None
        context.source.last_error_message = None

    payload = copy_job_payload(context.job)
    if payload_workflow_stage is not None:
        payload["workflow_stage"] = payload_workflow_stage
    if payload_updates:
        payload.update(payload_updates)
    if payload_remove_keys:
        for key in payload_remove_keys:
            payload.pop(key, None)

    context.job.payload_json = payload
    context.job.status = IngestJobStatus.SUCCEEDED
    context.job.next_retry_at = None
    if context.sync_request is not None:
        context.sync_request.status = SyncRequestStatus.SUCCEEDED
        context.sync_request.error_code = None
        context.sync_request.error_message = None


__all__ = [
    "apply_dead_letter_transition",
    "apply_retry_transition",
    "apply_success_transition",
    "copy_job_payload",
]
