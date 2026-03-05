from __future__ import annotations

from datetime import datetime, timezone

import redis

from app.modules.llm_runtime.queue import (
    LlmQueueMessage,
    ack_stream_tasks,
    claim_idle_stream_tasks,
    consume_stream_tasks,
    ensure_stream_group,
    move_due_retry_tasks,
    queue_group,
    queue_stream_key,
)


def consume_llm_queue_batch(
    *,
    redis_client: redis.Redis,
    worker_id: str,
    concurrency: int,
    poll_ms: int,
) -> tuple[str, str, list[LlmQueueMessage]]:
    stream_key = queue_stream_key()
    group_name = queue_group()
    ensure_stream_group(redis_client, stream_key=stream_key, group_name=group_name)

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
        min_idle_ms=max(int(poll_ms) * 3, 10_000),
        count=concurrency,
    )
    remaining = max(1, concurrency - len(reclaimed))
    fresh = consume_stream_tasks(
        redis_client,
        stream_key=stream_key,
        group_name=group_name,
        consumer_name=worker_id,
        count=remaining,
        block_ms=max(1, int(poll_ms)),
    )
    return stream_key, group_name, reclaimed + fresh


def ack_llm_messages(
    *,
    redis_client: redis.Redis,
    stream_key: str,
    group_name: str,
    message_ids: list[str],
) -> None:
    ack_stream_tasks(redis_client, stream_key=stream_key, group_name=group_name, message_ids=message_ids)


__all__ = [
    "ack_llm_messages",
    "consume_llm_queue_batch",
]
