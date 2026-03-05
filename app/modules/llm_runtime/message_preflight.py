from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.ingestion import IngestJob, IngestJobStatus
from app.db.models.input import InputSource, SyncRequest, SyncRequestStatus
from app.modules.runtime_kernel import JobContext, apply_dead_letter_transition, copy_job_payload, utcnow
from app.modules.runtime_kernel.parse_task_queue import ParseTaskMessage


@dataclass(frozen=True)
class MessagePreflight:
    should_parse: bool
    parse_payload: dict
    cursor_patch: dict
    provider_hint: str


def prepare_message_for_processing(
    db: Session,
    *,
    message: ParseTaskMessage,
    worker_id: str,
) -> MessagePreflight:
    now = utcnow()
    job = db.scalar(
        select(IngestJob).where(IngestJob.request_id == message.request_id).with_for_update(skip_locked=True)
    )
    if job is None:
        return MessagePreflight(
            should_parse=False,
            parse_payload={},
            cursor_patch={},
            provider_hint="",
        )

    sync_request = db.scalar(select(SyncRequest).where(SyncRequest.request_id == message.request_id))
    source = db.get(InputSource, job.source_id)
    if sync_request is None or source is None:
        apply_dead_letter_transition(
            context=JobContext(job=job, sync_request=sync_request, source=source),
            error_code="llm_context_missing",
            error_message="missing sync_request/source for llm task",
            attempt=max(job.attempt, message.attempt) + 1,
            dead_lettered_at=now,
            workflow_stage="LLM_DEAD_LETTER",
            clear_claim=False,
            attempt_mode="max",
        )
        db.commit()
        return MessagePreflight(
            should_parse=False,
            parse_payload={},
            cursor_patch={},
            provider_hint="",
        )

    if job.status == IngestJobStatus.SUCCEEDED:
        return MessagePreflight(
            should_parse=False,
            parse_payload={},
            cursor_patch={},
            provider_hint="",
        )
    if job.status in {IngestJobStatus.FAILED, IngestJobStatus.DEAD_LETTER}:
        return MessagePreflight(
            should_parse=False,
            parse_payload={},
            cursor_patch={},
            provider_hint="",
        )
    if job.status != IngestJobStatus.CLAIMED:
        return MessagePreflight(
            should_parse=False,
            parse_payload={},
            cursor_patch={},
            provider_hint="",
        )

    payload = copy_job_payload(job)
    parse_payload = payload.get("llm_parse_payload")
    cursor_patch = payload.get("llm_cursor_patch")
    if not isinstance(parse_payload, dict):
        apply_dead_letter_transition(
            context=JobContext(job=job, sync_request=sync_request, source=source),
            error_code="llm_parse_payload_missing",
            error_message="llm_parse_payload is missing or invalid",
            attempt=max(job.attempt, message.attempt) + 1,
            dead_lettered_at=now,
            workflow_stage="LLM_DEAD_LETTER",
            clear_claim=False,
            attempt_mode="max",
        )
        db.commit()
        return MessagePreflight(
            should_parse=False,
            parse_payload={},
            cursor_patch={},
            provider_hint="",
        )

    if not isinstance(cursor_patch, dict):
        cursor_patch = {}

    payload["workflow_stage"] = "LLM_RUNNING"
    payload["llm_worker_id"] = worker_id
    payload["llm_started_at"] = now.isoformat()
    job.payload_json = payload
    settings = get_settings()
    job.next_retry_at = now + timedelta(seconds=max(30, int(settings.llm_claim_timeout_seconds)))
    sync_request.status = SyncRequestStatus.RUNNING
    db.commit()

    return MessagePreflight(
        should_parse=True,
        parse_payload=parse_payload,
        cursor_patch=cursor_patch,
        provider_hint=str(payload.get("provider") or ""),
    )


__all__ = [
    "MessagePreflight",
    "prepare_message_for_processing",
]
