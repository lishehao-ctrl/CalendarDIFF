from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.runtime import IngestJob, IngestJobStatus
from app.db.models.input import InputSource, SyncRequest, SyncRequestStage, SyncRequestStatus
from app.modules.runtime.connectors.calendar_fanout_contract import is_calendar_component_reason, is_calendar_reduce_reason
from app.modules.runtime.kernel import (
    JobContext,
    apply_dead_letter_transition,
    build_sync_progress_payload,
    copy_job_payload,
    set_sync_runtime_state,
    utcnow,
)
from app.modules.runtime.kernel.parse_task_queue import ParseTaskMessage


@dataclass(frozen=True)
class MessagePreflight:
    should_parse: bool
    ack_on_skip: bool
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
    is_calendar_component = is_calendar_component_reason(message.reason)
    job_stmt = select(IngestJob).where(IngestJob.request_id == message.request_id)
    if not is_calendar_component:
        job_stmt = job_stmt.with_for_update()
    job = db.scalar(job_stmt)
    if job is None:
        return MessagePreflight(
            should_parse=False,
            ack_on_skip=False,
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
            sync_substage="llm_context_missing",
            sync_progress=build_sync_progress_payload(
                phase="failed",
                label="LLM task failed",
                detail="Missing sync/source context for LLM task.",
            ),
            clear_claim=False,
            attempt_mode="max",
        )
        db.commit()
        return MessagePreflight(
            should_parse=False,
            ack_on_skip=False,
            parse_payload={},
            cursor_patch={},
            provider_hint="",
        )

    if job.status == IngestJobStatus.SUCCEEDED:
        return MessagePreflight(
            should_parse=False,
            ack_on_skip=True,
            parse_payload={},
            cursor_patch={},
            provider_hint="",
        )
    if job.status in {IngestJobStatus.FAILED, IngestJobStatus.DEAD_LETTER}:
        return MessagePreflight(
            should_parse=False,
            ack_on_skip=True,
            parse_payload={},
            cursor_patch={},
            provider_hint="",
        )
    if job.status != IngestJobStatus.CLAIMED:
        return MessagePreflight(
            should_parse=False,
            ack_on_skip=False,
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
            sync_substage="llm_parse_payload_missing",
            sync_progress=build_sync_progress_payload(
                phase="failed",
                label="LLM task failed",
                detail="Missing llm_parse_payload for queued LLM task.",
            ),
            clear_claim=False,
            attempt_mode="max",
        )
        db.commit()
        return MessagePreflight(
            should_parse=False,
            ack_on_skip=False,
            parse_payload={},
            cursor_patch={},
            provider_hint="",
        )

    if not isinstance(cursor_patch, dict):
        cursor_patch = {}

    if is_calendar_component:
        set_sync_runtime_state(
            sync_request,
            status=SyncRequestStatus.RUNNING,
            stage=SyncRequestStage.LLM_PARSE,
            substage="calendar_child_parse",
            progress=build_sync_progress_payload(
                phase="calendar_child_parse",
                label="Parsing calendar child event",
                detail="A calendar component child parse task is running.",
            ),
            error_code=None,
            error_message=None,
            when=now,
        )
        db.commit()
        return MessagePreflight(
            should_parse=True,
            ack_on_skip=True,
            parse_payload=parse_payload,
            cursor_patch=cursor_patch,
            provider_hint=str(payload.get("provider") or ""),
        )

    payload["workflow_stage"] = "LLM_RUNNING"
    payload["llm_worker_id"] = worker_id
    payload["llm_started_at"] = now.isoformat()
    job.payload_json = payload
    settings = get_settings()
    job.next_retry_at = now + timedelta(seconds=max(30, int(settings.llm_claim_timeout_seconds)))
    parse_kind = str(parse_payload.get("kind") or "").strip().lower()
    substage = "llm_parse"
    progress = build_sync_progress_payload(
        phase="llm_parse",
        label="LLM extraction running",
        detail="The parser is extracting semantic records from provider payload.",
    )
    if parse_kind == "gmail":
        substage = "gmail_parse_running"
        progress = build_sync_progress_payload(
            phase="gmail_llm_parse",
            label="Extracting Gmail events",
            detail="The parser is extracting grade-relevant signals from queued emails.",
        )
    elif parse_kind == "calendar_delta" or is_calendar_reduce_reason(message.reason):
        substage = "calendar_reduce_running"
        progress = build_sync_progress_payload(
            phase="calendar_reduce",
            label="Reducing calendar parse results",
            detail="Calendar child parse results are being reduced into one provider result.",
        )
    set_sync_runtime_state(
        sync_request,
        status=SyncRequestStatus.RUNNING,
        stage=SyncRequestStage.LLM_PARSE,
        substage=substage,
        progress=progress,
        error_code=None,
        error_message=None,
        when=now,
    )
    db.commit()

    return MessagePreflight(
        should_parse=True,
        ack_on_skip=True,
        parse_payload=parse_payload,
        cursor_patch=cursor_patch,
        provider_hint=str(payload.get("provider") or ""),
    )


__all__ = [
    "MessagePreflight",
    "prepare_message_for_processing",
]
