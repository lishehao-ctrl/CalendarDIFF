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
from app.db.session import get_engine
from app.modules.health.router import router as health_router
from app.modules.input_control_plane.router import internal_router as input_internal_router
from app.modules.input_control_plane.router import public_router as input_public_router
from app.modules.input_control_plane.router import router as input_control_plane_router
from app.modules.onboarding.router import router as onboarding_router
from app.modules.users.router import router as users_router
from app.state import SchedulerStatus

logger = logging.getLogger(__name__)


def _assert_postgres_runtime() -> None:
    engine = get_engine()
    dialect = engine.dialect.name
    if dialect.startswith("postgresql"):
        return
    raise RuntimeError(f"PostgreSQL-only runtime: expected PostgreSQL dialect, got '{dialect}'.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()
    _assert_postgres_runtime()
    app.state.schema_guard_error = None
    if settings.schema_guard_enabled:
        try:
            ensure_schema_ready(get_engine(), force_refresh=True)
        except SchemaNotReadyError as exc:
            app.state.schema_guard_error = str(exc)
            logger.error("schema readiness check failed error=%s", sanitize_log_message(str(exc)))
    status = SchedulerStatus()
    status.instance_id = f"input-control-plane:{settings.scheduler_instance_id or socket.gethostname()}"
    status.running = False
    app.state.scheduler_runner = type("_NoopRunner", (), {"status": status})()
    yield


def _schema_not_ready_exception_handler(_: Request, exc: SchemaNotReadyError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


def _database_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    if is_schema_mismatch_error(exc):
        return JSONResponse(status_code=503, content={"detail": "Database schema is not ready for this app version."})
    logger.error("database operation failed error=%s", sanitize_log_message(str(exc)))
    return JSONResponse(status_code=500, content={"detail": "Database operation failed"})


def create_input_control_plane_app() -> FastAPI:
    app = FastAPI(title="Input Control Plane", version="2.0.0", lifespan=lifespan)
    app.add_exception_handler(SchemaNotReadyError, _schema_not_ready_exception_handler)
    app.add_exception_handler(OperationalError, _database_exception_handler)
    app.add_exception_handler(ProgrammingError, _database_exception_handler)
    app.include_router(health_router)
    app.include_router(users_router)
    app.include_router(onboarding_router)
    app.include_router(input_public_router)
    app.include_router(input_control_plane_router)
    app.include_router(input_internal_router)
    return app


app = create_input_control_plane_app()
