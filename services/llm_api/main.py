from __future__ import annotations

import logging

from app.db.session import get_session_factory
from app.modules.health.router import router as health_router
from app.modules.llm_runtime.metrics_router import router as llm_metrics_router
from app.modules.llm_runtime.queue import get_redis_client
from app.modules.llm_runtime.worker_tick import run_llm_worker_tick
from app.runtime.worker_loop import build_worker_id, read_worker_enabled, run_periodic_sync_worker
from app.service_app import create_service_app

logger = logging.getLogger(__name__)


async def _run_llm_worker() -> None:
    worker_id = build_worker_id(service_name="llm-service", env_var="LLM_WORKER_ID")
    enabled = read_worker_enabled(env_var="LLM_SERVICE_ENABLE_WORKER", default=True)
    session_factory = get_session_factory()
    redis_client = get_redis_client()

    def _tick() -> int:
        return run_llm_worker_tick(
            redis_client=redis_client,
            session_factory=session_factory,
            worker_id=worker_id,
        )

    def _log_success(result: dict[str, object] | int | None, latency_ms: int) -> str | None:
        processed = int(result) if isinstance(result, int) else 0
        if processed <= 0:
            return None
        return "llm worker tick worker_id=%s processed=%s latency_ms=%s" % (
            worker_id,
            processed,
            latency_ms,
        )

    await run_periodic_sync_worker(
        worker_name="llm",
        worker_id=worker_id,
        tick_seconds=0.05,
        tick_sync_fn=_tick,
        logger=logger,
        enabled=enabled,
        disabled_env_var="LLM_SERVICE_ENABLE_WORKER",
        log_success=_log_success,
    )


app = create_service_app(
    title="CalendarDIFF LLM Service",
    version="0.1.0",
    routers=[
        health_router,
        llm_metrics_router,
    ],
    worker_tasks=[_run_llm_worker],
)
