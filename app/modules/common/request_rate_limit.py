from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass

from fastapi import HTTPException, Request, status

from app.core.config import get_settings
from app.modules.common.api_errors import api_error_detail

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    retry_after_seconds: int
    in_window: int
    max_requests: int
    window_seconds: int


class RejectingSlidingWindowRateLimiter:
    def __init__(self, *, max_requests: int, window_seconds: int) -> None:
        self.max_requests = max(int(max_requests), 0)
        self.window_seconds = max(int(window_seconds), 0)
        self._lock = threading.Lock()
        self._timestamps: dict[str, deque[float]] = defaultdict(deque)

    def try_acquire(self, key: str) -> RateLimitResult:
        if self.max_requests <= 0 or self.window_seconds <= 0:
            return RateLimitResult(
                allowed=True,
                retry_after_seconds=0,
                in_window=0,
                max_requests=self.max_requests,
                window_seconds=self.window_seconds,
            )

        now = time.monotonic()
        cutoff = now - float(self.window_seconds)
        with self._lock:
            timestamps = self._timestamps[key]
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()
            if len(timestamps) < self.max_requests:
                timestamps.append(now)
                return RateLimitResult(
                    allowed=True,
                    retry_after_seconds=0,
                    in_window=len(timestamps),
                    max_requests=self.max_requests,
                    window_seconds=self.window_seconds,
                )
            retry_after_seconds = max(int(timestamps[0] + float(self.window_seconds) - now) + 1, 1)
            return RateLimitResult(
                allowed=False,
                retry_after_seconds=retry_after_seconds,
                in_window=len(timestamps),
                max_requests=self.max_requests,
                window_seconds=self.window_seconds,
            )


_LIMITER_LOCK = threading.Lock()
_LIMITERS: dict[tuple[str, int, int], RejectingSlidingWindowRateLimiter] = {}


def reset_request_rate_limiters() -> None:
    with _LIMITER_LOCK:
        _LIMITERS.clear()


def enforce_auth_rate_limit(request: Request) -> None:
    route_label = _request_route_label(request)
    client_ip = _request_client_ip(request)
    _enforce_rate_limit(
        namespace="auth",
        key=f"ip:{client_ip}:{request.method}:{route_label}",
        label=route_label,
        subject_label=f"ip:{client_ip}",
        max_requests=max(int(get_settings().auth_rate_limit_max_requests), 0),
        window_seconds=max(int(get_settings().auth_rate_limit_window_seconds), 0),
    )


def enforce_user_mutation_rate_limit(request: Request, *, user_id: int) -> None:
    route_label = _request_route_label(request)
    _enforce_rate_limit(
        namespace="mutation",
        key=f"user:{user_id}:{request.method}:{route_label}",
        label=route_label,
        subject_label=f"user:{user_id}",
        max_requests=max(int(get_settings().mutation_rate_limit_max_requests), 0),
        window_seconds=max(int(get_settings().mutation_rate_limit_window_seconds), 0),
    )


def enforce_mcp_mutation_rate_limit(*, tool_name: str, user_id: int, auth_mode: str) -> None:
    _enforce_rate_limit(
        namespace="mcp-mutation",
        key=f"{auth_mode}:user:{user_id}:tool:{tool_name}",
        label=tool_name,
        subject_label=f"{auth_mode}:user:{user_id}",
        max_requests=max(int(get_settings().mutation_rate_limit_max_requests), 0),
        window_seconds=max(int(get_settings().mutation_rate_limit_window_seconds), 0),
    )


def _enforce_rate_limit(
    *,
    namespace: str,
    key: str,
    label: str,
    subject_label: str,
    max_requests: int,
    window_seconds: int,
) -> None:
    limiter = _get_limiter(namespace=namespace, max_requests=max_requests, window_seconds=window_seconds)
    result = limiter.try_acquire(key)
    if result.allowed:
        return
    logger.warning(
        "request rate limited namespace=%s label=%s subject=%s retry_after_seconds=%s in_window=%s max_requests=%s window_seconds=%s",
        namespace,
        label,
        subject_label,
        result.retry_after_seconds,
        result.in_window,
        result.max_requests,
        result.window_seconds,
    )
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=api_error_detail(
            code="rate_limited",
            message="Too many requests. Try again later.",
            message_code="common.rate_limited",
        ),
        headers={"Retry-After": str(result.retry_after_seconds)},
    )


def _get_limiter(*, namespace: str, max_requests: int, window_seconds: int) -> RejectingSlidingWindowRateLimiter:
    limiter_key = (namespace, max_requests, window_seconds)
    with _LIMITER_LOCK:
        limiter = _LIMITERS.get(limiter_key)
        if limiter is None:
            limiter = RejectingSlidingWindowRateLimiter(
                max_requests=max_requests,
                window_seconds=window_seconds,
            )
            _LIMITERS[limiter_key] = limiter
        return limiter


def _request_route_label(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if isinstance(path, str) and path.strip():
        return path
    return request.url.path


def _request_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "").strip()
    if forwarded_for:
        candidate = forwarded_for.split(",", 1)[0].strip()
        if candidate:
            return candidate
    client = getattr(request, "client", None)
    host = getattr(client, "host", None)
    if isinstance(host, str) and host.strip():
        return host
    return "unknown"


__all__ = [
    "enforce_auth_rate_limit",
    "enforce_mcp_mutation_rate_limit",
    "enforce_user_mutation_rate_limit",
    "reset_request_rate_limiters",
]
