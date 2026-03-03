from __future__ import annotations

import logging
import os
import socket
import time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import configure_logging, sanitize_log_message
from app.db.models import DigestSendLog
from app.db.schema_guard import ensure_schema_ready
from app.db.session import get_engine, get_session_factory
from app.modules.notify.consumer import run_notification_enqueue_tick
from app.modules.notify.digest_service import process_due_digests

logger = logging.getLogger(__name__)


def _build_worker_id() -> str:
    env_worker_id = os.getenv("NOTIFICATION_WORKER_ID")
    if env_worker_id:
        return env_worker_id
    return f"notification:{socket.gethostname()}:{os.getpid()}"


def _read_tick_seconds() -> float:
    raw = os.getenv("NOTIFICATION_TICK_SECONDS", "30")
    try:
        value = float(raw)
    except ValueError:
        logger.warning("invalid NOTIFICATION_TICK_SECONDS value=%s, fallback=30", raw)
        value = 30.0
    return max(0.1, value)


def _count_digest_results(db: Session) -> tuple[int, int]:
    sent = 0
    failed = 0
    rows = db.execute(select(DigestSendLog.status, func.count()).group_by(DigestSendLog.status)).all()
    for status, count in rows:
        if status == "sent":
            sent = int(count)
        elif status == "failed":
            failed = int(count)
    return sent, failed


def main() -> None:
    configure_logging()
    settings = get_settings()
    if settings.schema_guard_enabled:
        ensure_schema_ready(get_engine(), force_refresh=True)

    tick_seconds = _read_tick_seconds()
    worker_id = _build_worker_id()
    session_factory = get_session_factory()

    logger.info(
        "starting notification worker_id=%s tick_seconds=%s notifications_enabled=%s",
        worker_id,
        tick_seconds,
        settings.enable_notifications,
    )

    while True:
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
            "notification tick worker_id=%s enqueued_notifications=%s processed_slots=%s sent_count=%s "
            "failed_count=%s tick_latency_ms=%s",
            worker_id,
            enqueued_notifications,
            processed_slots,
            sent_count,
            failed_count,
            tick_latency_ms,
        )

        time.sleep(max(0.1, tick_seconds - elapsed))


if __name__ == "__main__":
    main()
