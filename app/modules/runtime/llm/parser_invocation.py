from __future__ import annotations

import time
from collections.abc import Callable

import redis

from app.modules.runtime.connectors.llm_parsers import LlmParseError


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
    started = time.perf_counter()
    try:
        return parse_call()
    except LlmParseError as exc:
        del started
        raise
    except Exception:
        del started
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
