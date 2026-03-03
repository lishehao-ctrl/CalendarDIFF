from __future__ import annotations

import logging
import os
import socket
import threading

from app.db.session import get_session_factory
from app.modules.health.router import router as health_router
from app.modules.llm_runtime.metrics_router import router as llm_metrics_router
from app.modules.llm_runtime.worker import run_llm_worker_loop
from app.service_app import create_service_app

logger = logging.getLogger(__name__)


def _build_worker_id() -> str:
    env_worker_id = os.getenv("LLM_WORKER_ID")
    if env_worker_id:
        return env_worker_id
    return f"llm-service:{socket.gethostname()}:{os.getpid()}"


def _is_worker_enabled() -> bool:
    raw = os.getenv("LLM_SERVICE_ENABLE_WORKER", "true").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _start_llm_worker(stop_event: threading.Event) -> threading.Thread:
    def _runner() -> None:
        if not _is_worker_enabled():
            logger.info("llm worker disabled by LLM_SERVICE_ENABLE_WORKER")
            return
        worker_id = _build_worker_id()
        session_factory = get_session_factory()
        run_llm_worker_loop(
            stop_event=stop_event,
            worker_id=worker_id,
            session_factory=session_factory,
        )

    return threading.Thread(target=_runner, name="llm-service-worker", daemon=True)


app = create_service_app(
    title="CalendarDIFF LLM Service",
    version="0.1.0",
    routers=[
        health_router,
        llm_metrics_router,
    ],
    worker_starter=_start_llm_worker,
)
