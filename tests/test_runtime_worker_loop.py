from __future__ import annotations

import logging
import time

import anyio

from app.modules.runtime import worker_loop


def test_read_tick_seconds_falls_back_on_invalid(monkeypatch) -> None:
    monkeypatch.setenv("TEST_TICK_SECONDS", "not-a-number")
    value = worker_loop.read_tick_seconds(env_var="TEST_TICK_SECONDS", default=2.0)
    assert value == 2.0


def test_read_worker_enabled_parses_truthy_and_falsy(monkeypatch) -> None:
    monkeypatch.setenv("TEST_WORKER_ENABLED", "yes")
    assert worker_loop.read_worker_enabled(env_var="TEST_WORKER_ENABLED", default=False) is True

    monkeypatch.setenv("TEST_WORKER_ENABLED", "nope")
    assert worker_loop.read_worker_enabled(env_var="TEST_WORKER_ENABLED", default=True) is False


def test_run_periodic_sync_worker_continues_after_tick_error() -> None:
    calls = {"count": 0}

    def _tick() -> int:
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("boom")
        return calls["count"]

    async def _worker() -> None:
        await worker_loop.run_periodic_sync_worker(
            worker_name="test",
            worker_id="worker-test",
            tick_seconds=0.1,
            tick_sync_fn=_tick,
            logger=logging.getLogger("tests.runtime.worker_loop"),
        )

    async def _run() -> None:
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(_worker)
            await anyio.sleep(0.25)
            task_group.cancel_scope.cancel()

    anyio.run(_run)
    assert calls["count"] >= 2


def test_run_periodic_sync_worker_uses_non_negative_sleep_floor(monkeypatch) -> None:
    class _StopLoop(Exception):
        pass

    sleep_values: list[float] = []
    original_sleep = worker_loop.anyio.sleep

    async def _capturing_sleep(seconds: float) -> None:
        sleep_values.append(seconds)
        raise _StopLoop()

    monkeypatch.setattr(worker_loop.anyio, "sleep", _capturing_sleep)

    def _slow_tick() -> int:
        time.sleep(0.15)
        return 1

    async def _run() -> None:
        await worker_loop.run_periodic_sync_worker(
            worker_name="test",
            worker_id="worker-test",
            tick_seconds=0.05,
            tick_sync_fn=_slow_tick,
            logger=logging.getLogger("tests.runtime.worker_loop"),
        )

    try:
        anyio.run(_run)
    except _StopLoop:
        pass
    finally:
        monkeypatch.setattr(worker_loop.anyio, "sleep", original_sleep)

    assert sleep_values
    assert sleep_values[0] >= 0.1
