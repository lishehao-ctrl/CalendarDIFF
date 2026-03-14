from __future__ import annotations

from datetime import timedelta

import redis
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.models.ingestion import CalendarComponentParseStatus, CalendarComponentParseTask, ConnectorResultStatus
from app.db.models.input import SyncRequestStatus
from app.modules.ingestion.calendar_component_tasks import upsert_calendar_component_tasks
from app.modules.ingestion.calendar_fanout_contract import (
    CALENDAR_REDUCE_REASON,
    is_calendar_fanout_reason,
    is_calendar_reduce_reason,
    parse_component_key_from_reason,
)
from app.modules.ingestion.ics_delta import external_event_id_from_component_key
from app.modules.ingestion.llm_parsers import LlmParseError, ParserContext
from app.modules.llm_runtime.message_preflight import MessagePreflight
from app.modules.llm_runtime.parse_pipeline import (
    RateLimitRejected,
    normalize_calendar_changed_component_input,
    parse_calendar_changed_component_with_llm,
)
from app.modules.runtime_kernel import (
    apply_success_transition,
    copy_job_payload,
    load_job_context,
    upsert_ingest_result_and_outbox_once,
    utcnow,
)
from app.modules.runtime_kernel.parse_task_queue import enqueue_parse_task

TERMINAL_COMPONENT_STATUSES = {
    CalendarComponentParseStatus.SUCCEEDED,
    CalendarComponentParseStatus.UNRESOLVED,
    CalendarComponentParseStatus.FAILED,
}


def process_calendar_fanout_message(
    *,
    message,
    preflight: MessagePreflight,
    redis_client: redis.Redis,
    stream_key: str,
    session_factory: sessionmaker[Session],
) -> bool:
    if is_calendar_reduce_reason(message.reason):
        return _process_calendar_reduce_message(
            message=message,
            preflight=preflight,
            session_factory=session_factory,
        )
    component_key = parse_component_key_from_reason(message.reason)
    if component_key is None:
        return False
    return _process_calendar_component_message(
        message=message,
        component_key=component_key,
        preflight=preflight,
        redis_client=redis_client,
        stream_key=stream_key,
        session_factory=session_factory,
    )


def _process_calendar_component_message(
    *,
    message,
    component_key: str,
    preflight: MessagePreflight,
    redis_client: redis.Redis,
    stream_key: str,
    session_factory: sessionmaker[Session],
) -> bool:
    parse_payload = preflight.parse_payload if isinstance(preflight.parse_payload, dict) else {}
    changed_components = parse_payload.get("changed_components")
    changed_rows = changed_components if isinstance(changed_components, list) else []

    with session_factory() as db:
        context = load_job_context(db, request_id=message.request_id, lock_job=True)
        if context is None or context.sync_request is None or context.source is None:
            return True
        component_task = _ensure_component_task(
            db=db,
            request_id=message.request_id,
            source_id=context.source.id,
            component_key=component_key,
            changed_components=changed_rows,
        )
        if component_task is None:
            return True
        if component_task.status in TERMINAL_COMPONENT_STATUSES:
            return True
        if component_task.status == CalendarComponentParseStatus.RUNNING:
            now = utcnow()
            settings = get_settings()
            started_at = component_task.started_at
            timeout_cutoff = now - timedelta(seconds=max(30, int(settings.llm_claim_timeout_seconds)))
            if started_at is not None and started_at >= timeout_cutoff:
                return True

        component_task.status = CalendarComponentParseStatus.RUNNING
        component_task.attempt = max(int(component_task.attempt or 0), 0) + 1
        component_task.started_at = utcnow()
        component_task.error_code = None
        component_task.error_message = None
        _touch_job_running(context=context, stage="LLM_CALENDAR_COMPONENT_RUNNING")
        db.commit()

        attempt = int(component_task.attempt)
        source_id = context.source.id
        provider = context.source.provider
        normalized_component = normalize_calendar_changed_component_input(
            {
                "component_key": component_task.component_key,
                "external_event_id": component_task.external_event_id,
                "component_ical_b64": component_task.component_ical_b64,
                "fingerprint": component_task.fingerprint,
            }
        )
        if normalized_component is None:
            _mark_component_terminal(
                db=db,
                context=context,
                component_task=component_task,
                status=CalendarComponentParseStatus.UNRESOLVED,
                error_code="llm_calendar_delta_payload_invalid",
                error_message="missing calendar component payload for child parse task",
            )
            db.commit()
            enqueue_parse_task(
                redis_client=redis_client,
                request_id=message.request_id,
                source_id=source_id,
                attempt=0,
                reason=CALENDAR_REDUCE_REASON,
            )
            return True

    try:
        with session_factory() as db:
            parser_context = ParserContext(
                source_id=message.source_id,
                provider=preflight.provider_hint or provider,
                source_kind="calendar",
                request_id=message.request_id,
            )
            parsed_records = parse_calendar_changed_component_with_llm(
                db=db,
                redis_client=redis_client,
                stream_key=stream_key,
                provider=preflight.provider_hint or provider,
                context=parser_context,
                component=normalized_component,
            )
    except RateLimitRejected as exc:
        return _handle_retryable_component_error(
            message=message,
            session_factory=session_factory,
            redis_client=redis_client,
            component_key=component_key,
            error_code="llm_rate_limited",
            error_message=f"llm limiter rejected: {exc.reason}",
            attempt=attempt,
            retryable=True,
        )
    except LlmParseError as exc:
        return _handle_retryable_component_error(
            message=message,
            session_factory=session_factory,
            redis_client=redis_client,
            component_key=component_key,
            error_code=exc.code,
            error_message=str(exc),
            attempt=attempt,
            retryable=bool(exc.retryable),
        )
    except Exception as exc:  # pragma: no cover - defensive guard
        return _handle_retryable_component_error(
            message=message,
            session_factory=session_factory,
            redis_client=redis_client,
            component_key=component_key,
            error_code="parse_llm_worker_exception",
            error_message=str(exc),
            attempt=attempt,
            retryable=True,
        )

    parsed_record = _first_calendar_record(parsed_records)
    with session_factory() as db:
        context = load_job_context(db, request_id=message.request_id, lock_job=True)
        if context is None or context.sync_request is None or context.source is None:
            return True
        component_task = db.scalar(
            select(CalendarComponentParseTask)
            .where(
                CalendarComponentParseTask.request_id == message.request_id,
                CalendarComponentParseTask.component_key == component_key,
            )
            .with_for_update()
        )
        if component_task is None:
            return True
        if parsed_record is None:
            _mark_component_terminal(
                db=db,
                context=context,
                component_task=component_task,
                status=CalendarComponentParseStatus.UNRESOLVED,
                error_code="llm_calendar_component_record_missing",
                error_message="calendar child parse produced no calendar.event.extracted record",
            )
        else:
            component_task.status = CalendarComponentParseStatus.SUCCEEDED
            component_task.parsed_record_json = parsed_record
            component_task.error_code = None
            component_task.error_message = None
            component_task.finished_at = utcnow()
            _touch_job_running(context=context, stage="LLM_CALENDAR_COMPONENT_SUCCEEDED")
        db.commit()

    enqueue_parse_task(
        redis_client=redis_client,
        request_id=message.request_id,
        source_id=message.source_id,
        attempt=0,
        reason=CALENDAR_REDUCE_REASON,
    )
    return True


def _handle_retryable_component_error(
    *,
    message,
    session_factory: sessionmaker[Session],
    redis_client: redis.Redis,
    component_key: str,
    error_code: str,
    error_message: str,
    attempt: int,
    retryable: bool,
) -> bool:
    settings = get_settings()
    max_attempts = max(1, int(settings.llm_max_retry_attempts))
    with session_factory() as db:
        context = load_job_context(db, request_id=message.request_id, lock_job=True)
        if context is None or context.sync_request is None or context.source is None:
            return True
        component_task = db.scalar(
            select(CalendarComponentParseTask)
            .where(
                CalendarComponentParseTask.request_id == message.request_id,
                CalendarComponentParseTask.component_key == component_key,
            )
            .with_for_update()
        )
        if component_task is None:
            return True
        if retryable and attempt < max_attempts:
            component_task.status = CalendarComponentParseStatus.PENDING
            component_task.error_code = error_code
            component_task.error_message = error_message
            component_task.finished_at = utcnow()
            _touch_job_running(context=context, stage="LLM_CALENDAR_COMPONENT_RETRY_PENDING")
            db.commit()
            enqueue_parse_task(
                redis_client=redis_client,
                request_id=message.request_id,
                source_id=message.source_id,
                attempt=attempt,
                reason=message.reason,
            )
            return True

        terminal_status = CalendarComponentParseStatus.UNRESOLVED if not retryable else CalendarComponentParseStatus.FAILED
        _mark_component_terminal(
            db=db,
            context=context,
            component_task=component_task,
            status=terminal_status,
            error_code=error_code,
            error_message=error_message,
        )
        db.commit()

    enqueue_parse_task(
        redis_client=redis_client,
        request_id=message.request_id,
        source_id=message.source_id,
        attempt=0,
        reason=CALENDAR_REDUCE_REASON,
    )
    return True


def _process_calendar_reduce_message(
    *,
    message,
    preflight: MessagePreflight,
    session_factory: sessionmaker[Session],
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
        pending_exists = any(
            row.status in {CalendarComponentParseStatus.PENDING, CalendarComponentParseStatus.RUNNING}
            for row in rows
        )
        if pending_exists:
            _touch_job_running(
                context=context,
                stage="LLM_CALENDAR_REDUCE_WAITING",
                extra={
                    "calendar_component_pending": sum(
                        1 for row in rows if row.status in {CalendarComponentParseStatus.PENDING, CalendarComponentParseStatus.RUNNING}
                    )
                },
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
            payload_remove_keys=["llm_parse_payload"],
        )
        db.commit()
        return True


def _first_calendar_record(parsed_records: list[dict]) -> dict | None:
    for row in parsed_records:
        if not isinstance(row, dict):
            continue
        if row.get("record_type") != "calendar.event.extracted":
            continue
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue
        return row
    return None


def _ensure_component_task(
    *,
    db: Session,
    request_id: str,
    source_id: int,
    component_key: str,
    changed_components: list[dict],
) -> CalendarComponentParseTask | None:
    row = db.scalar(
        select(CalendarComponentParseTask)
        .where(
            CalendarComponentParseTask.request_id == request_id,
            CalendarComponentParseTask.component_key == component_key,
        )
        .with_for_update()
    )
    if row is not None:
        return row

    upsert_calendar_component_tasks(
        db,
        request_id=request_id,
        source_id=source_id,
        changed_components=changed_components,
    )
    db.flush()
    return db.scalar(
        select(CalendarComponentParseTask)
        .where(
            CalendarComponentParseTask.request_id == request_id,
            CalendarComponentParseTask.component_key == component_key,
        )
        .with_for_update()
    )


def _mark_component_terminal(
    *,
    db: Session,
    context,
    component_task: CalendarComponentParseTask,
    status: CalendarComponentParseStatus,
    error_code: str,
    error_message: str,
) -> None:
    component_task.status = status
    component_task.error_code = error_code
    component_task.error_message = error_message
    component_task.finished_at = utcnow()
    _touch_job_running(
        context=context,
        stage="LLM_CALENDAR_COMPONENT_TERMINAL",
    )


def _touch_job_running(
    *,
    context,
    stage: str,
    extra: dict | None = None,
) -> None:
    now = utcnow()
    settings = get_settings()
    payload = copy_job_payload(context.job)
    payload["workflow_stage"] = stage
    if extra:
        payload.update(extra)
    context.job.payload_json = payload
    context.job.next_retry_at = now + timedelta(seconds=max(30, int(settings.llm_claim_timeout_seconds)))
    if context.sync_request is not None:
        context.sync_request.status = SyncRequestStatus.RUNNING
        context.sync_request.error_code = None
        context.sync_request.error_message = None


__all__ = [
    "is_calendar_fanout_reason",
    "process_calendar_fanout_message",
]
