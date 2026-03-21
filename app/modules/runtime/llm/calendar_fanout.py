from __future__ import annotations

import redis
from sqlalchemy.orm import Session, sessionmaker

from app.modules.runtime.connectors.calendar_fanout_contract import (
    is_calendar_fanout_reason,
    is_calendar_reduce_reason,
    parse_component_key_from_reason,
)
from app.modules.runtime.kernel.parse_task_queue import enqueue_parse_task, schedule_parse_retry
from app.modules.runtime.llm.parse_pipeline import parse_calendar_changed_component_with_llm
from app.modules.runtime.llm.calendar_component_runtime import process_calendar_component_message_impl
from app.modules.runtime.llm.calendar_reduce_runtime import process_calendar_reduce_message_impl
from app.modules.runtime.llm.message_preflight import MessagePreflight


def process_calendar_fanout_message(
    *,
    message,
    preflight: MessagePreflight,
    redis_client: redis.Redis,
    stream_key: str,
    session_factory: sessionmaker[Session],
) -> bool:
    if is_calendar_reduce_reason(message.reason):
        return process_calendar_reduce_message_impl(
            message=message,
            preflight=preflight,
            redis_client=redis_client,
            session_factory=session_factory,
            enqueue_parse_task_fn=enqueue_parse_task,
            schedule_parse_retry_fn=schedule_parse_retry,
        )
    component_key = parse_component_key_from_reason(message.reason)
    if component_key is None:
        return False
    return process_calendar_component_message_impl(
        message=message,
        component_key=component_key,
        preflight=preflight,
        redis_client=redis_client,
        stream_key=stream_key,
        session_factory=session_factory,
        parse_calendar_changed_component_with_llm_fn=parse_calendar_changed_component_with_llm,
        enqueue_parse_task_fn=enqueue_parse_task,
        schedule_parse_retry_fn=schedule_parse_retry,
    )


__all__ = [
    "enqueue_parse_task",
    "is_calendar_fanout_reason",
    "parse_calendar_changed_component_with_llm",
    "process_calendar_fanout_message",
    "schedule_parse_retry",
]
