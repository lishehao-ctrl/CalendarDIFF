from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

import redis
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.modules.llm_runtime.message_processor import process_parse_task_message
from app.modules.runtime_kernel.parse_task_queue import ack_parse_tasks, consume_parse_tasks

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
    stream_key, _group_name, messages = consume_parse_tasks(
        redis_client=redis_client,
        worker_id=worker_id,
        batch_size=concurrency,
        poll_ms=max(1, int(settings.llm_queue_consumer_poll_ms)),
    )
    if not messages:
        return 0

    outcomes: list[_TaskOutcome] = []
    max_workers = max(1, min(concurrency, len(messages)))
    if max_workers == 1:
        for message in messages:
            ack = process_parse_task_message(
                message=message,
                redis_client=redis_client,
                session_factory=session_factory,
                worker_id=worker_id,
                stream_key=stream_key,
            )
            outcomes.append(_TaskOutcome(message_id=message.message_id, ack=ack))
    else:
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="llm-runtime") as pool:
            future_map = {
                pool.submit(
                    process_parse_task_message,
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
                    outcomes.append(_TaskOutcome(message_id=message.message_id, ack=bool(future.result())))
                except Exception as exc:  # pragma: no cover - defensive worker guard
                    logger.error(
                        "llm worker task crashed request_id=%s source_id=%s error=%s",
                        message.request_id,
                        message.source_id,
                        str(exc),
                    )
                    outcomes.append(_TaskOutcome(message_id=message.message_id, ack=False))

    ack_ids = [row.message_id for row in outcomes if row.ack]
    ack_parse_tasks(
        redis_client=redis_client,
        message_ids=ack_ids,
    )
    return len(messages)


__all__ = ["run_llm_worker_tick"]
