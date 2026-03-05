from __future__ import annotations

import logging

from app.core.logging import sanitize_log_message
from app.db.session import get_session_factory
from app.modules.core_ingest.router import router as core_ingest_router
from app.modules.health.router import router as health_router
from app.modules.core_ingest.worker import run_core_apply_tick
from app.modules.review_changes.metrics_router import router as review_metrics_router
from app.modules.review_changes.router import router as review_changes_router
from app.modules.review_links.alerts_event_consumer import run_review_link_alert_events_tick
from app.modules.review_links.router import router as review_links_router
from app.runtime.worker_loop import (
    build_worker_id,
    read_tick_seconds,
    read_worker_enabled,
    run_periodic_sync_worker,
)
from app.service_app import create_service_app

logger = logging.getLogger(__name__)


async def _run_review_apply_worker() -> None:
    worker_id = build_worker_id(service_name="review-service", env_var="REVIEW_APPLY_WORKER_ID")
    tick_seconds = read_tick_seconds(
        env_var="REVIEW_APPLY_TICK_SECONDS",
        default=2.0,
        logger=logger,
    )
    enabled = read_worker_enabled(env_var="REVIEW_SERVICE_ENABLE_APPLY_WORKER", default=True)
    session_factory = get_session_factory()

    def _tick() -> dict[str, int]:
        apply_processed = 0
        alert_events_processed = 0
        try:
            with session_factory() as db:
                try:
                    apply_processed = run_core_apply_tick(db)
                    alert_events_processed = run_review_link_alert_events_tick(db)
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
        return {"apply_processed": apply_processed, "alert_events_processed": alert_events_processed}

    def _log_success(result: dict[str, object] | int | None, latency_ms: int) -> str:
        payload = result if isinstance(result, dict) else {}
        apply_processed = int(payload.get("apply_processed") or 0)
        alert_events_processed = int(payload.get("alert_events_processed") or 0)
        return "review apply tick worker_id=%s apply_processed=%s alert_events_processed=%s latency_ms=%s" % (
            worker_id,
            apply_processed,
            alert_events_processed,
            latency_ms,
        )

    await run_periodic_sync_worker(
        worker_name="review apply",
        worker_id=worker_id,
        tick_seconds=tick_seconds,
        tick_sync_fn=_tick,
        logger=logger,
        enabled=enabled,
        disabled_env_var="REVIEW_SERVICE_ENABLE_APPLY_WORKER",
        log_success=_log_success,
    )


app = create_service_app(
    title="CalendarDIFF Review Service",
    version="0.1.0",
    public_api=True,
    routers=[
        health_router,
        review_changes_router,
        review_links_router,
        core_ingest_router,
        review_metrics_router,
    ],
    worker_tasks=[_run_review_apply_worker],
)
