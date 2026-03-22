from __future__ import annotations

from datetime import timedelta

import redis
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.models.runtime import CalendarComponentParseStatus, CalendarComponentParseTask
from app.db.models.input import SyncRequestStage, SyncRequestStatus
from app.modules.runtime.connectors.calendar_component_tasks import upsert_calendar_component_tasks
from app.modules.runtime.connectors.calendar_fanout_contract import CALENDAR_REDUCE_REASON
from app.modules.runtime.connectors.llm_parsers import LlmParseError, ParserContext
from app.modules.runtime.llm.message_preflight import MessagePreflight
from app.modules.runtime.llm.parse_pipeline import (
    RateLimitRejected,
    normalize_calendar_changed_component_input,
    parse_calendar_changed_component_with_llm,
)
from app.modules.runtime.kernel import build_sync_progress_payload, load_job_context, set_sync_runtime_state, utcnow
from app.modules.runtime.kernel.parse_task_queue import enqueue_parse_task, schedule_parse_retry


TERMINAL_COMPONENT_STATUSES = {
    CalendarComponentParseStatus.SUCCEEDED,
    CalendarComponentParseStatus.UNRESOLVED,
    CalendarComponentParseStatus.FAILED,
}


def process_calendar_component_message_impl(
    *,
    message,
    component_key: str,
    preflight: MessagePreflight,
    redis_client: redis.Redis,
    stream_key: str,
    session_factory: sessionmaker[Session],
    parse_calendar_changed_component_with_llm_fn,
    enqueue_parse_task_fn,
    schedule_parse_retry_fn,
) -> bool:
    parse_payload = preflight.parse_payload if isinstance(preflight.parse_payload, dict) else {}
    changed_components = parse_payload.get("changed_components")
    changed_rows = changed_components if isinstance(changed_components, list) else []

    with session_factory() as db:
        component_task = ensure_component_task(
            db=db,
            request_id=message.request_id,
            source_id=message.source_id,
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
        component_task.finished_at = None
        component_task.error_code = None
        component_task.error_message = None
        db.commit()
        if context := load_job_context(db, request_id=message.request_id, lock_job=False):
            if context.sync_request is not None:
                total_components = len(changed_rows)
                set_sync_runtime_state(
                    context.sync_request,
                    status=SyncRequestStatus.RUNNING,
                    stage=SyncRequestStage.LLM_PARSE,
                    substage="calendar_child_parse",
                    progress=build_sync_progress_payload(
                        phase="calendar_child_parse",
                        label="Parsing calendar child events",
                        detail="Calendar component child tasks are running.",
                        current=None,
                        total=total_components if total_components > 0 else None,
                        unit="events" if total_components > 0 else None,
                    ),
                )
                db.commit()

        attempt = int(component_task.attempt)
        source_id = message.source_id
        provider = preflight.provider_hint or "calendar"
        normalized_component = normalize_calendar_changed_component_input(
            {
                "component_key": component_task.component_key,
                "external_event_id": component_task.external_event_id,
                "component_ical_b64": component_task.component_ical_b64,
                "fingerprint": component_task.fingerprint,
            }
        )
        if normalized_component is None:
            mark_component_terminal(
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
            parsed_records = parse_calendar_changed_component_with_llm_fn(
                db=db,
                redis_client=redis_client,
                stream_key=stream_key,
                provider=preflight.provider_hint or provider,
                context=parser_context,
                component=normalized_component,
            )
    except RateLimitRejected as exc:
        return _requeue_rate_limited_component(
            message=message,
            session_factory=session_factory,
            redis_client=redis_client,
            component_key=component_key,
            error_message=f"llm limiter rejected: {exc.reason}",
            schedule_parse_retry_fn=schedule_parse_retry_fn,
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
            enqueue_parse_task_fn=enqueue_parse_task_fn,
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
            enqueue_parse_task_fn=enqueue_parse_task_fn,
        )

    parsed_record = first_calendar_record(parsed_records)
    with session_factory() as db:
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
            mark_component_terminal(
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
        db.commit()

    enqueue_parse_task_fn(
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
    enqueue_parse_task_fn,
) -> bool:
    settings = get_settings()
    max_attempts = max(1, int(settings.llm_max_retry_attempts))
    with session_factory() as db:
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
            db.commit()
            enqueue_parse_task_fn(
                redis_client=redis_client,
                request_id=message.request_id,
                source_id=message.source_id,
                attempt=attempt,
                reason=message.reason,
            )
            return True

        terminal_status = CalendarComponentParseStatus.UNRESOLVED if not retryable else CalendarComponentParseStatus.FAILED
        mark_component_terminal(
            component_task=component_task,
            status=terminal_status,
            error_code=error_code,
            error_message=error_message,
        )
        db.commit()

    enqueue_parse_task_fn(
        redis_client=redis_client,
        request_id=message.request_id,
        source_id=message.source_id,
        attempt=0,
        reason=CALENDAR_REDUCE_REASON,
    )
    return True


def _requeue_rate_limited_component(
    *,
    message,
    session_factory: sessionmaker[Session],
    redis_client: redis.Redis,
    component_key: str,
    error_message: str,
    schedule_parse_retry_fn,
) -> bool:
    due_at = utcnow() + timedelta(seconds=1)
    with session_factory() as db:
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
        component_task.status = CalendarComponentParseStatus.PENDING
        component_task.attempt = max(int(component_task.attempt or 0) - 1, 0)
        component_task.error_code = "llm_rate_limited"
        component_task.error_message = error_message
        component_task.finished_at = utcnow()
        schedule_parse_retry_fn(
            redis_client=redis_client,
            request_id=message.request_id,
            source_id=message.source_id,
            attempt=max(message.attempt, 0),
            reason=message.reason,
            available_at=due_at,
        )
        db.commit()
    return True


def ensure_component_task(
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


def mark_component_terminal(
    *,
    component_task: CalendarComponentParseTask,
    status: CalendarComponentParseStatus,
    error_code: str,
    error_message: str,
) -> None:
    component_task.status = status
    component_task.error_code = error_code
    component_task.error_message = error_message
    component_task.finished_at = utcnow()


def first_calendar_record(parsed_records: list[dict]) -> dict | None:
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


__all__ = [
    "TERMINAL_COMPONENT_STATUSES",
    "ensure_component_task",
    "first_calendar_record",
    "mark_component_terminal",
    "process_calendar_component_message_impl",
]
