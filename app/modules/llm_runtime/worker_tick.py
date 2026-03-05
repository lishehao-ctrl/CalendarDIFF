from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import timedelta

import redis
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.models import IngestJob, IngestJobStatus, InputSource, SyncRequest, SyncRequestStatus
from app.modules.ingestion.job_lifecycle import JobContext, apply_dead_letter_transition, copy_job_payload, utcnow
from app.modules.ingestion.llm_parsers import LlmParseError
from app.modules.llm_runtime.parse_pipeline import (
    RateLimitRejected,
    is_rate_limited_llm_error,
    parse_with_llm,
)
from app.modules.llm_runtime.queue import LlmQueueMessage, increment_metric_counter
from app.modules.llm_runtime.queue_consumer import ack_llm_messages, consume_llm_queue_batch
from app.modules.llm_runtime.transitions import apply_llm_failure_transition, mark_llm_success

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _TaskOutcome:
    message_id: str
    ack: bool


def run_llm_worker_tick(
    *,
    redis_client: redis.Redis,
    session_factory: sessionmaker[Session],
    worker_id: str,
) -> int:
    settings = get_settings()
    concurrency = max(1, int(settings.llm_worker_concurrency))
    stream_key, group_name, messages = consume_llm_queue_batch(
        redis_client=redis_client,
        worker_id=worker_id,
        concurrency=concurrency,
        poll_ms=max(1, int(settings.llm_queue_consumer_poll_ms)),
    )
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
    ack_llm_messages(
        redis_client=redis_client,
        stream_key=stream_key,
        group_name=group_name,
        message_ids=ack_ids,
    )
    return len(messages)


def _process_stream_message(
    *,
    message: LlmQueueMessage,
    redis_client: redis.Redis,
    session_factory: sessionmaker[Session],
    worker_id: str,
    stream_key: str,
) -> _TaskOutcome:
    with session_factory() as db:
        now = utcnow()
        job = db.scalar(
            select(IngestJob).where(IngestJob.request_id == message.request_id).with_for_update(skip_locked=True)
        )
        if job is None:
            return _TaskOutcome(message_id=message.message_id, ack=True)

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
            return _TaskOutcome(message_id=message.message_id, ack=True)

        if job.status == IngestJobStatus.SUCCEEDED:
            return _TaskOutcome(message_id=message.message_id, ack=True)
        if job.status in {IngestJobStatus.FAILED, IngestJobStatus.DEAD_LETTER}:
            return _TaskOutcome(message_id=message.message_id, ack=True)
        if job.status != IngestJobStatus.CLAIMED:
            return _TaskOutcome(message_id=message.message_id, ack=True)

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

    try:
        records, final_status = parse_with_llm(
            redis_client=redis_client,
            stream_key=stream_key,
            source_id=message.source_id,
            provider_hint=str(payload.get("provider") or ""),
            parse_payload=parse_payload,
            request_id=message.request_id,
        )
    except RateLimitRejected as exc:
        with session_factory() as db:
            apply_llm_failure_transition(
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
        if is_rate_limited_llm_error(exc):
            increment_metric_counter(redis_client, metric_name="llm_calls_rate_limited")
        with session_factory() as db:
            apply_llm_failure_transition(
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
            apply_llm_failure_transition(
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
        mark_llm_success(
            db,
            request_id=message.request_id,
            records=records,
            result_status=final_status,
            cursor_patch=cursor_patch,
        )
    return _TaskOutcome(message_id=message.message_id, ack=True)


__all__ = ["run_llm_worker_tick"]
