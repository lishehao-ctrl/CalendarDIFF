from __future__ import annotations

import time
from dataclasses import dataclass

import redis

from app.core.config import get_settings
from app.modules.llm_runtime.queue import queue_stream_key


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    reason: str
    remaining_tokens: float
    hard_counter: int


_LUA_LIMITER = """
local token_key = KEYS[1]
local ts_key = KEYS[2]
local hard_key = KEYS[3]

local now_ms = tonumber(ARGV[1])
local target_rps = tonumber(ARGV[2])
local hard_rps = tonumber(ARGV[3])
local burst = tonumber(ARGV[4])

if target_rps <= 0 then
  return {0, "invalid_target", 0, 0}
end
if hard_rps <= 0 then
  return {0, "invalid_hard", 0, 0}
end
if burst <= 0 then
  return {0, "invalid_burst", 0, 0}
end

local tokens = tonumber(redis.call("GET", token_key))
local last_ms = tonumber(redis.call("GET", ts_key))
if tokens == nil then
  tokens = burst
end
if last_ms == nil then
  last_ms = now_ms
end

local elapsed_ms = now_ms - last_ms
if elapsed_ms < 0 then
  elapsed_ms = 0
end

local refill = (elapsed_ms / 1000.0) * target_rps
tokens = math.min(burst, tokens + refill)

local hard_count = tonumber(redis.call("GET", hard_key))
if hard_count == nil then
  hard_count = 0
end
if hard_count >= hard_rps then
  redis.call("SET", token_key, tostring(tokens), "PX", 60000)
  redis.call("SET", ts_key, tostring(now_ms), "PX", 60000)
  return {0, "hard_cap", tokens, hard_count}
end

if tokens < 1 then
  redis.call("SET", token_key, tostring(tokens), "PX", 60000)
  redis.call("SET", ts_key, tostring(now_ms), "PX", 60000)
  return {0, "target_cap", tokens, hard_count}
end

tokens = tokens - 1
hard_count = redis.call("INCR", hard_key)
if hard_count == 1 then
  redis.call("EXPIRE", hard_key, 2)
end

redis.call("SET", token_key, tostring(tokens), "PX", 60000)
redis.call("SET", ts_key, tostring(now_ms), "PX", 60000)
return {1, "ok", tokens, hard_count}
"""


def _limiter_prefix() -> str:
    stream_key = queue_stream_key()
    return f"{stream_key}:limiter:v1"


def _limiter_keys(*, now_seconds: int) -> tuple[str, str, str]:
    prefix = _limiter_prefix()
    return (
        f"{prefix}:tokens",
        f"{prefix}:ts_ms",
        f"{prefix}:hard:{now_seconds}",
    )


def acquire_global_permit(client: redis.Redis) -> RateLimitDecision:
    settings = get_settings()
    now_ms = int(time.time() * 1000)
    now_seconds = now_ms // 1000
    keys = _limiter_keys(now_seconds=now_seconds)
    args = [
        now_ms,
        int(settings.llm_rate_limit_target_rps),
        int(settings.llm_rate_limit_hard_rps),
        int(settings.llm_rate_limit_burst),
    ]
    raw = client.eval(_LUA_LIMITER, len(keys), *keys, *args)
    if not isinstance(raw, list) or len(raw) < 4:
        return RateLimitDecision(allowed=False, reason="limiter_malformed_result", remaining_tokens=0.0, hard_counter=0)
    allowed_raw, reason_raw, remaining_raw, hard_raw = raw[:4]
    allowed = bool(int(allowed_raw)) if isinstance(allowed_raw, (int, str)) else False
    reason = str(reason_raw)
    try:
        remaining_tokens = float(remaining_raw)
    except Exception:
        remaining_tokens = 0.0
    try:
        hard_counter = int(hard_raw)
    except Exception:
        hard_counter = 0
    return RateLimitDecision(
        allowed=allowed,
        reason=reason,
        remaining_tokens=remaining_tokens,
        hard_counter=hard_counter,
    )
