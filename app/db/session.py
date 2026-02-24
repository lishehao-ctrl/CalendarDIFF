from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.schema_guard import ensure_schema_ready, reset_schema_guard_cache

_ENGINE: Engine | None = None
_SESSION_FACTORY: sessionmaker[Session] | None = None


def _assert_postgres_database_url(database_url: str) -> None:
    driver = make_url(database_url).drivername
    if driver.startswith("postgresql"):
        return
    raise RuntimeError(
        "PostgreSQL-only runtime: DATABASE_URL must use a PostgreSQL driver, "
        f"got '{driver}'."
    )


def _build_engine() -> Engine:
    settings = get_settings()
    _assert_postgres_database_url(settings.database_url)
    return create_engine(settings.database_url, pool_pre_ping=True, future=True)


def get_engine() -> Engine:
    global _ENGINE, _SESSION_FACTORY
    settings = get_settings()

    if _ENGINE is None or str(_ENGINE.url) != settings.database_url:
        _ENGINE = _build_engine()
        _SESSION_FACTORY = sessionmaker(bind=_ENGINE, autoflush=False, autocommit=False, expire_on_commit=False)
    return _ENGINE


def reset_engine() -> None:
    global _ENGINE, _SESSION_FACTORY
    if _ENGINE is not None:
        _ENGINE.dispose()
    _ENGINE = None
    _SESSION_FACTORY = None
    reset_schema_guard_cache()


def get_session_factory() -> sessionmaker[Session]:
    global _SESSION_FACTORY
    if _SESSION_FACTORY is None:
        get_engine()
    assert _SESSION_FACTORY is not None
    return _SESSION_FACTORY


def get_db() -> Generator[Session, None, None]:
    settings = get_settings()
    if settings.schema_guard_enabled:
        ensure_schema_ready(get_engine())

    session_factory = get_session_factory()
    db = session_factory()
    try:
        yield db
    finally:
        db.close()
