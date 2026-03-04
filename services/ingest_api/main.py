from __future__ import annotations

import logging

from app.core.logging import sanitize_log_message
from app.db.session import get_session_factory
from app.modules.health.router import router as health_router
from app.modules.ingestion.connector_runtime import run_connector_tick
from app.modules.ingestion.metrics_router import router as ingestion_metrics_router
from app.modules.ingestion.ops_router import router as ingestion_ops_router
from app.modules.ingestion.orchestrator import run_orchestrator_tick
from app.runtime.worker_loop import (
    build_worker_id,
    read_tick_seconds,
    read_worker_enabled,
    run_periodic_sync_worker,
)
from app.service_app import create_service_app

logger = logging.getLogger(__name__)


async def _run_ingest_worker() -> None:
    worker_id = build_worker_id(service_name="ingest-service", env_var="INGESTION_WORKER_ID")
    tick_seconds = read_tick_seconds(
        env_var="INGESTION_TICK_SECONDS",
        default=2.0,
        logger=logger,
    )
    enabled = read_worker_enabled(env_var="INGEST_SERVICE_ENABLE_WORKER", default=True)
    session_factory = get_session_factory()

    def _tick() -> dict[str, int]:
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

    def _log_success(result: dict[str, object] | int | None, latency_ms: int) -> str:
        payload = result if isinstance(result, dict) else {}
        orchestrated_count = int(payload.get("orchestrated_count") or 0)
        connector_processed = int(payload.get("connector_processed") or 0)
        return (
            "ingest service tick worker_id=%s orchestrated_count=%s connector_processed=%s latency_ms=%s"
            % (
                worker_id,
                orchestrated_count,
                connector_processed,
                latency_ms,
            )
        )

    await run_periodic_sync_worker(
        worker_name="ingest service",
        worker_id=worker_id,
        tick_seconds=tick_seconds,
        tick_sync_fn=_tick,
        logger=logger,
        enabled=enabled,
        disabled_env_var="INGEST_SERVICE_ENABLE_WORKER",
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
