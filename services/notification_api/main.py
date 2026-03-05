from __future__ import annotations

import logging

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.logging import sanitize_log_message
from app.db.models.notify import DigestSendLog
from app.db.session import get_session_factory
from app.modules.health.router import router as health_router
from app.modules.notify.consumer import run_notification_enqueue_tick
from app.modules.notify.digest_service import process_due_digests
from app.modules.notify.metrics_router import router as notify_metrics_router
from app.modules.notify.ops_router import router as notify_ops_router
from app.runtime.worker_loop import (
    build_worker_id,
    read_tick_seconds,
    read_worker_enabled,
    run_periodic_sync_worker,
)
from app.service_app import create_service_app

logger = logging.getLogger(__name__)


def _coerce_int_metric(value: object) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except Exception:
            return 0
    return 0


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


async def _run_notification_worker() -> None:
    worker_id = build_worker_id(service_name="notification-service", env_var="NOTIFICATION_WORKER_ID")
    tick_seconds = read_tick_seconds(
        env_var="NOTIFICATION_TICK_SECONDS",
        default=30.0,
        logger=logger,
    )
    enabled = read_worker_enabled(env_var="NOTIFICATION_SERVICE_ENABLE_WORKER", default=True)
    session_factory = get_session_factory()
    settings = get_settings()

    def _tick() -> dict[str, object]:
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
        return {
            "enqueued_notifications": enqueued_notifications,
            "processed_slots": processed_slots,
            "sent_count": sent_count,
            "failed_count": failed_count,
        }

    def _log_success(result: dict[str, object] | int | None, latency_ms: int) -> str:
        payload = result if isinstance(result, dict) else {}
        enqueued_notifications = _coerce_int_metric(payload.get("enqueued_notifications"))
        processed_slots = _coerce_int_metric(payload.get("processed_slots"))
        sent_count = _coerce_int_metric(payload.get("sent_count"))
        failed_count = _coerce_int_metric(payload.get("failed_count"))
        return (
            "notification tick worker_id=%s enqueued_notifications=%s processed_slots=%s "
            "sent_count=%s failed_count=%s tick_latency_ms=%s"
            % (
                worker_id,
                enqueued_notifications,
                processed_slots,
                sent_count,
                failed_count,
                latency_ms,
            )
        )

    await run_periodic_sync_worker(
        worker_name="notification",
        worker_id=worker_id,
        tick_seconds=tick_seconds,
        tick_sync_fn=_tick,
        logger=logger,
        enabled=enabled,
        disabled_env_var="NOTIFICATION_SERVICE_ENABLE_WORKER",
        log_success=_log_success,
    )


app = create_service_app(
    title="CalendarDIFF Notification Service",
    version="0.1.0",
    routers=[
        health_router,
        notify_ops_router,
        notify_metrics_router,
    ],
    worker_tasks=[_run_notification_worker],
)
