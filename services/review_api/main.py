from __future__ import annotations

import logging

from app.core.logging import sanitize_log_message
from app.db.session import get_session_factory
from app.modules.core_ingest.router import router as core_ingest_router
from app.modules.core_ingest.worker import run_core_apply_tick
from app.modules.health.router import router as health_router
from app.modules.review_changes.metrics_router import router as review_metrics_router
from app.runtime.service_workers import TickResult, build_periodic_worker_task, coerce_int_metric
from app.service_app import create_service_app

logger = logging.getLogger(__name__)
session_factory = get_session_factory()


def _build_tick(worker_id: str):
    def _tick() -> dict[str, object]:
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
        return {"apply_processed": apply_processed}

    return _tick


def _log_success(worker_id: str, result: TickResult, latency_ms: int) -> str:
    payload = result if isinstance(result, dict) else {}
    apply_processed = coerce_int_metric(payload.get("apply_processed"))
    return "review apply tick worker_id=%s apply_processed=%s latency_ms=%s" % (
        worker_id,
        apply_processed,
        latency_ms,
    )


_run_review_apply_worker = build_periodic_worker_task(
    service_name="review-service",
    worker_name="review apply",
    worker_id_env="REVIEW_APPLY_WORKER_ID",
    enabled_env="REVIEW_SERVICE_ENABLE_APPLY_WORKER",
    tick_seconds_env="REVIEW_APPLY_TICK_SECONDS",
    default_tick_seconds=2.0,
    logger=logger,
    tick_builder=_build_tick,
    log_success=_log_success,
)


app = create_service_app(
    title="CalendarDIFF Review Service",
    version="0.1.0",
    public_api=False,
    routers=[
        health_router,
        core_ingest_router,
        review_metrics_router,
    ],
    worker_tasks=[_run_review_apply_worker],
)
