from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import get_session_factory
from app.modules.changes.router import router as changes_router
from app.modules.health.router import router as health_router
from app.modules.scheduler.runner import SchedulerRunner
from app.modules.snapshots.router import router as snapshots_router
from app.modules.sources.router import router as sources_router
from app.state import SchedulerStatus


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()

    scheduler_status = SchedulerStatus()
    scheduler_runner = SchedulerRunner(get_session_factory(), scheduler_status)
    app.state.scheduler_runner = scheduler_runner

    if not settings.disable_scheduler:
        scheduler_runner.start()

    try:
        yield
    finally:
        scheduler_runner.stop()


def create_app() -> FastAPI:
    app = FastAPI(title="Deadline Diff Watcher", version="0.1.0", lifespan=lifespan)
    app.include_router(health_router)
    app.include_router(sources_router)
    app.include_router(changes_router)
    app.include_router(snapshots_router)
    return app


app = create_app()
