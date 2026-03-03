from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.core.config import get_settings
from app.core.logging import configure_logging, sanitize_log_message
from app.db.schema_guard import SchemaNotReadyError, ensure_schema_ready, is_schema_mismatch_error
from app.db.session import get_engine

logger = logging.getLogger(__name__)


WorkerStarter = Callable[[threading.Event], threading.Thread]


def _assert_postgres_runtime() -> None:
    engine = get_engine()
    dialect = engine.dialect.name
    if dialect.startswith("postgresql"):
        return
    raise RuntimeError(
        "PostgreSQL-only runtime: expected PostgreSQL engine dialect, "
        f"got '{dialect}'."
    )


def _schema_not_ready_exception_handler(_: Request, exc: SchemaNotReadyError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


def _database_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    if is_schema_mismatch_error(exc):
        return JSONResponse(
            status_code=503,
            content={
                "detail": (
                    "Database schema is not ready for this app version. "
                    "In-place upgrades from prior migration chains are not supported. "
                    "Run `scripts/reset_postgres_db.sh` for local PostgreSQL reset, "
                    "then run `alembic upgrade head` against a fresh database."
                )
            },
        )

    logger.error("database operation failed error=%s", sanitize_log_message(str(exc)))
    return JSONResponse(status_code=500, content={"detail": "Database operation failed"})


def _parse_public_web_origins(raw_value: str | None) -> list[str]:
    if not raw_value:
        return []
    return [item.strip() for item in raw_value.split(",") if item and item.strip()]


def create_service_app(
    *,
    title: str,
    version: str,
    routers: Iterable[APIRouter],
    public_api: bool = False,
    worker_starter: WorkerStarter | None = None,
) -> FastAPI:
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

        if not schema_ready:
            logger.warning("service startup warnings because database schema is not ready")

        stop_event = threading.Event()
        worker_thread: threading.Thread | None = None
        if worker_starter is not None:
            worker_thread = worker_starter(stop_event)
            worker_thread.start()

        try:
            yield
        finally:
            stop_event.set()
            if worker_thread is not None:
                worker_thread.join(timeout=5)

    app = FastAPI(title=title, version=version, lifespan=lifespan)
    app.add_exception_handler(SchemaNotReadyError, _schema_not_ready_exception_handler)
    app.add_exception_handler(OperationalError, _database_exception_handler)
    app.add_exception_handler(ProgrammingError, _database_exception_handler)
    if public_api:
        settings = get_settings()
        allowed_origins = _parse_public_web_origins(settings.public_web_origins)
        if allowed_origins:
            app.add_middleware(
                CORSMiddleware,
                allow_origins=allowed_origins,
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
            )
    for router in routers:
        app.include_router(router)
    return app
