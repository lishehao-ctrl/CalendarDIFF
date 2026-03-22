from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.runtime import IngestJob, IngestJobStatus
from app.db.models.input import InputSource, SyncRequest
from app.modules.runtime.connectors.calendar_fanout_contract import is_calendar_component_reason, is_calendar_reduce_reason
from app.modules.runtime.kernel import (
    JobContext,
    apply_dead_letter_transition,
    build_sync_progress_payload,
    copy_job_payload,
    utcnow,
)
from app.modules.runtime.llm.transitions import LlmTaskKind
from app.modules.runtime.kernel.parse_task_queue import ParseTaskMessage


@dataclass(frozen=True)
class MessagePreflight:
    should_parse: bool
    ack_on_skip: bool
    parse_payload: dict
    cursor_patch: dict
    provider_hint: str
    task_kind: LlmTaskKind


def prepare_message_for_processing(
    db: Session,
    *,
    message: ParseTaskMessage,
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
            task_kind="generic",
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
            task_kind="generic",
        )

    if job.status == IngestJobStatus.SUCCEEDED:
        return MessagePreflight(
            should_parse=False,
            ack_on_skip=True,
            parse_payload={},
            cursor_patch={},
            provider_hint="",
            task_kind="generic",
        )
    if job.status in {IngestJobStatus.FAILED, IngestJobStatus.DEAD_LETTER}:
        return MessagePreflight(
            should_parse=False,
            ack_on_skip=True,
            parse_payload={},
            cursor_patch={},
            provider_hint="",
            task_kind="generic",
        )
    if job.status != IngestJobStatus.CLAIMED:
        return MessagePreflight(
            should_parse=False,
            ack_on_skip=False,
            parse_payload={},
            cursor_patch={},
            provider_hint="",
            task_kind="generic",
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
            task_kind="generic",
        )

    if not isinstance(cursor_patch, dict):
        cursor_patch = {}

    parse_kind = str(parse_payload.get("kind") or "").strip().lower()
    task_kind: LlmTaskKind = "generic"
    if is_calendar_component:
        task_kind = "calendar_component"
    elif parse_kind == "gmail":
        task_kind = "gmail"
    elif parse_kind == "calendar_delta" or is_calendar_reduce_reason(message.reason):
        task_kind = "calendar_reduce"

    return MessagePreflight(
        should_parse=True,
        ack_on_skip=True,
        parse_payload=parse_payload,
        cursor_patch=cursor_patch,
        provider_hint=str(payload.get("provider") or ""),
        task_kind=task_kind,
    )


__all__ = [
    "MessagePreflight",
    "prepare_message_for_processing",
]
