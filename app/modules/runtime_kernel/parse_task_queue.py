from __future__ import annotations

from datetime import datetime, timezone

import redis

from app.core.config import get_settings
from app.modules.runtime_kernel.parse_task_channel import parse_queue_group, parse_queue_stream_key
from app.modules.runtime_kernel.stream_queue import (
    StreamQueueMessage,
    ack_stream_tasks,
    claim_idle_stream_tasks,
    consume_stream_tasks,
    enqueue_stream_task,
    ensure_stream_group,
    increment_metric_counter,
    latency_p95_5m,
    move_due_retry_tasks,
    queue_depth_retry,
    queue_depth_stream,
    read_metric_counter_1m,
    record_latency_ms,
    schedule_retry_task,
)

ParseTaskMessage = StreamQueueMessage


def get_parse_queue_redis_client() -> redis.Redis:
    settings = get_settings()
    redis_url = (settings.redis_url or "").strip()
    if not redis_url:
        raise RuntimeError("REDIS_URL is required for parse task queue")
    return redis.Redis.from_url(redis_url, decode_responses=True)


def ensure_parse_queue_group(redis_client: redis.Redis) -> None:
    ensure_stream_group(
        redis_client,
        stream_key=parse_queue_stream_key(),
        group_name=parse_queue_group(),
    )


def enqueue_parse_task(
    redis_client: redis.Redis,
    *,
    request_id: str,
    source_id: int,
    attempt: int,
    reason: str,
) -> str:
    return enqueue_stream_task(
        redis_client,
        stream_key=parse_queue_stream_key(),
        request_id=request_id,
        source_id=source_id,
        attempt=attempt,
        reason=reason,
    )


def consume_parse_tasks(
    redis_client: redis.Redis,
    *,
    worker_id: str,
    batch_size: int,
    poll_ms: int,
) -> tuple[str, str, list[ParseTaskMessage]]:
    stream_key = parse_queue_stream_key()
    group_name = parse_queue_group()
    ensure_parse_queue_group(redis_client)
    move_due_parse_retries(
        redis_client,
        now=datetime.now(timezone.utc),
        limit=max(batch_size * 2, 8),
    )
    reclaimed = claim_idle_stream_tasks(
        redis_client,
        stream_key=stream_key,
        group_name=group_name,
        consumer_name=worker_id,
        min_idle_ms=max(int(poll_ms) * 3, 10_000),
        count=batch_size,
    )
    remaining = max(1, batch_size - len(reclaimed))
    fresh = consume_stream_tasks(
        redis_client,
        stream_key=stream_key,
        group_name=group_name,
        consumer_name=worker_id,
        count=remaining,
        block_ms=max(1, int(poll_ms)),
    )
    return stream_key, group_name, reclaimed + fresh


def ack_parse_tasks(
    redis_client: redis.Redis,
    *,
    message_ids: list[str],
) -> int:
    return ack_stream_tasks(
        redis_client,
        stream_key=parse_queue_stream_key(),
        group_name=parse_queue_group(),
        message_ids=message_ids,
    )


def schedule_parse_retry(
    redis_client: redis.Redis,
    *,
    request_id: str,
    source_id: int,
    attempt: int,
    available_at: datetime,
    reason: str,
) -> None:
    schedule_retry_task(
        redis_client,
        stream_key=parse_queue_stream_key(),
        request_id=request_id,
        source_id=source_id,
        attempt=attempt,
        reason=reason,
        due_at=available_at,
    )


def move_due_parse_retries(
    redis_client: redis.Redis,
    *,
    now: datetime,
    limit: int = 100,
) -> int:
    return move_due_retry_tasks(
        redis_client,
        stream_key=parse_queue_stream_key(),
        now=now,
        limit=limit,
    )


def parse_queue_depth(redis_client: redis.Redis) -> int:
    return queue_depth_stream(redis_client, stream_key=parse_queue_stream_key())


def parse_retry_depth(redis_client: redis.Redis) -> int:
    return queue_depth_retry(redis_client, stream_key=parse_queue_stream_key())


def increment_parse_metric_counter(redis_client: redis.Redis, *, metric_name: str, amount: int = 1) -> None:
    increment_metric_counter(redis_client, metric_name=metric_name, amount=amount)


def read_parse_metric_counter_1m(redis_client: redis.Redis, *, metric_name: str) -> int:
    return read_metric_counter_1m(redis_client, metric_name=metric_name)


def record_parse_latency_ms(redis_client: redis.Redis, *, latency_ms: int, max_items: int = 6000) -> None:
    record_latency_ms(
        redis_client,
        stream_key=parse_queue_stream_key(),
        latency_ms=latency_ms,
        max_items=max_items,
    )


def parse_latency_p95_5m(redis_client: redis.Redis) -> float:
    return latency_p95_5m(redis_client, stream_key=parse_queue_stream_key())


__all__ = [
    "ParseTaskMessage",
    "ack_parse_tasks",
    "consume_parse_tasks",
    "enqueue_parse_task",
    "ensure_parse_queue_group",
    "get_parse_queue_redis_client",
    "increment_parse_metric_counter",
    "move_due_parse_retries",
    "parse_latency_p95_5m",
    "parse_queue_depth",
    "parse_queue_group",
    "parse_queue_stream_key",
    "parse_retry_depth",
    "read_parse_metric_counter_1m",
    "record_parse_latency_ms",
    "schedule_parse_retry",
]
