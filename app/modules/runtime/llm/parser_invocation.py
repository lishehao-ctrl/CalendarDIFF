from __future__ import annotations

import time
from collections.abc import Callable

import redis

from app.modules.runtime.connectors.llm_parsers import LlmParseError
from app.modules.runtime.kernel.parse_task_queue import increment_parse_metric_counter, record_parse_latency_ms


class RateLimitRejected(RuntimeError):
    def __init__(self, *, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def invoke_parser_with_limit_impl(
    *,
    redis_client: redis.Redis,
    stream_key: str,
    parse_call: Callable[[], object],
):
    del stream_key
    increment_parse_metric_counter(redis_client, metric_name="llm_calls_total")
    started = time.perf_counter()
    try:
        result = parse_call()
        latency_ms = max(int((time.perf_counter() - started) * 1000), 0)
        record_parse_latency_ms(redis_client, latency_ms=latency_ms)
        return result
    except LlmParseError as exc:
        latency_ms = max(int((time.perf_counter() - started) * 1000), 0)
        record_parse_latency_ms(redis_client, latency_ms=latency_ms)
        if is_rate_limited_llm_error_impl(exc):
            increment_parse_metric_counter(redis_client, metric_name="llm_calls_rate_limited")
        raise
    except Exception:
        latency_ms = max(int((time.perf_counter() - started) * 1000), 0)
        record_parse_latency_ms(redis_client, latency_ms=latency_ms)
        raise


def is_rate_limited_llm_error_impl(exc: LlmParseError) -> bool:
    code = exc.code.lower()
    message = str(exc).lower()
    return "rate_limit" in code or "rate_limited" in code or "429" in message


__all__ = [
    "RateLimitRejected",
    "invoke_parser_with_limit_impl",
    "is_rate_limited_llm_error_impl",
]
