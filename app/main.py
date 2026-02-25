from __future__ import annotations

import logging
import socket
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.core.config import get_settings
from app.core.logging import configure_logging, sanitize_log_message
from app.db.schema_guard import SchemaNotReadyError, ensure_schema_ready, is_schema_mismatch_error
from app.db.session import get_engine, get_session_factory
from app.modules.changes.router import router as changes_router
from app.modules.emails.router import router as emails_router
from app.modules.health.router import router as health_router
from app.modules.inputs.router import router as inputs_router
from app.modules.notify.router import router as notify_router
from app.modules.onboarding.router import router as onboarding_router
from app.modules.oauth.router import router as oauth_router
from app.modules.dev.router import router as dev_router
from app.modules.users.router import router as users_router
from app.modules.scheduler.runner import SchedulerRunner
from app.modules.status.router import router as status_router
from app.modules.ui.router import router as ui_router
from app.state import SchedulerStatus


logger = logging.getLogger(__name__)


def _assert_postgres_runtime() -> None:
    engine = get_engine()
    dialect = engine.dialect.name
    if dialect.startswith("postgresql"):
        return
    raise RuntimeError(
        "PostgreSQL-only runtime: expected PostgreSQL engine dialect, "
        f"got '{dialect}'."
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()
    _assert_postgres_runtime()

    schema_ready = True
    app.state.schema_guard_error = None
    if settings.schema_guard_enabled:
        try:
            ensure_schema_ready(get_engine(), force_refresh=True)
        except SchemaNotReadyError as exc:
            schema_ready = False
            app.state.schema_guard_error = str(exc)
            logger.error("schema readiness check failed error=%s", sanitize_log_message(str(exc)))
        except Exception as exc:  # pragma: no cover - startup defensive path
            schema_ready = False
            app.state.schema_guard_error = "Database schema check failed during startup."
            logger.error("schema startup check error=%s", sanitize_log_message(str(exc)))

    scheduler_status = SchedulerStatus()
    scheduler_status.instance_id = settings.scheduler_instance_id or socket.gethostname()
    scheduler_status.schema_guard_blocked = not schema_ready
    scheduler_status.schema_guard_message = app.state.schema_guard_error
    scheduler_runner = SchedulerRunner(get_session_factory(), scheduler_status)
    app.state.scheduler_runner = scheduler_runner

    if not settings.disable_scheduler and schema_ready:
        scheduler_runner.start()
    elif not schema_ready:
        logger.warning("scheduler startup skipped because database schema is not ready")

    try:
        yield
    finally:
        scheduler_runner.stop()


def _schema_not_ready_exception_handler(_: Request, exc: SchemaNotReadyError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


def _database_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    if is_schema_mismatch_error(exc):
        return JSONResponse(
            status_code=503,
            content={
                "detail": (
                    "Database schema is not ready for this app version. "
                    "Run `scripts/reset_postgres_db.sh` for local PostgreSQL reset, "
                    "or run `alembic upgrade head` against a fresh database."
                )
            },
        )

    logger.error("database operation failed error=%s", sanitize_log_message(str(exc)))
    return JSONResponse(status_code=500, content={"detail": "Database operation failed"})


def create_app() -> FastAPI:
    app = FastAPI(title="Deadline Diff Watcher", version="0.1.0", lifespan=lifespan)
    app.add_exception_handler(SchemaNotReadyError, _schema_not_ready_exception_handler)
    app.add_exception_handler(OperationalError, _database_exception_handler)
    app.add_exception_handler(ProgrammingError, _database_exception_handler)
    app.include_router(health_router)
    app.include_router(users_router)
    app.include_router(onboarding_router)
    app.include_router(changes_router)
    app.include_router(status_router)
    app.include_router(inputs_router)
    app.include_router(oauth_router)
    app.include_router(notify_router)
    app.include_router(dev_router)
    app.include_router(emails_router)
    app.include_router(ui_router)
    return app


app = create_app()
