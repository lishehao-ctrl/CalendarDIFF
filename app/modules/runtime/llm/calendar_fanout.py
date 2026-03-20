from __future__ import annotations

from datetime import UTC, datetime, timedelta

import redis
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.models.runtime import CalendarComponentParseStatus, CalendarComponentParseTask, ConnectorResultStatus
from app.db.models.input import SyncRequestStage, SyncRequestStatus
from app.modules.runtime.connectors.calendar_component_tasks import upsert_calendar_component_tasks
from app.modules.runtime.connectors.calendar_fanout_contract import (
    CALENDAR_REDUCE_REASON,
    build_calendar_component_reason,
    is_calendar_fanout_reason,
    is_calendar_reduce_reason,
    parse_component_key_from_reason,
)
from app.modules.runtime.connectors.ics_delta import external_event_id_from_component_key
from app.modules.runtime.connectors.llm_parsers import LlmParseError, ParserContext
from app.modules.runtime.llm.message_preflight import MessagePreflight
from app.modules.runtime.llm.parse_pipeline import (
    RateLimitRejected,
    normalize_calendar_changed_component_input,
    parse_calendar_changed_component_with_llm,
)
from app.modules.runtime.kernel import (
    apply_success_transition,
    build_sync_progress_payload,
    copy_job_payload,
    set_sync_runtime_state,
    load_job_context,
    upsert_ingest_result_and_outbox_once,
    utcnow,
)
from app.modules.runtime.kernel.parse_task_queue import enqueue_parse_task, schedule_parse_retry

TERMINAL_COMPONENT_STATUSES = {
    CalendarComponentParseStatus.SUCCEEDED,
    CalendarComponentParseStatus.UNRESOLVED,
    CalendarComponentParseStatus.FAILED,
}
CALENDAR_REDUCE_RETRY_DELAY_SECONDS = 2


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
            redis_client=redis_client,
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
        component_task = _ensure_component_task(
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
            _mark_component_terminal(
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
        return _requeue_rate_limited_component(
            message=message,
            session_factory=session_factory,
            redis_client=redis_client,
            component_key=component_key,
            error_message=f"llm limiter rejected: {exc.reason}",
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


def _requeue_rate_limited_component(
    *,
    message,
    session_factory: sessionmaker[Session],
    redis_client: redis.Redis,
    component_key: str,
    error_message: str,
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
        schedule_parse_retry(
            redis_client=redis_client,
            request_id=message.request_id,
            source_id=message.source_id,
            attempt=max(message.attempt, 0),
            reason=message.reason,
            available_at=due_at,
        )
        db.commit()
    return True


def _process_calendar_reduce_message(
    *,
    message,
    preflight: MessagePreflight,
    redis_client: redis.Redis,
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
        running_exists = any(row.status == CalendarComponentParseStatus.RUNNING for row in rows)
        pending_exists = any(
            row.status in {CalendarComponentParseStatus.PENDING, CalendarComponentParseStatus.RUNNING}
            for row in rows
        )
        if pending_exists:
            pending_count = sum(
                1 for row in rows if row.status in {CalendarComponentParseStatus.PENDING, CalendarComponentParseStatus.RUNNING}
            )
            reduce_retry_due_at = _ensure_calendar_reduce_retry_scheduled(
                context=context,
                redis_client=redis_client,
                request_id=message.request_id,
                source_id=message.source_id,
            )
            requeued_count = _requeue_stale_pending_components(
                rows=rows,
                redis_client=redis_client,
                request_id=message.request_id,
                source_id=message.source_id,
                allow_immediate_requeue=not running_exists,
            )
            _touch_job_running(
                context=context,
                stage="LLM_CALENDAR_REDUCE_WAITING",
                sync_stage=SyncRequestStage.PROVIDER_REDUCE,
                sync_substage="calendar_reduce_wait",
                sync_progress=build_sync_progress_payload(
                    phase="calendar_reduce_wait",
                    label="Waiting for calendar child parses",
                    detail=f"{pending_count} calendar child tasks are still pending before reduce can commit.",
                    current=len(rows) - pending_count,
                    total=len(rows) if rows else None,
                    unit="events" if rows else None,
                ),
                extra={
                    "calendar_component_pending": pending_count,
                    "calendar_component_requeued": requeued_count,
                    "calendar_reduce_retry_due_at": reduce_retry_due_at.isoformat(),
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
    component_task: CalendarComponentParseTask,
    status: CalendarComponentParseStatus,
    error_code: str,
    error_message: str,
) -> None:
    component_task.status = status
    component_task.error_code = error_code
    component_task.error_message = error_message
    component_task.finished_at = utcnow()


def _touch_job_running(
    *,
    context,
    stage: str,
    sync_stage: SyncRequestStage | None = None,
    sync_substage: str | None = None,
    sync_progress: dict | None = None,
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
        set_sync_runtime_state(
            context.sync_request,
            status=SyncRequestStatus.RUNNING,
            stage=sync_stage if sync_stage is not None else context.sync_request.stage,
            substage=sync_substage,
            progress=sync_progress,
            error_code=None,
            error_message=None,
            when=now,
        )


def _ensure_calendar_reduce_retry_scheduled(
    *,
    context,
    redis_client: redis.Redis,
    request_id: str,
    source_id: int,
) -> datetime:
    now = utcnow()
    payload = copy_job_payload(context.job)
    existing_due_at = _parse_optional_datetime(payload.get("calendar_reduce_retry_due_at"))
    if existing_due_at is not None and existing_due_at > now:
        return existing_due_at
    due_at = now + timedelta(seconds=CALENDAR_REDUCE_RETRY_DELAY_SECONDS)
    schedule_parse_retry(
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


def _parse_optional_datetime(value: object) -> datetime | None:
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


def _requeue_stale_pending_components(
    *,
    rows: list[CalendarComponentParseTask],
    redis_client: redis.Redis,
    request_id: str,
    source_id: int,
    allow_immediate_requeue: bool,
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
        enqueue_parse_task(
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
    "is_calendar_fanout_reason",
    "process_calendar_fanout_message",
]
