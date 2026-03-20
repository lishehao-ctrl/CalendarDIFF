from __future__ import annotations

import logging
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass

import redis
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.modules.runtime.llm.message_processor import process_parse_task_message
from app.modules.runtime.kernel.parse_task_queue import ack_parse_tasks, consume_parse_tasks

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
    poll_ms = max(1, int(settings.llm_queue_consumer_poll_ms))
    stream_key, _group_name, messages = consume_parse_tasks(
        redis_client=redis_client,
        worker_id=worker_id,
        batch_size=concurrency,
        poll_ms=poll_ms,
    )
    if not messages:
        return 0

    total_consumed = 0
    max_workers = max(1, concurrency)
    if max_workers == 1:
        current_messages = messages
        while current_messages:
            total_consumed += len(current_messages)
            ack_ids: list[str] = []
            for message in current_messages:
                ack = process_parse_task_message(
                    message=message,
                    redis_client=redis_client,
                    session_factory=session_factory,
                    worker_id=worker_id,
                    stream_key=stream_key,
                )
                if ack:
                    ack_ids.append(message.message_id)
            ack_parse_tasks(
                redis_client=redis_client,
                message_ids=ack_ids,
            )
            _stream_key, _group_name, current_messages = consume_parse_tasks(
                redis_client=redis_client,
                worker_id=worker_id,
                batch_size=1,
                poll_ms=1,
            )
        return total_consumed

    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="llm-runtime") as pool:
        future_map = {}

        def submit_batch(batch_messages) -> None:
            nonlocal total_consumed
            total_consumed += len(batch_messages)
            for message in batch_messages:
                future_map[
                    pool.submit(
                        process_parse_task_message,
                        message=message,
                        redis_client=redis_client,
                        session_factory=session_factory,
                        worker_id=worker_id,
                        stream_key=stream_key,
                    )
                ] = message

        submit_batch(messages)

        while future_map:
            done, _pending = wait(set(future_map.keys()), return_when=FIRST_COMPLETED)
            ack_ids: list[str] = []
            for future in done:
                message = future_map.pop(future)
                try:
                    if bool(future.result()):
                        ack_ids.append(message.message_id)
                except Exception as exc:  # pragma: no cover - defensive worker guard
                    logger.error(
                        "llm worker task crashed request_id=%s source_id=%s error=%s",
                        message.request_id,
                        message.source_id,
                        str(exc),
                    )
            ack_parse_tasks(
                redis_client=redis_client,
                message_ids=ack_ids,
            )

            available_slots = max_workers - len(future_map)
            if available_slots <= 0:
                continue
            _stream_key, _group_name, more_messages = consume_parse_tasks(
                redis_client=redis_client,
                worker_id=worker_id,
                batch_size=available_slots,
                poll_ms=1,
            )
            if more_messages:
                submit_batch(more_messages)

    return total_consumed


__all__ = ["run_llm_worker_tick"]
