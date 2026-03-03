from __future__ import annotations

from dataclasses import dataclass, field

from app.core.config import get_settings
from app.modules.llm_runtime import limiter as limiter_module


@dataclass
class _FakeRedis:
    values: dict[str, float | int] = field(default_factory=dict)

    def eval(self, _script: str, key_count: int, *parts):  # noqa: ANN001 - test fake
        keys = list(parts[:key_count])
        args = list(parts[key_count:])
        token_key, ts_key, hard_key = keys
        now_ms = float(args[0])
        target_rps = float(args[1])
        hard_rps = int(args[2])
        burst = float(args[3])

        tokens = float(self.values.get(token_key, burst))
        last_ms = float(self.values.get(ts_key, now_ms))
        elapsed_ms = max(0.0, now_ms - last_ms)
        refill = (elapsed_ms / 1000.0) * target_rps
        tokens = min(burst, tokens + refill)

        hard_count = int(self.values.get(hard_key, 0))
        if hard_count >= hard_rps:
            self.values[token_key] = tokens
            self.values[ts_key] = now_ms
            return [0, "hard_cap", tokens, hard_count]

        if tokens < 1:
            self.values[token_key] = tokens
            self.values[ts_key] = now_ms
            return [0, "target_cap", tokens, hard_count]

        tokens -= 1
        hard_count += 1
        self.values[token_key] = tokens
        self.values[ts_key] = now_ms
        self.values[hard_key] = hard_count
        return [1, "ok", tokens, hard_count]


def test_limiter_hard_cap_50_rps(monkeypatch) -> None:
    monkeypatch.setenv("LLM_RATE_LIMIT_TARGET_RPS", "40")
    monkeypatch.setenv("LLM_RATE_LIMIT_HARD_RPS", "50")
    monkeypatch.setenv("LLM_RATE_LIMIT_BURST", "50")
    get_settings.cache_clear()
    try:
        fake_redis = _FakeRedis()
        now_seconds = {"value": 1000.0}
        monkeypatch.setattr(limiter_module.time, "time", lambda: now_seconds["value"])

        allowed = 0
        rejected = 0
        for _ in range(55):
            decision = limiter_module.acquire_global_permit(fake_redis)  # type: ignore[arg-type]
            if decision.allowed:
                allowed += 1
            else:
                rejected += 1
                assert decision.reason in {"hard_cap", "target_cap"}

        assert allowed == 50
        assert rejected == 5

        now_seconds["value"] = 1001.0
        decision = limiter_module.acquire_global_permit(fake_redis)  # type: ignore[arg-type]
        assert decision.allowed is True
    finally:
        get_settings.cache_clear()


def test_limiter_target_cap_when_burst_exhausted(monkeypatch) -> None:
    monkeypatch.setenv("LLM_RATE_LIMIT_TARGET_RPS", "2")
    monkeypatch.setenv("LLM_RATE_LIMIT_HARD_RPS", "50")
    monkeypatch.setenv("LLM_RATE_LIMIT_BURST", "2")
    get_settings.cache_clear()
    try:
        fake_redis = _FakeRedis()
        monkeypatch.setattr(limiter_module.time, "time", lambda: 2000.0)

        first = limiter_module.acquire_global_permit(fake_redis)  # type: ignore[arg-type]
        second = limiter_module.acquire_global_permit(fake_redis)  # type: ignore[arg-type]
        third = limiter_module.acquire_global_permit(fake_redis)  # type: ignore[arg-type]

        assert first.allowed is True
        assert second.allowed is True
        assert third.allowed is False
        assert third.reason == "target_cap"
    finally:
        get_settings.cache_clear()
