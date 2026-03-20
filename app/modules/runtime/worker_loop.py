from __future__ import annotations

import logging
import os
import socket
import time
from collections.abc import Callable

import anyio

from app.core.logging import sanitize_log_message

TickResult = dict[str, object] | int | None
SuccessLogBuilder = Callable[[TickResult, int], str | None]


def build_worker_id(*, service_name: str, env_var: str) -> str:
    env_worker_id = os.getenv(env_var)
    if isinstance(env_worker_id, str) and env_worker_id.strip():
        return env_worker_id.strip()
    return f"{service_name}:{socket.gethostname()}:{os.getpid()}"


def read_worker_enabled(*, env_var: str, default: bool = True) -> bool:
    raw = os.getenv(env_var)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def read_tick_seconds(
    *,
    env_var: str,
    default: float,
    min_value: float = 0.1,
    logger: logging.Logger | None = None,
) -> float:
    raw = os.getenv(env_var)
    if raw is None:
        return max(min_value, float(default))
    try:
        value = float(raw)
    except ValueError:
        if logger is not None:
            logger.warning("invalid %s value=%s, fallback=%s", env_var, raw, default)
        value = float(default)
    return max(min_value, value)


async def run_periodic_sync_worker(
    *,
    worker_name: str,
    worker_id: str,
    tick_seconds: float,
    tick_sync_fn: Callable[[], TickResult],
    logger: logging.Logger,
    enabled: bool = True,
    disabled_env_var: str | None = None,
    log_success: SuccessLogBuilder | None = None,
) -> None:
    if not enabled:
        if isinstance(disabled_env_var, str) and disabled_env_var.strip():
            logger.info("%s worker disabled by %s", worker_name, disabled_env_var)
        else:
            logger.info("%s worker disabled", worker_name)
        return

    logger.info(
        "starting %s worker worker_id=%s tick_seconds=%s",
        worker_name,
        worker_id,
        tick_seconds,
    )
    while True:
        started = time.monotonic()
        result: TickResult = None
        try:
            result = await anyio.to_thread.run_sync(tick_sync_fn)
        except Exception as exc:  # pragma: no cover - defensive worker guard
            logger.error(
                "%s tick failed worker_id=%s error=%s",
                worker_name,
                worker_id,
                sanitize_log_message(str(exc)),
            )
        else:
            if log_success is not None:
                try:
                    message = log_success(result, max(int((time.monotonic() - started) * 1000), 0))
                except Exception as exc:  # pragma: no cover - defensive worker guard
                    logger.error(
                        "%s success logging failed worker_id=%s error=%s",
                        worker_name,
                        worker_id,
                        sanitize_log_message(str(exc)),
                    )
                else:
                    if isinstance(message, str) and message.strip():
                        logger.info("%s", message)

        elapsed = time.monotonic() - started
        await anyio.sleep(max(0.1, tick_seconds - elapsed))
