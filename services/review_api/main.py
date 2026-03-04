from __future__ import annotations

import logging
import os
import socket
import threading
import time

from app.core.logging import sanitize_log_message
from app.db.session import get_session_factory
from app.modules.core_ingest.router import router as core_ingest_router
from app.modules.emails.router import router as emails_router
from app.modules.events.router import router as events_router
from app.modules.health.router import router as health_router
from app.modules.core_ingest.worker import run_core_apply_tick
from app.modules.review_changes.metrics_router import router as review_metrics_router
from app.modules.review_changes.router import router as review_changes_router
from app.modules.review_links.router import router as review_links_router
from app.service_app import create_service_app

logger = logging.getLogger(__name__)


def _build_worker_id() -> str:
    env_worker_id = os.getenv("REVIEW_APPLY_WORKER_ID")
    if env_worker_id:
        return env_worker_id
    return f"review-service:{socket.gethostname()}:{os.getpid()}"


def _read_tick_seconds() -> float:
    raw = os.getenv("REVIEW_APPLY_TICK_SECONDS", "2")
    try:
        value = float(raw)
    except ValueError:
        logger.warning("invalid REVIEW_APPLY_TICK_SECONDS value=%s, fallback=2", raw)
        value = 2.0
    return max(0.1, value)


def _is_worker_enabled() -> bool:
    raw = os.getenv("REVIEW_SERVICE_ENABLE_APPLY_WORKER", "true").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _start_review_apply_worker(stop_event: threading.Event) -> threading.Thread:
    def _runner() -> None:
        if not _is_worker_enabled():
            logger.info("review apply worker disabled by REVIEW_SERVICE_ENABLE_APPLY_WORKER")
            return

        tick_seconds = _read_tick_seconds()
        worker_id = _build_worker_id()
        session_factory = get_session_factory()

        logger.info("starting review apply worker worker_id=%s tick_seconds=%s", worker_id, tick_seconds)

        while not stop_event.is_set():
            started = time.monotonic()
            apply_processed = 0
            try:
                with session_factory() as db:
                    try:
                        apply_processed = run_core_apply_tick(db)
                    except Exception as exc:  # pragma: no cover - defensive worker loop
                        db.rollback()
                        logger.error(
                            "review apply stage failed worker_id=%s error=%s",
                            worker_id,
                            sanitize_log_message(str(exc)),
                        )
            except Exception as exc:  # pragma: no cover - defensive worker loop
                logger.error(
                    "review apply tick failed worker_id=%s error=%s",
                    worker_id,
                    sanitize_log_message(str(exc)),
                )

            elapsed = time.monotonic() - started
            latency_ms = int(elapsed * 1000)
            logger.info(
                "review apply tick worker_id=%s apply_processed=%s latency_ms=%s",
                worker_id,
                apply_processed,
                latency_ms,
            )
            stop_event.wait(max(0.1, tick_seconds - elapsed))

    return threading.Thread(target=_runner, name="review-apply-worker", daemon=True)


app = create_service_app(
    title="CalendarDIFF Review Service",
    version="0.1.0",
    public_api=True,
    routers=[
        health_router,
        review_changes_router,
        review_links_router,
        events_router,
        emails_router,
        core_ingest_router,
        review_metrics_router,
    ],
    worker_starter=_start_review_apply_worker,
)
