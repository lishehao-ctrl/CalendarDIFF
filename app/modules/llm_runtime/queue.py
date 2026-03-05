from __future__ import annotations

import redis

from app.core.config import get_settings
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
    retry_meta_hash_key,
    retry_zset_key,
    schedule_retry_task,
)

LlmQueueMessage = StreamQueueMessage


def get_redis_client() -> redis.Redis:
    settings = get_settings()
    redis_url = (settings.redis_url or "").strip()
    if not redis_url:
        raise RuntimeError("REDIS_URL is required for llm runtime")
    return redis.Redis.from_url(redis_url, decode_responses=True)


def queue_stream_key() -> str:
    settings = get_settings()
    return settings.llm_queue_stream_key.strip() or "llm:parse:stream:v1"


def queue_group() -> str:
    settings = get_settings()
    return settings.llm_queue_group.strip() or "llm-parse-workers"


__all__ = [
    "LlmQueueMessage",
    "ack_stream_tasks",
    "claim_idle_stream_tasks",
    "consume_stream_tasks",
    "enqueue_stream_task",
    "ensure_stream_group",
    "get_redis_client",
    "increment_metric_counter",
    "latency_p95_5m",
    "move_due_retry_tasks",
    "queue_depth_retry",
    "queue_depth_stream",
    "queue_group",
    "queue_stream_key",
    "read_metric_counter_1m",
    "record_latency_ms",
    "retry_meta_hash_key",
    "retry_zset_key",
    "schedule_retry_task",
]
