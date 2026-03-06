from __future__ import annotations

import redis
from sqlalchemy.orm import Session, sessionmaker

from app.modules.ingestion.llm_parsers import LlmParseError
from app.modules.llm_runtime.message_preflight import prepare_message_for_processing
from app.modules.llm_runtime.parse_pipeline import RateLimitRejected, is_rate_limited_llm_error, parse_with_llm
from app.modules.llm_runtime.transitions import apply_llm_failure_transition, mark_llm_success
from app.modules.runtime_kernel.parse_task_queue import ParseTaskMessage, increment_parse_metric_counter


def process_parse_task_message(
    *,
    message: ParseTaskMessage,
    redis_client: redis.Redis,
    session_factory: sessionmaker[Session],
    worker_id: str,
    stream_key: str,
) -> bool:
    with session_factory() as db:
        preflight = prepare_message_for_processing(
            db,
            message=message,
            worker_id=worker_id,
        )
    if not preflight.should_parse:
        return bool(preflight.ack_on_skip)

    try:
        records, final_status = parse_with_llm(
            redis_client=redis_client,
            stream_key=stream_key,
            source_id=message.source_id,
            provider_hint=preflight.provider_hint,
            parse_payload=preflight.parse_payload,
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
        return True
    except LlmParseError as exc:
        error_code = exc.code
        error_message = str(exc)
        if is_rate_limited_llm_error(exc):
            increment_parse_metric_counter(redis_client, metric_name="llm_calls_rate_limited")
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
        return True
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
        return True

    with session_factory() as db:
        mark_llm_success(
            db,
            request_id=message.request_id,
            records=records,
            result_status=final_status,
            cursor_patch=preflight.cursor_patch,
        )
    return True


__all__ = ["process_parse_task_message"]
