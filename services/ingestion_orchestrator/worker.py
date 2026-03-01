from __future__ import annotations

import logging
import os
import socket
import time

from app.core.config import get_settings
from app.core.logging import configure_logging, sanitize_log_message
from app.db.schema_guard import ensure_schema_ready
from app.db.session import get_engine, get_session_factory
from app.modules.ingestion.orchestrator import run_orchestrator_tick

logger = logging.getLogger(__name__)


def _build_worker_id() -> str:
    env_worker_id = os.getenv("ORCHESTRATOR_WORKER_ID")
    if env_worker_id:
        return env_worker_id
    return f"orchestrator:{socket.gethostname()}:{os.getpid()}"


def main() -> None:
    configure_logging()
    settings = get_settings()
    if settings.schema_guard_enabled:
        ensure_schema_ready(get_engine(), force_refresh=True)

    tick_seconds = float(os.getenv("ORCHESTRATOR_TICK_SECONDS", str(max(settings.scheduler_tick_seconds, 1))))
    worker_id = _build_worker_id()
    session_factory = get_session_factory()

    logger.info("starting ingestion orchestrator worker_id=%s tick_seconds=%s", worker_id, tick_seconds)
    while True:
        started = time.monotonic()
        try:
            with session_factory() as db:
                run_orchestrator_tick(db, worker_id=worker_id)
        except Exception as exc:  # pragma: no cover - defensive worker loop
            logger.error("orchestrator tick failed error=%s", sanitize_log_message(str(exc)))
        elapsed = time.monotonic() - started
        sleep_seconds = max(0.1, tick_seconds - elapsed)
        time.sleep(sleep_seconds)


if __name__ == "__main__":
    main()
