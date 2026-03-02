from __future__ import annotations

import os
from collections.abc import Generator

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.models import User
from app.db.session import reset_engine
from app.modules.input_control_plane.schemas import InputSourceCreateRequest
from app.modules.input_control_plane.service import create_input_source
from app.main import create_app
from datetime import datetime, timezone


DEFAULT_TEST_DATABASE_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/deadline_diff_test"


def _recreate_postgres_database(database_url: str) -> None:
    parsed = make_url(database_url)
    if not parsed.drivername.startswith("postgresql"):
        return
    if not parsed.database:
        return

    db_name = parsed.database
    admin_url = parsed.set(database="postgres")
    engine = create_engine(admin_url, future=True, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    finally:
        engine.dispose()


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
    os.environ["APP_API_KEY"] = "test-api-key"
    os.environ["APP_SECRET_KEY"] = "7J2Btjj4GW8jIP5MErM81QOZeK4c7xYknVxKsgKMnmk="
    os.environ["DEFAULT_NOTIFY_EMAIL"] = "notify@example.com"
    os.environ["DATABASE_URL"] = test_database_url
    os.environ["SCHEMA_GUARD_ENABLED"] = "true"

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
def clean_database(db_engine: Engine) -> Generator[None, None, None]:
    _truncate_all_tables(db_engine)
    yield


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
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()
    reset_engine()


@pytest.fixture()
def initialized_user(client: TestClient, db_session: Session) -> dict[str, object]:
    del client
    user = User(
        email=None,
        notify_email="student@example.com",
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
            config={},
            secrets={"url": "https://example.com/initialized-user.ics"},
        ),
    )
    db_session.commit()
    db_session.refresh(user)
    return {
        "id": user.id,
        "email": user.email,
        "notify_email": user.notify_email,
        "calendar_delay_seconds": user.calendar_delay_seconds,
        "created_at": user.created_at,
    }
