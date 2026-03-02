from __future__ import annotations

import logging
import os
import socket
import time

from app.core.config import get_settings
from app.core.logging import configure_logging, sanitize_log_message
from app.db.schema_guard import ensure_schema_ready
from app.db.session import get_engine, get_session_factory
from app.modules.core_ingest.worker import run_core_apply_tick
from app.modules.ingestion.connector_runtime import run_connector_tick
from app.modules.ingestion.orchestrator import run_orchestrator_tick

logger = logging.getLogger(__name__)


def _build_worker_id() -> str:
    env_worker_id = os.getenv("INGESTION_WORKER_ID")
    if env_worker_id:
        return env_worker_id
    return f"ingestion-runtime:{socket.gethostname()}:{os.getpid()}"


def _read_tick_seconds() -> float:
    raw = os.getenv("INGESTION_TICK_SECONDS", "2")
    try:
        value = float(raw)
    except ValueError:
        logger.warning("invalid INGESTION_TICK_SECONDS value=%s, fallback=2", raw)
        value = 2.0
    return max(0.1, value)


def main() -> None:
    configure_logging()
    settings = get_settings()
    if settings.schema_guard_enabled:
        ensure_schema_ready(get_engine(), force_refresh=True)

    tick_seconds = _read_tick_seconds()
    worker_id = _build_worker_id()
    session_factory = get_session_factory()

    logger.info("starting ingestion runtime worker_id=%s tick_seconds=%s", worker_id, tick_seconds)

    while True:
        started = time.monotonic()
        orchestrated_count = 0
        connector_processed = 0
        apply_processed = 0

        try:
            with session_factory() as db:
                try:
                    orchestrated_count = run_orchestrator_tick(db, worker_id=worker_id)
                except Exception as exc:  # pragma: no cover - defensive worker loop
                    db.rollback()
                    logger.error(
                        "ingestion runtime stage failed stage=orchestrator worker_id=%s error=%s",
                        worker_id,
                        sanitize_log_message(str(exc)),
                    )

                try:
                    connector_processed = run_connector_tick(db, worker_id=worker_id)
                except Exception as exc:  # pragma: no cover - defensive worker loop
                    db.rollback()
                    logger.error(
                        "ingestion runtime stage failed stage=connector worker_id=%s error=%s",
                        worker_id,
                        sanitize_log_message(str(exc)),
                    )

                try:
                    apply_processed = run_core_apply_tick(db)
                except Exception as exc:  # pragma: no cover - defensive worker loop
                    db.rollback()
                    logger.error(
                        "ingestion runtime stage failed stage=apply worker_id=%s error=%s",
                        worker_id,
                        sanitize_log_message(str(exc)),
                    )
        except Exception as exc:  # pragma: no cover - defensive worker loop
            logger.error(
                "ingestion runtime tick failed worker_id=%s error=%s",
                worker_id,
                sanitize_log_message(str(exc)),
            )

        elapsed = time.monotonic() - started
        latency_ms = int(elapsed * 1000)
        logger.info(
            "ingestion runtime tick worker_id=%s orchestrated_count=%s connector_processed=%s "
            "apply_processed=%s latency_ms=%s",
            worker_id,
            orchestrated_count,
            connector_processed,
            apply_processed,
            latency_ms,
        )
        time.sleep(max(0.1, tick_seconds - elapsed))


if __name__ == "__main__":
    main()
