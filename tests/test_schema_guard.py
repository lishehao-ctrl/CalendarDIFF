from __future__ import annotations

import os
import uuid

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import URL, make_url

from app.core.config import get_settings
from app.db.schema_guard import reset_schema_guard_cache
from app.db.session import reset_engine
from app.main import create_app


ENV_KEYS = ("APP_API_KEY", "APP_SECRET_KEY", "DATABASE_URL", "DISABLE_SCHEDULER", "SCHEMA_GUARD_ENABLED")


def _build_temp_db_urls(base_url: str) -> tuple[URL, URL, str]:
    db_name = f"deadline_diff_guard_{uuid.uuid4().hex[:8]}"
    target_url = make_url(base_url).set(database=db_name)
    admin_url = target_url.set(database="postgres")
    return target_url, admin_url, db_name


def _create_database(admin_url: URL, db_name: str) -> None:
    engine = create_engine(admin_url, future=True, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    finally:
        engine.dispose()


def _drop_database(admin_url: URL, db_name: str) -> None:
    engine = create_engine(admin_url, future=True, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
    finally:
        engine.dispose()


def _reset_runtime_state() -> None:
    get_settings.cache_clear()
    reset_engine()
    reset_schema_guard_cache()


def _snapshot_runtime_env() -> dict[str, str | None]:
    return {key: os.environ.get(key) for key in ENV_KEYS}


def _restore_runtime_env(snapshot: dict[str, str | None]) -> None:
    for key, value in snapshot.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _set_runtime_env(target_url: URL) -> None:
    os.environ["APP_API_KEY"] = "test-api-key"
    os.environ["APP_SECRET_KEY"] = "7J2Btjj4GW8jIP5MErM81QOZeK4c7xYknVxKsgKMnmk="
    os.environ["DATABASE_URL"] = target_url.render_as_string(hide_password=False)
    os.environ["DISABLE_SCHEDULER"] = "true"
    os.environ["SCHEMA_GUARD_ENABLED"] = "true"
    _reset_runtime_state()


def test_schema_guard_returns_503_for_stale_revision(test_database_url: str) -> None:
    target_url, admin_url, db_name = _build_temp_db_urls(test_database_url)
    _create_database(admin_url, db_name)
    runtime_env = _snapshot_runtime_env()

    try:
        engine = create_engine(target_url, future=True)
        try:
            with engine.begin() as conn:
                conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(64) NOT NULL)"))
                conn.execute(text("INSERT INTO alembic_version (version_num) VALUES ('0000_stale_revision')"))
        finally:
            engine.dispose()

        _set_runtime_env(target_url)
        app = create_app()
        with TestClient(app) as client:
            response = client.get("/v1/inputs", headers={"X-API-Key": "test-api-key"})

        assert response.status_code == 503
        assert "Database schema is not ready" in response.json()["detail"]
    finally:
        _restore_runtime_env(runtime_env)
        _reset_runtime_state()
        _drop_database(admin_url, db_name)


def test_schema_error_handler_returns_503_for_runtime_schema_errors(test_database_url: str) -> None:
    alembic_cfg = Config("alembic.ini")
    script = ScriptDirectory.from_config(alembic_cfg)
    head_revision = script.get_current_head()
    assert head_revision is not None

    target_url, admin_url, db_name = _build_temp_db_urls(test_database_url)
    _create_database(admin_url, db_name)
    runtime_env = _snapshot_runtime_env()

    try:
        engine = create_engine(target_url, future=True)
        try:
            with engine.begin() as conn:
                conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(64) NOT NULL)"))
                conn.execute(text("INSERT INTO alembic_version (version_num) VALUES (:revision)"), {"revision": head_revision})
        finally:
            engine.dispose()

        _set_runtime_env(target_url)
        app = create_app()
        with TestClient(app) as client:
            response = client.get("/v1/inputs", headers={"X-API-Key": "test-api-key"})

        assert response.status_code == 503
        assert "Database schema is not ready" in response.json()["detail"]
    finally:
        _restore_runtime_env(runtime_env)
        _reset_runtime_state()
        _drop_database(admin_url, db_name)
