from __future__ import annotations

import os
from collections.abc import Generator
from datetime import datetime, timezone

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.models.shared import User
from app.db.session import reset_engine
from app.modules.auth.service import AUTH_SESSION_COOKIE_NAME, create_user_session
from app.modules.common.request_rate_limit import reset_request_rate_limiters
from app.modules.sources.schemas import InputSourceCreateRequest
from app.modules.sources.sources_service import create_input_source

DEFAULT_TEST_DATABASE_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/deadline_diff_test"
DEFAULT_TEST_REDIS_URL = "redis://127.0.0.1:6379/15"


def _live_smoke_mode() -> bool:
    return (os.getenv("RUN_SEMESTER_DEMO_SMOKE", "").strip().lower() in {"1", "true", "yes"} or os.getenv("RUN_REAL_SOURCE_SMOKE", "").strip().lower() in {"1", "true", "yes"})


def _recreate_postgres_database(database_url: str) -> None:
    parsed = make_url(database_url)
    if not parsed.drivername.startswith("postgresql"):
        return
    if not parsed.database:
        return

    db_name = parsed.database
    admin_dsn = parsed.set(drivername="postgresql", database="postgres").render_as_string(hide_password=False)
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        with conn.cursor() as cursor:
            cursor.execute(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)')
            cursor.execute(f'CREATE DATABASE "{db_name}"')


def _truncate_all_tables(engine: Engine) -> None:
    with engine.begin() as conn:
        table_names = conn.execute(
            text(
                """
                SELECT tablename
                FROM pg_tables
                WHERE schemaname = 'public'
                  AND tablename <> 'alembic_version'
                """
            )
        ).scalars().all()
        if not table_names:
            return
        quoted_tables = ", ".join(f'"{name}"' for name in table_names)
        conn.execute(text(f"TRUNCATE TABLE {quoted_tables} RESTART IDENTITY CASCADE"))


@pytest.fixture(scope="session")
def test_database_url() -> str:
    return os.getenv("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)


@pytest.fixture(scope="session", autouse=True)
def configure_test_environment(test_database_url: str) -> Generator[None, None, None]:
    if _live_smoke_mode():
        get_settings.cache_clear()
        reset_engine()
        yield
        get_settings.cache_clear()
        reset_engine()
        return

    os.environ["APP_API_KEY"] = "test-api-key"
    os.environ["APP_SECRET_KEY"] = "7J2Btjj4GW8jIP5MErM81QOZeK4c7xYknVxKsgKMnmk="
    os.environ["DEFAULT_EMAIL"] = "notify@example.com"
    os.environ["DATABASE_URL"] = test_database_url
    os.environ["SCHEMA_GUARD_ENABLED"] = "true"
    os.environ["INGEST_SERVICE_ENABLE_WORKER"] = "false"
    os.environ["REVIEW_SERVICE_ENABLE_APPLY_WORKER"] = "false"
    os.environ["NOTIFICATION_SERVICE_ENABLE_WORKER"] = "false"
    os.environ["LLM_SERVICE_ENABLE_WORKER"] = "false"
    os.environ["REDIS_URL"] = os.getenv("REDIS_URL", DEFAULT_TEST_REDIS_URL) or DEFAULT_TEST_REDIS_URL
    os.environ["BOOTSTRAP_ADMIN_EMAIL"] = ""
    os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = ""
    os.environ["BOOTSTRAP_ADMIN_TIMEZONE_NAME"] = "America/Los_Angeles"

    get_settings.cache_clear()
    reset_engine()
    yield
    get_settings.cache_clear()
    reset_engine()


@pytest.fixture(scope="session")
def db_engine(configure_test_environment: None, test_database_url: str) -> Generator[Engine, None, None]:
    _recreate_postgres_database(test_database_url)
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")

    engine = create_engine(test_database_url, future=True, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_database(request) -> Generator[None, None, None]:
    if _live_smoke_mode():
        yield
        return
    db_engine = request.getfixturevalue("db_engine")
    _truncate_all_tables(db_engine)
    reset_request_rate_limiters()
    yield
    reset_request_rate_limiters()


@pytest.fixture()
def db_session_factory(db_engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=db_engine, autoflush=False, autocommit=False, expire_on_commit=False)


@pytest.fixture()
def db_session(db_session_factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    session = db_session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(configure_test_environment: None) -> Generator[TestClient, None, None]:
    get_settings.cache_clear()
    reset_engine()
    from services.app_api.main import app as public_api_app

    with TestClient(public_api_app) as test_client:
        yield test_client
    get_settings.cache_clear()
    reset_engine()


@pytest.fixture()
def input_client(configure_test_environment: None) -> Generator[TestClient, None, None]:
    get_settings.cache_clear()
    reset_engine()
    from services.app_api.main import app as public_api_app

    with TestClient(public_api_app) as test_client:
        yield test_client
    get_settings.cache_clear()
    reset_engine()


@pytest.fixture()
def authenticate_client(db_session: Session):
    def _authenticate(test_client: TestClient, *, user: User) -> str:
        cookie_value = create_user_session(db_session, user=user)
        test_client.cookies.set(AUTH_SESSION_COOKIE_NAME, cookie_value)
        return cookie_value

    return _authenticate


@pytest.fixture()
def auth_headers(authenticate_client):
    def _auth_headers(test_client: TestClient, *, user: User) -> dict[str, str]:
        authenticate_client(test_client, user=user)
        return {"X-API-Key": "test-api-key"}

    return _auth_headers


@pytest.fixture()
def initialized_user(client: TestClient, db_session: Session) -> dict[str, object]:
    del client
    user = User(
        email="student@example.com",
        password_hash="hash",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.flush()
    create_input_source(
        db_session,
        user=user,
        payload=InputSourceCreateRequest(
            source_kind="calendar",
            provider="ics",
            source_key="initialized-user-calendar",
            display_name="Initialized User Calendar",
            config={"monitor_since": "2026-01-05"},
            secrets={"url": "https://example.com/initialized-user.ics"},
        ),
    )
    db_session.commit()
    db_session.refresh(user)
    return {
        "id": user.id,
        "email": user.email,
        "calendar_delay_seconds": user.calendar_delay_seconds,
        "created_at": user.created_at,
    }
