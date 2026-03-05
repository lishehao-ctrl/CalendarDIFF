from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.events import new_event
from app.db.models import (
    ConnectorResultStatus,
    IngestJob,
    IngestJobStatus,
    IngestResult,
    InputSource,
    IntegrationOutbox,
    OutboxStatus,
    SyncRequest,
    SyncRequestStatus,
)


@dataclass(frozen=True)
class JobContext:
    job: IngestJob
    sync_request: SyncRequest | None
    source: InputSource | None


def load_job_context(
    db: Session,
    *,
    request_id: str,
    lock_job: bool = True,
) -> JobContext | None:
    stmt = select(IngestJob).where(IngestJob.request_id == request_id)
    if lock_job:
        stmt = stmt.with_for_update()
    job = db.scalar(stmt)
    if job is None:
        return None
    sync_request = db.scalar(select(SyncRequest).where(SyncRequest.request_id == request_id))
    source = db.get(InputSource, job.source_id)
    return JobContext(job=job, sync_request=sync_request, source=source)


def copy_job_payload(job: IngestJob) -> dict:
    if isinstance(job.payload_json, dict):
        return dict(job.payload_json)
    return {}


def truncate_error(message: str, *, max_len: int = 512) -> str:
    value = (message or "").strip()
    if len(value) <= max_len:
        return value
    return value[:max_len]


def compute_retry_delay_seconds(
    *,
    attempt: int,
    base_seconds: int,
    max_seconds: int,
    jitter_seconds: int,
) -> int:
    exponent = max(attempt - 1, 0)
    base = max(1, int(base_seconds))
    ceiling = max(base, int(max_seconds))
    jitter = max(0, int(jitter_seconds))
    delay = min(base * (2**exponent), ceiling)
    if jitter > 0:
        delay += random.randint(0, jitter)
    return max(1, int(delay))


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


def upsert_ingest_result_and_outbox_once(
    db: Session,
    *,
    request_id: str,
    source_id: int,
    provider: str,
    result_status: ConnectorResultStatus,
    cursor_patch: dict,
    records: list[dict],
    fetched_at: datetime,
) -> bool:
    existing_result = db.scalar(select(IngestResult).where(IngestResult.request_id == request_id))
    if existing_result is not None:
        return False

    db.add(
        IngestResult(
            request_id=request_id,
            source_id=source_id,
            provider=provider,
            status=result_status,
            cursor_patch=cursor_patch,
            records=records,
            fetched_at=fetched_at,
            error_code=None,
            error_message=None,
        )
    )
    event = new_event(
        event_type="ingest.result.ready",
        aggregate_type="ingest_result",
        aggregate_id=request_id,
        payload={
            "request_id": request_id,
            "source_id": source_id,
            "provider": provider,
            "status": result_status.value,
        },
    )
    db.add(
        IntegrationOutbox(
            event_id=event.event_id,
            event_type=event.event_type,
            aggregate_type=event.aggregate_type,
            aggregate_id=event.aggregate_id,
            payload_json=event.payload,
            status=OutboxStatus.PENDING,
            available_at=event.available_at,
        )
    )
    return True


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


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


__all__ = [
    "JobContext",
    "apply_dead_letter_transition",
    "apply_retry_transition",
    "apply_success_transition",
    "compute_retry_delay_seconds",
    "copy_job_payload",
    "load_job_context",
    "truncate_error",
    "upsert_ingest_result_and_outbox_once",
    "utcnow",
]
