from __future__ import annotations

import logging

from app.core.config import get_settings
from app.core.logging import sanitize_log_message
from app.db.session import get_session_factory
from app.modules.health.router import router as health_router
from app.modules.notify.consumer import run_notification_enqueue_tick
from app.modules.notify.digest_service import dispatch_pending_notifications
from app.modules.notify.metrics_router import router as notify_metrics_router
from app.modules.notify.ops_router import router as notify_ops_router
from app.runtime.service_workers import TickResult, build_periodic_worker_task, coerce_int_metric
from app.service_app import create_service_app

logger = logging.getLogger(__name__)
session_factory = get_session_factory()
settings = get_settings()

def _build_tick(worker_id: str):
    def _tick() -> dict[str, object]:
        enqueued_notifications = 0
        processed_batches = 0
        sent_count = 0
        failed_count = 0
        try:
            with session_factory() as db:
                if settings.enable_notifications:
                    enqueued_notifications = run_notification_enqueue_tick(db)
                    dispatch_result = dispatch_pending_notifications(db)
                    processed_batches = dispatch_result.processed_batches
                    sent_count = dispatch_result.sent_count
                    failed_count = dispatch_result.failed_count
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
            "processed_slots": processed_batches,
            "processed_batches": processed_batches,
            "sent_count": sent_count,
            "failed_count": failed_count,
        }

    return _tick


def _log_success(worker_id: str, result: TickResult, latency_ms: int) -> str:
    payload = result if isinstance(result, dict) else {}
    enqueued_notifications = coerce_int_metric(payload.get("enqueued_notifications"))
    processed_batches = coerce_int_metric(payload.get("processed_batches") or payload.get("processed_slots"))
    sent_count = coerce_int_metric(payload.get("sent_count"))
    failed_count = coerce_int_metric(payload.get("failed_count"))
    return (
        "notification tick worker_id=%s enqueued_notifications=%s processed_batches=%s sent_count=%s failed_count=%s tick_latency_ms=%s"
        % (
            worker_id,
            enqueued_notifications,
            processed_batches,
            sent_count,
            failed_count,
            latency_ms,
        )
    )


_run_notification_worker = build_periodic_worker_task(
    service_name="notification-service",
    worker_name="notification",
    worker_id_env="NOTIFICATION_WORKER_ID",
    enabled_env="NOTIFICATION_SERVICE_ENABLE_WORKER",
    tick_seconds_env="NOTIFICATION_TICK_SECONDS",
    default_tick_seconds=5.0,
    logger=logger,
    tick_builder=_build_tick,
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
