from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import redis
from redis.exceptions import ResponseError


@dataclass(frozen=True)
class StreamQueueMessage:
    message_id: str
    request_id: str
    source_id: int
    attempt: int
    reason: str


def retry_zset_key(stream_key: str) -> str:
    return f"{stream_key}:retry"


def retry_meta_hash_key(stream_key: str) -> str:
    return f"{stream_key}:retry_meta"


def latency_list_key(stream_key: str) -> str:
    return f"{stream_key}:latency_ms"


def metric_counter_key(metric_name: str, *, minute_epoch: int) -> str:
    return f"llm:metric:{metric_name}:{minute_epoch}"


def ensure_stream_group(client: redis.Redis, *, stream_key: str, group_name: str) -> None:
    try:
        client.xgroup_create(name=stream_key, groupname=group_name, id="0-0", mkstream=True)
    except ResponseError as exc:
        message = str(exc).lower()
        if "busygroup" in message:
            return
        raise


def enqueue_stream_task(
    client: redis.Redis,
    *,
    stream_key: str,
    request_id: str,
    source_id: int,
    attempt: int,
    reason: str,
) -> str:
    return str(
        client.xadd(
            stream_key,
            fields={
                "request_id": request_id,
                "source_id": str(source_id),
                "attempt": str(max(attempt, 0)),
                "reason": reason,
            },
        )
    )


def schedule_retry_task(
    client: redis.Redis,
    *,
    stream_key: str,
    request_id: str,
    source_id: int,
    attempt: int,
    reason: str,
    due_at: datetime,
) -> None:
    retry_key = retry_zset_key(stream_key)
    retry_meta_key = retry_meta_hash_key(stream_key)
    due_at_utc = due_at.astimezone(timezone.utc)
    due_ts = due_at_utc.timestamp()
    payload = {
        "source_id": int(source_id),
        "attempt": int(max(attempt, 0)),
        "reason": reason,
    }
    pipe = client.pipeline(transaction=True)
    pipe.hset(retry_meta_key, request_id, json.dumps(payload, ensure_ascii=True, separators=(",", ":")))
    pipe.zadd(retry_key, {request_id: due_ts})
    pipe.execute()


def move_due_retry_tasks(
    client: redis.Redis,
    *,
    stream_key: str,
    now: datetime,
    limit: int,
) -> int:
    retry_key = retry_zset_key(stream_key)
    retry_meta_key = retry_meta_hash_key(stream_key)
    capped_limit = max(1, int(limit))
    now_ts = now.astimezone(timezone.utc).timestamp()
    request_ids = client.zrangebyscore(retry_key, min="-inf", max=now_ts, start=0, num=capped_limit)
    if not request_ids:
        return 0

    moved = 0
    pipe = client.pipeline(transaction=True)
    for request_id in request_ids:
        raw_meta = client.hget(retry_meta_key, request_id)
        if not raw_meta:
            pipe.zrem(retry_key, request_id)
            continue
        try:
            parsed = json.loads(raw_meta)
        except Exception:
            pipe.hdel(retry_meta_key, request_id)
            pipe.zrem(retry_key, request_id)
            continue
        source_id = int(parsed.get("source_id"))
        attempt = int(parsed.get("attempt", 0))
        reason = str(parsed.get("reason") or "retry")
        pipe.xadd(
            stream_key,
            fields={
                "request_id": request_id,
                "source_id": str(source_id),
                "attempt": str(max(attempt, 0)),
                "reason": reason,
            },
        )
        pipe.hdel(retry_meta_key, request_id)
        pipe.zrem(retry_key, request_id)
        moved += 1
    pipe.execute()
    return moved


def consume_stream_tasks(
    client: redis.Redis,
    *,
    stream_key: str,
    group_name: str,
    consumer_name: str,
    count: int,
    block_ms: int,
) -> list[StreamQueueMessage]:
    entries = client.xreadgroup(
        groupname=group_name,
        consumername=consumer_name,
        streams={stream_key: ">"},
        count=max(1, int(count)),
        block=max(1, int(block_ms)),
    )
    if not entries:
        return []
    messages: list[StreamQueueMessage] = []
    for _, rows in entries:
        for message_id, payload in rows:
            request_id = str(payload.get("request_id") or "")
            source_id_raw = payload.get("source_id")
            attempt_raw = payload.get("attempt")
            reason = str(payload.get("reason") or "initial")
            if not request_id:
                continue
            try:
                source_id = int(source_id_raw)
            except Exception:
                continue
            try:
                attempt = int(attempt_raw) if attempt_raw is not None else 0
            except Exception:
                attempt = 0
            messages.append(
                StreamQueueMessage(
                    message_id=str(message_id),
                    request_id=request_id,
                    source_id=source_id,
                    attempt=max(attempt, 0),
                    reason=reason,
                )
            )
    return messages


def claim_idle_stream_tasks(
    client: redis.Redis,
    *,
    stream_key: str,
    group_name: str,
    consumer_name: str,
    min_idle_ms: int,
    count: int,
) -> list[StreamQueueMessage]:
    try:
        next_id, rows = client.xautoclaim(
            stream_key,
            group_name,
            consumer_name,
            min_idle_time=max(1000, int(min_idle_ms)),
            start_id="0-0",
            count=max(1, int(count)),
        )
    except ResponseError as exc:
        message = str(exc).lower()
        if "unknown key" in message or "nogroup" in message:
            return []
        raise

    del next_id
    messages: list[StreamQueueMessage] = []
    for message_id, payload in rows:
        request_id = str(payload.get("request_id") or "")
        source_id_raw = payload.get("source_id")
        attempt_raw = payload.get("attempt")
        reason = str(payload.get("reason") or "reclaimed")
        if not request_id:
            continue
        try:
            source_id = int(source_id_raw)
        except Exception:
            continue
        try:
            attempt = int(attempt_raw) if attempt_raw is not None else 0
        except Exception:
            attempt = 0
        messages.append(
            StreamQueueMessage(
                message_id=str(message_id),
                request_id=request_id,
                source_id=source_id,
                attempt=max(attempt, 0),
                reason=reason,
            )
        )
    return messages


def ack_stream_tasks(
    client: redis.Redis,
    *,
    stream_key: str,
    group_name: str,
    message_ids: list[str],
) -> int:
    if not message_ids:
        return 0
    return int(client.xack(stream_key, group_name, *message_ids))


def queue_depth_stream(client: redis.Redis, *, stream_key: str) -> int:
    return int(client.xlen(stream_key))


def queue_depth_retry(client: redis.Redis, *, stream_key: str) -> int:
    return int(client.zcard(retry_zset_key(stream_key)))


def increment_metric_counter(client: redis.Redis, *, metric_name: str, amount: int = 1) -> None:
    now = int(time.time())
    minute_epoch = now // 60
    key = metric_counter_key(metric_name, minute_epoch=minute_epoch)
    pipe = client.pipeline(transaction=True)
    pipe.incrby(key, max(1, int(amount)))
    pipe.expire(key, 600)
    pipe.execute()


def read_metric_counter_1m(client: redis.Redis, *, metric_name: str) -> int:
    now = int(time.time())
    current = now // 60
    previous = current - 1
    keys = [
        metric_counter_key(metric_name, minute_epoch=current),
        metric_counter_key(metric_name, minute_epoch=previous),
    ]
    values = client.mget(keys)
    total = 0
    for value in values:
        if value is None:
            continue
        try:
            total += int(value)
        except Exception:
            continue
    return total


def record_latency_ms(client: redis.Redis, *, stream_key: str, latency_ms: int, max_items: int = 6000) -> None:
    now_ms = int(time.time() * 1000)
    entry = f"{now_ms}:{max(latency_ms, 0)}"
    key = latency_list_key(stream_key)
    pipe = client.pipeline(transaction=True)
    pipe.lpush(key, entry)
    pipe.ltrim(key, 0, max(max_items, 100) - 1)
    pipe.expire(key, 3600)
    pipe.execute()


def latency_p95_5m(client: redis.Redis, *, stream_key: str) -> float:
    key = latency_list_key(stream_key)
    rows = client.lrange(key, 0, 6000)
    if not rows:
        return 0.0
    threshold_ms = int(time.time() * 1000) - 5 * 60 * 1000
    values: list[int] = []
    for row in rows:
        try:
            ts_raw, latency_raw = row.split(":", 1)
            ts = int(ts_raw)
            latency = int(latency_raw)
        except Exception:
            continue
        if ts >= threshold_ms:
            values.append(max(latency, 0))
    if not values:
        return 0.0
    values.sort()
    index = int(round(0.95 * (len(values) - 1)))
    return float(values[index])


__all__ = [
    "StreamQueueMessage",
    "ack_stream_tasks",
    "claim_idle_stream_tasks",
    "consume_stream_tasks",
    "enqueue_stream_task",
    "ensure_stream_group",
    "increment_metric_counter",
    "latency_p95_5m",
    "metric_counter_key",
    "move_due_retry_tasks",
    "queue_depth_retry",
    "queue_depth_stream",
    "read_metric_counter_1m",
    "record_latency_ms",
    "retry_meta_hash_key",
    "retry_zset_key",
    "schedule_retry_task",
]
