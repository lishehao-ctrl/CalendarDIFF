from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass

from app.core.config import get_settings


@dataclass(frozen=True)
class AcquireResult:
    waited_ms: int
    in_window: int
    max_requests: int
    window_seconds: int


class SlidingWindowRequestLimiter:
    def __init__(self, *, max_requests: int, window_seconds: int) -> None:
        self.max_requests = max(int(max_requests), 0)
        self.window_seconds = max(int(window_seconds), 0)
        self._lock = threading.Condition()
        self._timestamps: deque[float] = deque()

    def acquire(self) -> AcquireResult:
        if self.max_requests <= 0 or self.window_seconds <= 0:
            return AcquireResult(waited_ms=0, in_window=0, max_requests=self.max_requests, window_seconds=self.window_seconds)

        started = time.monotonic()
        with self._lock:
            while True:
                now = time.monotonic()
                cutoff = now - float(self.window_seconds)
                while self._timestamps and self._timestamps[0] <= cutoff:
                    self._timestamps.popleft()

                if len(self._timestamps) < self.max_requests:
                    self._timestamps.append(now)
                    waited_ms = max(int((now - started) * 1000), 0)
                    return AcquireResult(
                        waited_ms=waited_ms,
                        in_window=len(self._timestamps),
                        max_requests=self.max_requests,
                        window_seconds=self.window_seconds,
                    )

                wait_seconds = max(self._timestamps[0] + float(self.window_seconds) - now, 0.001)
                self._lock.wait(timeout=wait_seconds)


_LIMITER_STATE_LOCK = threading.Lock()
_LIMITER_STATE: tuple[int, int, SlidingWindowRequestLimiter] | None = None



def get_global_request_limiter() -> SlidingWindowRequestLimiter:
    settings = get_settings()
    max_requests = max(int(settings.llm_max_requests_per_window), 0)
    window_seconds = max(int(settings.llm_request_window_seconds), 0)

    global _LIMITER_STATE
    with _LIMITER_STATE_LOCK:
        if _LIMITER_STATE is None or _LIMITER_STATE[0] != max_requests or _LIMITER_STATE[1] != window_seconds:
            _LIMITER_STATE = (
                max_requests,
                window_seconds,
                SlidingWindowRequestLimiter(max_requests=max_requests, window_seconds=window_seconds),
            )
        return _LIMITER_STATE[2]
