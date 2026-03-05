from __future__ import annotations

import redis

from app.modules.llm_runtime.queue import enqueue_stream_task, queue_stream_key


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


__all__ = ["enqueue_llm_task"]
