from __future__ import annotations

import logging
import os
import socket
import threading
import time

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.logging import sanitize_log_message
from app.db.models import DigestSendLog
from app.db.session import get_session_factory
from app.modules.health.router import router as health_router
from app.modules.notify.consumer import run_notification_enqueue_tick
from app.modules.notify.digest_service import process_due_digests
from app.modules.notify.metrics_router import router as notify_metrics_router
from app.modules.notify.ops_router import router as notify_ops_router
from app.service_app import create_service_app

logger = logging.getLogger(__name__)


def _build_worker_id() -> str:
    env_worker_id = os.getenv("NOTIFICATION_WORKER_ID")
    if env_worker_id:
        return env_worker_id
    return f"notification-service:{socket.gethostname()}:{os.getpid()}"


def _read_tick_seconds() -> float:
    raw = os.getenv("NOTIFICATION_TICK_SECONDS", "30")
    try:
        value = float(raw)
    except ValueError:
        logger.warning("invalid NOTIFICATION_TICK_SECONDS value=%s, fallback=30", raw)
        value = 30.0
    return max(0.1, value)


def _is_worker_enabled() -> bool:
    raw = os.getenv("NOTIFICATION_SERVICE_ENABLE_WORKER", "true").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _count_digest_results(db) -> tuple[int, int]:
    sent = 0
    failed = 0
    rows = db.execute(select(DigestSendLog.status, func.count()).group_by(DigestSendLog.status)).all()
    for status, count in rows:
        if status == "sent":
            sent = int(count)
        elif status == "failed":
            failed = int(count)
    return sent, failed


def _start_notification_worker(stop_event: threading.Event) -> threading.Thread:
    def _runner() -> None:
        if not _is_worker_enabled():
            logger.info("notification worker disabled by NOTIFICATION_SERVICE_ENABLE_WORKER")
            return

        tick_seconds = _read_tick_seconds()
        worker_id = _build_worker_id()
        session_factory = get_session_factory()
        settings = get_settings()

        logger.info(
            "starting notification worker worker_id=%s tick_seconds=%s notifications_enabled=%s",
            worker_id,
            tick_seconds,
            settings.enable_notifications,
        )

        while not stop_event.is_set():
            started = time.monotonic()
            enqueued_notifications = 0
            processed_slots = 0
            sent_count = 0
            failed_count = 0

            try:
                with session_factory() as db:
                    if settings.enable_notifications:
                        enqueued_notifications = run_notification_enqueue_tick(db)
                        sent_before, failed_before = _count_digest_results(db)
                        processed_slots = process_due_digests(db)
                        sent_after, failed_after = _count_digest_results(db)
                        sent_count = max(sent_after - sent_before, 0)
                        failed_count = max(failed_after - failed_before, 0)
                    else:
                        logger.info(
                            "notification tick skipped worker_id=%s reason=notifications_disabled",
                            worker_id,
                        )
            except Exception as exc:  # pragma: no cover - defensive worker loop
                logger.error(
                    "notification tick failed worker_id=%s error=%s",
                    worker_id,
                    sanitize_log_message(str(exc)),
                )

            elapsed = time.monotonic() - started
            tick_latency_ms = int(elapsed * 1000)
            logger.info(
                "notification tick worker_id=%s enqueued_notifications=%s processed_slots=%s "
                "sent_count=%s failed_count=%s tick_latency_ms=%s",
                worker_id,
                enqueued_notifications,
                processed_slots,
                sent_count,
                failed_count,
                tick_latency_ms,
            )

            stop_event.wait(max(0.1, tick_seconds - elapsed))

    return threading.Thread(target=_runner, name="notification-service-worker", daemon=True)


app = create_service_app(
    title="CalendarDIFF Notification Service",
    version="0.1.0",
    routers=[
        health_router,
        notify_ops_router,
        notify_metrics_router,
    ],
    worker_starter=_start_notification_worker,
)
