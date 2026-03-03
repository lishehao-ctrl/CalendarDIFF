from __future__ import annotations

import base64
import logging
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

import redis
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.contracts.events import new_event
from app.core.config import get_settings
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
from app.modules.ingestion.ics_delta import external_event_id_from_component_key
from app.modules.ingestion.llm_parsers import (
    LlmParseError,
    ParserContext,
    parse_calendar_content,
    parse_gmail_payload,
)
from app.modules.ingestion.parser_records import attach_parser_metadata
from app.modules.llm_runtime.limiter import acquire_global_permit
from app.modules.llm_runtime.queue import (
    LlmQueueMessage,
    ack_stream_tasks,
    claim_idle_stream_tasks,
    consume_stream_tasks,
    ensure_stream_group,
    enqueue_stream_task,
    get_redis_client,
    increment_metric_counter,
    move_due_retry_tasks,
    queue_group,
    queue_stream_key,
    record_latency_ms,
    schedule_retry_task,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _TaskOutcome:
    message_id: str
    ack: bool


class _RateLimitRejected(RuntimeError):
    def __init__(self, *, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def run_llm_worker_tick(
    *,
    redis_client: redis.Redis,
    session_factory: sessionmaker[Session],
    worker_id: str,
) -> int:
    settings = get_settings()
    stream_key = queue_stream_key()
    group_name = queue_group()
    ensure_stream_group(redis_client, stream_key=stream_key, group_name=group_name)

    concurrency = max(1, int(settings.llm_worker_concurrency))
    move_due_retry_tasks(
        redis_client,
        stream_key=stream_key,
        now=datetime.now(timezone.utc),
        limit=max(concurrency * 2, 8),
    )
    reclaimed = claim_idle_stream_tasks(
        redis_client,
        stream_key=stream_key,
        group_name=group_name,
        consumer_name=worker_id,
        min_idle_ms=max(int(settings.llm_queue_consumer_poll_ms) * 3, 10_000),
        count=concurrency,
    )
    remaining = max(1, concurrency - len(reclaimed))
    fresh = consume_stream_tasks(
        redis_client,
        stream_key=stream_key,
        group_name=group_name,
        consumer_name=worker_id,
        count=remaining,
        block_ms=max(1, int(settings.llm_queue_consumer_poll_ms)),
    )
    messages = reclaimed + fresh
    if not messages:
        return 0

    outcomes: list[_TaskOutcome] = []
    max_workers = max(1, min(concurrency, len(messages)))
    if max_workers == 1:
        for message in messages:
            outcomes.append(
                _process_stream_message(
                    message=message,
                    redis_client=redis_client,
                    session_factory=session_factory,
                    worker_id=worker_id,
                    stream_key=stream_key,
                )
            )
    else:
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="llm-runtime") as pool:
            future_map = {
                pool.submit(
                    _process_stream_message,
                    message=message,
                    redis_client=redis_client,
                    session_factory=session_factory,
                    worker_id=worker_id,
                    stream_key=stream_key,
                ): message
                for message in messages
            }
            for future in as_completed(future_map):
                message = future_map[future]
                try:
                    outcomes.append(future.result())
                except Exception as exc:  # pragma: no cover - defensive worker guard
                    logger.error(
                        "llm worker task crashed request_id=%s source_id=%s error=%s",
                        message.request_id,
                        message.source_id,
                        str(exc),
                    )
                    outcomes.append(_TaskOutcome(message_id=message.message_id, ack=False))

    ack_ids = [row.message_id for row in outcomes if row.ack]
    ack_stream_tasks(redis_client, stream_key=stream_key, group_name=group_name, message_ids=ack_ids)
    return len(messages)


def run_llm_worker_loop(*, stop_event, worker_id: str, session_factory: sessionmaker[Session]) -> None:
    redis_client = get_redis_client()
    logger.info("starting llm worker loop worker_id=%s", worker_id)
    while not stop_event.is_set():
        started = time.monotonic()
        processed = 0
        try:
            processed = run_llm_worker_tick(
                redis_client=redis_client,
                session_factory=session_factory,
                worker_id=worker_id,
            )
        except Exception as exc:  # pragma: no cover - defensive worker guard
            logger.error("llm worker tick failed worker_id=%s error=%s", worker_id, str(exc))
        elapsed_ms = int((time.monotonic() - started) * 1000)
        if processed > 0:
            logger.info("llm worker tick worker_id=%s processed=%s latency_ms=%s", worker_id, processed, elapsed_ms)
        stop_event.wait(0.05)


def _process_stream_message(
    *,
    message: LlmQueueMessage,
    redis_client: redis.Redis,
    session_factory: sessionmaker[Session],
    worker_id: str,
    stream_key: str,
) -> _TaskOutcome:
    with session_factory() as db:
        now = datetime.now(timezone.utc)
        job = db.scalar(
            select(IngestJob).where(IngestJob.request_id == message.request_id).with_for_update(skip_locked=True)
        )
        if job is None:
            return _TaskOutcome(message_id=message.message_id, ack=True)

        sync_request = db.scalar(select(SyncRequest).where(SyncRequest.request_id == message.request_id))
        source = db.get(InputSource, job.source_id)
        if sync_request is None or source is None:
            _dead_letter(
                db,
                job=job,
                sync_request=sync_request,
                source=source,
                error_code="llm_context_missing",
                error_message="missing sync_request/source for llm task",
                attempt=max(job.attempt, message.attempt) + 1,
            )
            return _TaskOutcome(message_id=message.message_id, ack=True)

        if job.status == IngestJobStatus.SUCCEEDED:
            return _TaskOutcome(message_id=message.message_id, ack=True)
        if job.status in {IngestJobStatus.FAILED, IngestJobStatus.DEAD_LETTER}:
            return _TaskOutcome(message_id=message.message_id, ack=True)
        if job.status != IngestJobStatus.CLAIMED:
            return _TaskOutcome(message_id=message.message_id, ack=True)

        payload = _job_payload(job)
        parse_payload = payload.get("llm_parse_payload")
        cursor_patch = payload.get("llm_cursor_patch")
        if not isinstance(parse_payload, dict):
            _dead_letter(
                db,
                job=job,
                sync_request=sync_request,
                source=source,
                error_code="llm_parse_payload_missing",
                error_message="llm_parse_payload is missing or invalid",
                attempt=max(job.attempt, message.attempt) + 1,
            )
            return _TaskOutcome(message_id=message.message_id, ack=True)

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

    # Process outside previous transaction.
    try:
        records, final_status = _parse_with_llm(
            redis_client=redis_client,
            stream_key=stream_key,
            source_id=message.source_id,
            provider_hint=str(payload.get("provider") or ""),
            parse_payload=parse_payload,
            request_id=message.request_id,
        )
    except _RateLimitRejected as exc:
        with session_factory() as db:
            _retry_or_dead_letter(
                db,
                redis_client=redis_client,
                stream_key=stream_key,
                request_id=message.request_id,
                next_attempt=max(message.attempt, 0) + 1,
                error_code="llm_rate_limited",
                error_message=f"llm limiter rejected: {exc.reason}",
                reason="rate_limit",
            )
        return _TaskOutcome(message_id=message.message_id, ack=True)
    except LlmParseError as exc:
        error_code = exc.code
        error_message = str(exc)
        if _is_rate_limited_llm_error(exc):
            increment_metric_counter(redis_client, metric_name="llm_calls_rate_limited")
        with session_factory() as db:
            _retry_or_dead_letter(
                db,
                redis_client=redis_client,
                stream_key=stream_key,
                request_id=message.request_id,
                next_attempt=max(message.attempt, 0) + 1,
                error_code=error_code,
                error_message=error_message,
                reason=error_code,
                retryable=bool(exc.retryable),
            )
        return _TaskOutcome(message_id=message.message_id, ack=True)
    except Exception as exc:  # pragma: no cover - defensive worker guard
        with session_factory() as db:
            _retry_or_dead_letter(
                db,
                redis_client=redis_client,
                stream_key=stream_key,
                request_id=message.request_id,
                next_attempt=max(message.attempt, 0) + 1,
                error_code="parse_llm_worker_exception",
                error_message=str(exc),
                reason="exception",
            )
        return _TaskOutcome(message_id=message.message_id, ack=True)

    with session_factory() as db:
        _mark_success(
            db,
            request_id=message.request_id,
            records=records,
            result_status=final_status,
            cursor_patch=cursor_patch,
        )
    return _TaskOutcome(message_id=message.message_id, ack=True)


def _parse_with_llm(
    *,
    redis_client: redis.Redis,
    stream_key: str,
    source_id: int,
    provider_hint: str,
    parse_payload: dict,
    request_id: str,
) -> tuple[list[dict], ConnectorResultStatus]:
    parse_kind = str(parse_payload.get("kind") or "").strip().lower()
    if parse_kind not in {"gmail", "calendar", "calendar_delta_v1"}:
        raise LlmParseError(
            code="llm_parse_kind_invalid",
            message=f"unsupported llm parse kind: {parse_kind or '-'}",
            retryable=False,
            provider=provider_hint or "-",
            parser_version="v2",
        )

    from app.db.session import get_session_factory

    session_factory = get_session_factory()
    records: list[dict] = []
    provider = provider_hint or parse_kind

    if parse_kind == "calendar":
        content_b64 = parse_payload.get("content_b64")
        if not isinstance(content_b64, str) or not content_b64:
            raise LlmParseError(
                code="llm_calendar_payload_invalid",
                message="calendar parse payload missing content_b64",
                retryable=False,
                provider=provider,
                parser_version="v2",
            )
        try:
            content = base64.b64decode(content_b64.encode("utf-8"), validate=True)
        except Exception as exc:
            raise LlmParseError(
                code="llm_calendar_payload_invalid",
                message=f"invalid calendar content_b64: {exc}",
                retryable=False,
                provider=provider,
                parser_version="v2",
            ) from exc

        with session_factory() as db:
            context = ParserContext(
                source_id=source_id,
                provider=provider,
                source_kind="calendar",
                request_id=request_id,
            )
            parser_output = _invoke_parser_with_limit(
                redis_client=redis_client,
                stream_key=stream_key,
                parse_call=lambda: parse_calendar_content(db=db, content=content, context=context),
            )
            records.extend(attach_parser_metadata(records=parser_output.records, parser_output=parser_output))
        return records, ConnectorResultStatus.CHANGED

    if parse_kind == "calendar_delta_v1":
        return _parse_calendar_delta_with_llm(
            redis_client=redis_client,
            stream_key=stream_key,
            parse_payload=parse_payload,
            provider=provider,
            request_id=request_id,
            source_id=source_id,
            session_factory=session_factory,
        )

    messages = parse_payload.get("messages")
    if not isinstance(messages, list):
        raise LlmParseError(
            code="llm_gmail_payload_invalid",
            message="gmail parse payload missing messages list",
            retryable=False,
            provider=provider,
            parser_version="v2",
        )

    with session_factory() as db:
        context = ParserContext(
            source_id=source_id,
            provider=provider,
            source_kind="email",
            request_id=request_id,
        )
        for item in messages:
            if not isinstance(item, dict):
                continue
            parser_output = _invoke_parser_with_limit(
                redis_client=redis_client,
                stream_key=stream_key,
                parse_call=lambda item=item: parse_gmail_payload(db=db, payload=item, context=context),
            )
            records.extend(attach_parser_metadata(records=parser_output.records, parser_output=parser_output))
    status = ConnectorResultStatus.CHANGED if records else ConnectorResultStatus.NO_CHANGE
    return records, status


def _parse_calendar_delta_with_llm(
    *,
    redis_client: redis.Redis,
    stream_key: str,
    parse_payload: dict,
    provider: str,
    request_id: str,
    source_id: int,
    session_factory: sessionmaker[Session],
) -> tuple[list[dict], ConnectorResultStatus]:
    changed_components = parse_payload.get("changed_components")
    removed_component_keys = parse_payload.get("removed_component_keys")
    if not isinstance(changed_components, list):
        raise LlmParseError(
            code="llm_calendar_delta_payload_invalid",
            message="calendar delta payload missing changed_components list",
            retryable=False,
            provider=provider,
            parser_version="v2",
        )
    if not isinstance(removed_component_keys, list):
        raise LlmParseError(
            code="llm_calendar_delta_payload_invalid",
            message="calendar delta payload missing removed_component_keys list",
            retryable=False,
            provider=provider,
            parser_version="v2",
        )

    records: list[dict] = []
    for raw_key in removed_component_keys:
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

    if not changed_components:
        status = ConnectorResultStatus.CHANGED if records else ConnectorResultStatus.NO_CHANGE
        return records, status

    with session_factory() as db:
        context = ParserContext(
            source_id=source_id,
            provider=provider,
            source_kind="calendar",
            request_id=request_id,
        )
        for item in changed_components:
            if not isinstance(item, dict):
                continue
            component_key_raw = item.get("component_key")
            component_ical_b64 = item.get("component_ical_b64")
            if not isinstance(component_key_raw, str) or not component_key_raw.strip():
                continue
            if not isinstance(component_ical_b64, str) or not component_ical_b64:
                continue
            component_key = component_key_raw.strip()
            external_event_id_raw = item.get("external_event_id")
            if isinstance(external_event_id_raw, str) and external_event_id_raw.strip():
                external_event_id = external_event_id_raw.strip()
            else:
                external_event_id = external_event_id_from_component_key(component_key)

            try:
                component_bytes = base64.b64decode(component_ical_b64.encode("utf-8"), validate=True)
            except Exception as exc:
                raise LlmParseError(
                    code="llm_calendar_delta_payload_invalid",
                    message=f"invalid calendar delta component_ical_b64: {exc}",
                    retryable=False,
                    provider=provider,
                    parser_version="v2",
                ) from exc

            try:
                component_text = component_bytes.decode("utf-8")
            except Exception as exc:
                raise LlmParseError(
                    code="llm_calendar_delta_payload_invalid",
                    message=f"calendar delta component is not utf-8: {exc}",
                    retryable=False,
                    provider=provider,
                    parser_version="v2",
                ) from exc

            calendar_text = _build_minimal_calendar_text(component_text)
            parser_output = _invoke_parser_with_limit(
                redis_client=redis_client,
                stream_key=stream_key,
                parse_call=lambda calendar_text=calendar_text: parse_calendar_content(
                    db=db,
                    content=calendar_text.encode("utf-8"),
                    context=context,
                ),
            )
            parsed_records = attach_parser_metadata(records=parser_output.records, parser_output=parser_output)
            for record in parsed_records:
                if not isinstance(record, dict) or record.get("record_type") != "calendar.event.extracted":
                    continue
                payload = record.get("payload")
                if not isinstance(payload, dict):
                    continue
                payload["uid"] = external_event_id
                source_canonical = payload.get("source_canonical") if isinstance(payload.get("source_canonical"), dict) else {}
                source_canonical["external_event_id"] = external_event_id
                source_canonical["component_key"] = component_key
                payload["source_canonical"] = source_canonical
                payload["component_key"] = component_key
            records.extend(parsed_records)

    status = ConnectorResultStatus.CHANGED if records else ConnectorResultStatus.NO_CHANGE
    return records, status


def _build_minimal_calendar_text(component_ical_text: str) -> str:
    body = component_ical_text.strip()
    if "BEGIN:VEVENT" not in body or "END:VEVENT" not in body:
        raise LlmParseError(
            code="llm_calendar_delta_payload_invalid",
            message="calendar delta component missing VEVENT wrapper",
            retryable=False,
            provider="calendar",
            parser_version="v2",
        )
    return "\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//CalendarDIFF//ICS Delta//EN",
            body,
            "END:VCALENDAR",
            "",
        ]
    )


def _invoke_parser_with_limit(*, redis_client: redis.Redis, stream_key: str, parse_call: Callable[[], object]):
    decision = acquire_global_permit(redis_client)
    if not decision.allowed:
        increment_metric_counter(redis_client, metric_name="limiter_rejects")
        increment_metric_counter(redis_client, metric_name="llm_calls_rate_limited")
        raise _RateLimitRejected(reason=decision.reason)

    increment_metric_counter(redis_client, metric_name="llm_calls_total")
    started = time.perf_counter()
    try:
        result = parse_call()
        latency_ms = max(int((time.perf_counter() - started) * 1000), 0)
        record_latency_ms(redis_client, stream_key=stream_key, latency_ms=latency_ms)
        return result
    except LlmParseError as exc:
        latency_ms = max(int((time.perf_counter() - started) * 1000), 0)
        record_latency_ms(redis_client, stream_key=stream_key, latency_ms=latency_ms)
        if _is_rate_limited_llm_error(exc):
            increment_metric_counter(redis_client, metric_name="llm_calls_rate_limited")
        raise
    except Exception:
        latency_ms = max(int((time.perf_counter() - started) * 1000), 0)
        record_latency_ms(redis_client, stream_key=stream_key, latency_ms=latency_ms)
        raise


def _is_rate_limited_llm_error(exc: LlmParseError) -> bool:
    code = exc.code.lower()
    message = str(exc).lower()
    return "rate_limit" in code or "rate_limited" in code or "429" in message


def _job_payload(job: IngestJob) -> dict:
    if isinstance(job.payload_json, dict):
        return dict(job.payload_json)
    return {}


def _retry_or_dead_letter(
    db: Session,
    *,
    redis_client: redis.Redis,
    stream_key: str,
    request_id: str,
    next_attempt: int,
    error_code: str,
    error_message: str,
    reason: str,
    retryable: bool = True,
) -> None:
    now = datetime.now(timezone.utc)
    settings = get_settings()

    job = db.scalar(select(IngestJob).where(IngestJob.request_id == request_id).with_for_update())
    sync_request = db.scalar(select(SyncRequest).where(SyncRequest.request_id == request_id))
    source = db.get(InputSource, job.source_id) if job is not None else None
    if job is None or sync_request is None or source is None:
        if job is not None:
            _dead_letter(
                db,
                job=job,
                sync_request=sync_request,
                source=source,
                error_code="llm_retry_context_missing",
                error_message="missing context during retry scheduling",
                attempt=next_attempt,
            )
        return

    max_attempts = max(1, int(settings.llm_max_retry_attempts))
    if retryable and next_attempt < max_attempts:
        delay_seconds = _compute_retry_delay_seconds(next_attempt)
        due_at = now + timedelta(seconds=delay_seconds)
        try:
            schedule_retry_task(
                redis_client,
                stream_key=stream_key,
                request_id=request_id,
                source_id=job.source_id,
                attempt=next_attempt,
                reason=reason,
                due_at=due_at,
            )
        except Exception as exc:
            _dead_letter(
                db,
                job=job,
                sync_request=sync_request,
                source=source,
                error_code="llm_retry_schedule_failed",
                error_message=str(exc),
                attempt=next_attempt,
            )
            return

        increment_metric_counter(redis_client, metric_name="llm_retry_scheduled")
        payload = _job_payload(job)
        payload["workflow_stage"] = "LLM_RETRY_WAITING"
        payload["last_error_code"] = error_code
        payload["last_error_message"] = _truncate(error_message)
        payload["last_retry_scheduled_at"] = now.isoformat()
        payload["llm_next_due_at"] = due_at.isoformat()

        job.status = IngestJobStatus.CLAIMED
        job.attempt = next_attempt
        job.next_retry_at = due_at
        job.payload_json = payload
        sync_request.status = SyncRequestStatus.RUNNING
        sync_request.error_code = error_code
        sync_request.error_message = _truncate(error_message)
        source.last_error_code = error_code
        source.last_error_message = _truncate(error_message)
        db.commit()
        return

    _dead_letter(
        db,
        job=job,
        sync_request=sync_request,
        source=source,
        error_code=error_code,
        error_message=error_message,
        attempt=next_attempt,
    )


def _dead_letter(
    db: Session,
    *,
    job: IngestJob,
    sync_request: SyncRequest | None,
    source: InputSource | None,
    error_code: str,
    error_message: str,
    attempt: int,
) -> None:
    now = datetime.now(timezone.utc)
    payload = _job_payload(job)
    payload["workflow_stage"] = "LLM_DEAD_LETTER"
    payload["last_error_code"] = error_code
    payload["last_error_message"] = _truncate(error_message)
    payload["dead_lettered_at"] = now.isoformat()

    job.status = IngestJobStatus.DEAD_LETTER
    job.dead_lettered_at = now
    job.next_retry_at = None
    job.attempt = max(attempt, job.attempt + 1)
    job.payload_json = payload
    if sync_request is not None:
        sync_request.status = SyncRequestStatus.FAILED
        sync_request.error_code = error_code
        sync_request.error_message = _truncate(error_message)
    if source is not None:
        source.last_error_code = error_code
        source.last_error_message = _truncate(error_message)
    db.commit()


def _compute_retry_delay_seconds(next_attempt: int) -> int:
    settings = get_settings()
    exponent = max(next_attempt - 1, 0)
    base = max(1, int(settings.llm_retry_base_seconds))
    max_seconds = max(base, int(settings.llm_retry_max_seconds))
    jitter_max = max(0, int(settings.llm_retry_jitter_seconds))
    delay = min(base * (2**exponent), max_seconds)
    if jitter_max > 0:
        delay += random.randint(0, jitter_max)
    return max(1, int(delay))


def _mark_success(
    db: Session,
    *,
    request_id: str,
    records: list[dict],
    result_status: ConnectorResultStatus,
    cursor_patch: dict,
) -> None:
    now = datetime.now(timezone.utc)
    job = db.scalar(select(IngestJob).where(IngestJob.request_id == request_id).with_for_update())
    sync_request = db.scalar(select(SyncRequest).where(SyncRequest.request_id == request_id))
    if job is None or sync_request is None:
        return
    source = db.get(InputSource, job.source_id)
    if source is None:
        _dead_letter(
            db,
            job=job,
            sync_request=sync_request,
            source=source,
            error_code="llm_source_missing_on_success",
            error_message="source row disappeared before success commit",
            attempt=job.attempt + 1,
        )
        return

    existing_result = db.scalar(select(IngestResult).where(IngestResult.request_id == request_id))
    if existing_result is None:
        db.add(
            IngestResult(
                request_id=request_id,
                source_id=source.id,
                provider=source.provider,
                status=result_status,
                cursor_patch=cursor_patch,
                records=records,
                fetched_at=now,
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
                "source_id": source.id,
                "provider": source.provider,
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

    if source.cursor is not None and cursor_patch:
        merged = dict(source.cursor.cursor_json or {})
        merged.update(cursor_patch)
        source.cursor.cursor_json = merged
        source.cursor.version += 1
    source.last_polled_at = now
    source.next_poll_at = now + timedelta(seconds=max(source.poll_interval_seconds, 30))
    source.last_error_code = None
    source.last_error_message = None

    payload = _job_payload(job)
    payload["workflow_stage"] = "LLM_SUCCEEDED"
    payload["llm_finished_at"] = now.isoformat()
    payload.pop("llm_parse_payload", None)
    job.payload_json = payload
    job.status = IngestJobStatus.SUCCEEDED
    job.next_retry_at = None
    sync_request.status = SyncRequestStatus.SUCCEEDED
    sync_request.error_code = None
    sync_request.error_message = None
    db.commit()


def _truncate(message: str, max_len: int = 512) -> str:
    text = (message or "").strip()
    if len(text) <= max_len:
        return text
    return text[:max_len]


def enqueue_llm_task(
    *,
    redis_client: redis.Redis,
    request_id: str,
    source_id: int,
    attempt: int,
    reason: str,
) -> str:
    return enqueue_stream_task(
        redis_client,
        stream_key=queue_stream_key(),
        request_id=request_id,
        source_id=source_id,
        attempt=attempt,
        reason=reason,
    )
