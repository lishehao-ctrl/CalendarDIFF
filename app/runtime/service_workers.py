from __future__ import annotations

import logging
from collections.abc import Callable

from app.runtime.worker_loop import build_worker_id, read_tick_seconds, read_worker_enabled, run_periodic_sync_worker

TickResult = dict[str, object] | int | None
TickSyncFn = Callable[[], TickResult]
TickBuilder = Callable[[str], TickSyncFn]
SuccessLogBuilder = Callable[[str, TickResult, int], str | None]


def coerce_int_metric(value: object) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except Exception:
            return 0
    return 0


def build_periodic_worker_task(
    *,
    service_name: str,
    worker_name: str,
    worker_id_env: str,
    enabled_env: str,
    logger: logging.Logger,
    tick_builder: TickBuilder,
    log_success: SuccessLogBuilder,
    default_tick_seconds: float | None = None,
    tick_seconds_env: str | None = None,
    fixed_tick_seconds: float | None = None,
):
    async def _run() -> None:
        worker_id = build_worker_id(service_name=service_name, env_var=worker_id_env)
        enabled = read_worker_enabled(env_var=enabled_env, default=True)
        if fixed_tick_seconds is not None:
            tick_seconds = fixed_tick_seconds
        else:
            if tick_seconds_env is None or default_tick_seconds is None:
                raise RuntimeError("tick_seconds_env and default_tick_seconds are required when fixed_tick_seconds is not set")
            tick_seconds = read_tick_seconds(
                env_var=tick_seconds_env,
                default=default_tick_seconds,
                logger=logger,
            )

        tick_sync_fn = tick_builder(worker_id)

        def _log_success(result: TickResult, latency_ms: int) -> str | None:
            return log_success(worker_id, result, latency_ms)

        await run_periodic_sync_worker(
            worker_name=worker_name,
            worker_id=worker_id,
            tick_seconds=tick_seconds,
            tick_sync_fn=tick_sync_fn,
            logger=logger,
            enabled=enabled,
            disabled_env_var=enabled_env,
            log_success=_log_success,
        )

    return _run


__all__ = [
    "TickResult",
    "coerce_int_metric",
    "build_periodic_worker_task",
]
