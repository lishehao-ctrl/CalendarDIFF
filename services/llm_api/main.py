from __future__ import annotations

import logging

from app.db.session import get_session_factory
from app.modules.health.router import router as health_router
from app.modules.llm_runtime.metrics_router import router as llm_metrics_router
from app.modules.llm_runtime.tick_runner import run_llm_worker_tick
from app.modules.runtime_kernel.parse_task_queue import get_parse_queue_redis_client
from app.runtime.service_workers import TickResult, build_periodic_worker_task
from app.service_app import create_service_app

logger = logging.getLogger(__name__)
session_factory = get_session_factory()
redis_client = get_parse_queue_redis_client()


def _build_tick(worker_id: str):
    def _tick() -> int:
        return run_llm_worker_tick(
            redis_client=redis_client,
            session_factory=session_factory,
            worker_id=worker_id,
        )

    return _tick


def _log_success(worker_id: str, result: TickResult, latency_ms: int) -> str | None:
    processed = int(result) if isinstance(result, int) else 0
    if processed <= 0:
        return None
    return "llm worker tick worker_id=%s processed=%s latency_ms=%s" % (
        worker_id,
        processed,
        latency_ms,
    )


_run_llm_worker = build_periodic_worker_task(
    service_name="llm-service",
    worker_name="llm",
    worker_id_env="LLM_WORKER_ID",
    enabled_env="LLM_SERVICE_ENABLE_WORKER",
    logger=logger,
    tick_builder=_build_tick,
    log_success=_log_success,
    fixed_tick_seconds=0.05,
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
