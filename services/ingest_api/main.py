from __future__ import annotations

import logging
import os
import socket
import threading
import time

from app.core.logging import sanitize_log_message
from app.db.session import get_session_factory
from app.modules.health.router import router as health_router
from app.modules.ingestion.connector_runtime import run_connector_tick
from app.modules.ingestion.metrics_router import router as ingestion_metrics_router
from app.modules.ingestion.ops_router import router as ingestion_ops_router
from app.modules.ingestion.orchestrator import run_orchestrator_tick
from app.service_app import create_service_app

logger = logging.getLogger(__name__)


def _build_worker_id() -> str:
    env_worker_id = os.getenv("INGESTION_WORKER_ID")
    if env_worker_id:
        return env_worker_id
    return f"ingest-service:{socket.gethostname()}:{os.getpid()}"


def _read_tick_seconds() -> float:
    raw = os.getenv("INGESTION_TICK_SECONDS", "2")
    try:
        value = float(raw)
    except ValueError:
        logger.warning("invalid INGESTION_TICK_SECONDS value=%s, fallback=2", raw)
        value = 2.0
    return max(0.1, value)


def _is_worker_enabled() -> bool:
    raw = os.getenv("INGEST_SERVICE_ENABLE_WORKER", "true").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _start_ingest_worker(stop_event: threading.Event) -> threading.Thread:
    def _runner() -> None:
        if not _is_worker_enabled():
            logger.info("ingest service worker disabled by INGEST_SERVICE_ENABLE_WORKER")
            return

        tick_seconds = _read_tick_seconds()
        worker_id = _build_worker_id()
        session_factory = get_session_factory()

        logger.info("starting ingest service worker worker_id=%s tick_seconds=%s", worker_id, tick_seconds)

        while not stop_event.is_set():
            started = time.monotonic()
            orchestrated_count = 0
            connector_processed = 0
            try:
                with session_factory() as db:
                    try:
                        orchestrated_count = run_orchestrator_tick(db, worker_id=worker_id)
                    except Exception as exc:  # pragma: no cover - defensive worker loop
                        db.rollback()
                        logger.error(
                            "ingest service stage failed stage=orchestrator worker_id=%s error=%s",
                            worker_id,
                            sanitize_log_message(str(exc)),
                        )

                    try:
                        connector_processed = run_connector_tick(db, worker_id=worker_id)
                    except Exception as exc:  # pragma: no cover - defensive worker loop
                        db.rollback()
                        logger.error(
                            "ingest service stage failed stage=connector worker_id=%s error=%s",
                            worker_id,
                            sanitize_log_message(str(exc)),
                        )
            except Exception as exc:  # pragma: no cover - defensive worker loop
                logger.error(
                    "ingest service tick failed worker_id=%s error=%s",
                    worker_id,
                    sanitize_log_message(str(exc)),
                )

            elapsed = time.monotonic() - started
            latency_ms = int(elapsed * 1000)
            logger.info(
                "ingest service tick worker_id=%s orchestrated_count=%s connector_processed=%s latency_ms=%s",
                worker_id,
                orchestrated_count,
                connector_processed,
                latency_ms,
            )
            stop_event.wait(max(0.1, tick_seconds - elapsed))

    return threading.Thread(target=_runner, name="ingest-service-worker", daemon=True)


app = create_service_app(
    title="CalendarDIFF Ingest Service",
    version="0.1.0",
    routers=[
        health_router,
        ingestion_ops_router,
        ingestion_metrics_router,
    ],
    worker_starter=_start_ingest_worker,
)
