from __future__ import annotations

from datetime import UTC, datetime, timedelta

import redis
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.models.runtime import CalendarComponentParseStatus, CalendarComponentParseTask, ConnectorResultStatus
from app.db.models.input import SyncRequestStage, SyncRequestStatus
from app.modules.runtime.connectors.calendar_fanout_contract import CALENDAR_REDUCE_REASON, build_calendar_component_reason
from app.modules.runtime.connectors.ics_delta import external_event_id_from_component_key
from app.modules.runtime.llm.message_preflight import MessagePreflight
from app.modules.runtime.kernel import (
    apply_success_transition,
    build_sync_progress_payload,
    copy_job_payload,
    load_job_context,
    set_sync_runtime_state,
    upsert_ingest_result_and_outbox_once,
    utcnow,
)
from app.modules.runtime.kernel.parse_task_queue import enqueue_parse_task, schedule_parse_retry


CALENDAR_REDUCE_RETRY_DELAY_SECONDS = 2


def process_calendar_reduce_message_impl(
    *,
    message,
    preflight: MessagePreflight,
    redis_client: redis.Redis,
    session_factory: sessionmaker[Session],
    enqueue_parse_task_fn,
    schedule_parse_retry_fn,
) -> bool:
    parse_payload = preflight.parse_payload if isinstance(preflight.parse_payload, dict) else {}
    cursor_patch = preflight.cursor_patch if isinstance(preflight.cursor_patch, dict) else {}
    removed_component_keys = parse_payload.get("removed_component_keys")
    removed_keys = removed_component_keys if isinstance(removed_component_keys, list) else []

    with session_factory() as db:
        context = load_job_context(db, request_id=message.request_id, lock_job=True)
        if context is None or context.sync_request is None or context.source is None:
            return True

        rows = list(
            db.scalars(
                select(CalendarComponentParseTask)
                .where(CalendarComponentParseTask.request_id == message.request_id)
                .order_by(CalendarComponentParseTask.component_key.asc())
            ).all()
        )
        running_exists = any(row.status == CalendarComponentParseStatus.RUNNING for row in rows)
        pending_exists = any(
            row.status in {CalendarComponentParseStatus.PENDING, CalendarComponentParseStatus.RUNNING}
            for row in rows
        )
        if pending_exists:
            pending_count = sum(
                1 for row in rows if row.status in {CalendarComponentParseStatus.PENDING, CalendarComponentParseStatus.RUNNING}
            )
            reduce_retry_due_at = ensure_calendar_reduce_retry_scheduled(
                context=context,
                redis_client=redis_client,
                request_id=message.request_id,
                source_id=message.source_id,
                schedule_parse_retry_fn=schedule_parse_retry_fn,
            )
            requeued_count = requeue_stale_pending_components(
                rows=rows,
                redis_client=redis_client,
                request_id=message.request_id,
                source_id=message.source_id,
                allow_immediate_requeue=not running_exists,
                enqueue_parse_task_fn=enqueue_parse_task_fn,
            )
            touch_calendar_reduce_waiting(
                context=context,
                pending_count=pending_count,
                total_rows=len(rows),
                requeued_count=requeued_count,
                reduce_retry_due_at=reduce_retry_due_at,
            )
            db.commit()
            return True

        records: list[dict] = []
        for raw_key in removed_keys:
            if not isinstance(raw_key, str) or not raw_key.strip():
                continue
            component_key = raw_key.strip()
            records.append(
                {
                    "record_type": "calendar.event.removed",
                    "payload": {
                        "component_key": component_key,
                        "external_event_id": external_event_id_from_component_key(component_key),
                    },
                }
            )

        for row in rows:
            if row.status != CalendarComponentParseStatus.SUCCEEDED:
                continue
            if isinstance(row.parsed_record_json, dict):
                records.append(row.parsed_record_json)

        result_status = ConnectorResultStatus.CHANGED if records else ConnectorResultStatus.NO_CHANGE
        now = utcnow()
        set_sync_runtime_state(
            context.sync_request,
            status=SyncRequestStatus.RUNNING,
            stage=SyncRequestStage.PROVIDER_REDUCE,
            substage="calendar_reduce_commit",
            progress=build_sync_progress_payload(
                phase="calendar_reduce_commit",
                label="Committing calendar reduce result",
                detail=f"Reducing {len(rows)} calendar component tasks into one provider result.",
                current=len(rows) if rows else None,
                total=len(rows) if rows else None,
                percent=100 if rows else None,
                unit="events" if rows else None,
                updated_at=now,
            ),
            error_code=None,
            error_message=None,
            when=now,
        )
        upsert_ingest_result_and_outbox_once(
            db,
            request_id=message.request_id,
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
            payload_updates={
                "calendar_component_summary": {
                    "total": len(rows),
                    "succeeded": sum(1 for row in rows if row.status == CalendarComponentParseStatus.SUCCEEDED),
                    "unresolved": sum(1 for row in rows if row.status == CalendarComponentParseStatus.UNRESOLVED),
                    "failed": sum(1 for row in rows if row.status == CalendarComponentParseStatus.FAILED),
                }
            },
            payload_remove_keys=["llm_parse_payload", "sync_progress", "sync_progress_updated_at", "calendar_reduce_retry_due_at"],
            apply_cursor_patch=False,
            touch_source_success_state=False,
            sync_status=SyncRequestStatus.RUNNING,
            sync_stage=SyncRequestStage.RESULT_READY,
            sync_substage="calendar_result_ready",
            sync_progress=build_sync_progress_payload(
                phase="result_ready",
                label="Calendar result ready to apply",
                detail=f"{len(records)} calendar records are ready for canonical apply.",
                current=len(records),
                total=len(records),
                percent=100,
                unit="records",
                updated_at=now,
            ),
        )
        db.commit()
        return True


def touch_calendar_reduce_waiting(
    *,
    context,
    pending_count: int,
    total_rows: int,
    requeued_count: int,
    reduce_retry_due_at: datetime,
) -> None:
    now = utcnow()
    settings = get_settings()
    payload = copy_job_payload(context.job)
    payload["workflow_stage"] = "LLM_CALENDAR_REDUCE_WAITING"
    payload["calendar_component_pending"] = pending_count
    payload["calendar_component_requeued"] = requeued_count
    payload["calendar_reduce_retry_due_at"] = reduce_retry_due_at.isoformat()
    context.job.payload_json = payload
    context.job.next_retry_at = now + timedelta(seconds=max(30, int(settings.llm_claim_timeout_seconds)))
    if context.sync_request is not None:
        set_sync_runtime_state(
            context.sync_request,
            status=SyncRequestStatus.RUNNING,
            stage=SyncRequestStage.PROVIDER_REDUCE,
            substage="calendar_reduce_wait",
            progress=build_sync_progress_payload(
                phase="calendar_reduce_wait",
                label="Waiting for calendar child parses",
                detail=f"{pending_count} calendar child tasks are still pending before reduce can commit.",
                current=total_rows - pending_count,
                total=total_rows if total_rows else None,
                unit="events" if total_rows else None,
            ),
            error_code=None,
            error_message=None,
            when=now,
        )


def ensure_calendar_reduce_retry_scheduled(
    *,
    context,
    redis_client: redis.Redis,
    request_id: str,
    source_id: int,
    schedule_parse_retry_fn,
) -> datetime:
    now = utcnow()
    payload = copy_job_payload(context.job)
    existing_due_at = parse_optional_datetime(payload.get("calendar_reduce_retry_due_at"))
    if existing_due_at is not None and existing_due_at > now:
        return existing_due_at
    due_at = now + timedelta(seconds=CALENDAR_REDUCE_RETRY_DELAY_SECONDS)
    schedule_parse_retry_fn(
        redis_client=redis_client,
        request_id=request_id,
        source_id=source_id,
        attempt=0,
        reason=CALENDAR_REDUCE_REASON,
        available_at=due_at,
    )
    payload["calendar_reduce_retry_due_at"] = due_at.isoformat()
    context.job.payload_json = payload
    return due_at


def parse_optional_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def requeue_stale_pending_components(
    *,
    rows: list[CalendarComponentParseTask],
    redis_client: redis.Redis,
    request_id: str,
    source_id: int,
    allow_immediate_requeue: bool,
    enqueue_parse_task_fn,
) -> int:
    now = utcnow()
    stale_threshold = now - timedelta(seconds=5)
    requeued = 0
    for row in rows:
        if row.status != CalendarComponentParseStatus.PENDING:
            continue
        if row.started_at is not None:
            continue
        last_touch = row.updated_at or row.created_at
        if not allow_immediate_requeue and (last_touch is None or last_touch > stale_threshold):
            continue
        enqueue_parse_task_fn(
            redis_client=redis_client,
            request_id=request_id,
            source_id=source_id,
            attempt=max(int(row.attempt or 0), 0),
            reason=build_calendar_component_reason(row.component_key),
        )
        row.error_code = "llm_component_requeued"
        row.error_message = "requeued by reducer after component task remained pending without start"
        row.finished_at = now
        requeued += 1
    return requeued


__all__ = [
    "ensure_calendar_reduce_retry_scheduled",
    "process_calendar_reduce_message_impl",
    "requeue_stale_pending_components",
    "touch_calendar_reduce_waiting",
]
