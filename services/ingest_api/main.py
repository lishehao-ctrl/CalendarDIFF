from __future__ import annotations

import logging

from app.core.logging import sanitize_log_message
from app.db.session import get_session_factory
from app.modules.health.router import router as health_router
from app.modules.ingestion.connector_runtime import run_connector_tick
from app.modules.ingestion.metrics_router import router as ingestion_metrics_router
from app.modules.ingestion.ops_router import router as ingestion_ops_router
from app.modules.ingestion.orchestrator import run_orchestrator_tick
from app.runtime.service_workers import TickResult, build_periodic_worker_task, coerce_int_metric
from app.service_app import create_service_app

logger = logging.getLogger(__name__)
session_factory = get_session_factory()


def _build_tick(worker_id: str):
    def _tick() -> dict[str, object]:
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
        return {
            "orchestrated_count": orchestrated_count,
            "connector_processed": connector_processed,
        }

    return _tick


def _log_success(worker_id: str, result: TickResult, latency_ms: int) -> str:
    payload = result if isinstance(result, dict) else {}
    orchestrated_count = coerce_int_metric(payload.get("orchestrated_count"))
    connector_processed = coerce_int_metric(payload.get("connector_processed"))
    return (
        "ingest service tick worker_id=%s orchestrated_count=%s connector_processed=%s latency_ms=%s"
        % (
            worker_id,
            orchestrated_count,
            connector_processed,
            latency_ms,
        )
    )


_run_ingest_worker = build_periodic_worker_task(
    service_name="ingest-service",
    worker_name="ingest service",
    worker_id_env="INGESTION_WORKER_ID",
    enabled_env="INGEST_SERVICE_ENABLE_WORKER",
    tick_seconds_env="INGESTION_TICK_SECONDS",
    default_tick_seconds=2.0,
    logger=logger,
    tick_builder=_build_tick,
    log_success=_log_success,
)


app = create_service_app(
    title="CalendarDIFF Ingest Service",
    version="0.1.0",
    routers=[
        health_router,
        ingestion_ops_router,
        ingestion_metrics_router,
    ],
    worker_tasks=[_run_ingest_worker],
)
