from __future__ import annotations

import random


def truncate_error(message: str, *, max_len: int = 512) -> str:
    value = (message or "").strip()
    if len(value) <= max_len:
        return value
    return value[:max_len]


def compute_retry_delay_seconds(
    *,
    attempt: int,
    base_seconds: int,
    max_seconds: int,
    jitter_seconds: int,
) -> int:
    exponent = max(attempt - 1, 0)
    base = max(1, int(base_seconds))
    ceiling = max(base, int(max_seconds))
    jitter = max(0, int(jitter_seconds))
    delay = min(base * (2**exponent), ceiling)
    if jitter > 0:
        delay += random.randint(0, jitter)
    return max(1, int(delay))


__all__ = ["compute_retry_delay_seconds", "truncate_error"]
