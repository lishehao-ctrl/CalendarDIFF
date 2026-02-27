from __future__ import annotations

import os
import uuid

from alembic import command
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
    db_name = f"deadline_diff_mig_{uuid.uuid4().hex[:8]}"
    target_url = make_url(base_url).set(database=db_name)
    admin_url = target_url.set(database="postgres")
    return target_url, admin_url, db_name


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


def _set_runtime_env(target_url: URL) -> None:
    os.environ["APP_API_KEY"] = "test-api-key"
    os.environ["APP_SECRET_KEY"] = "7J2Btjj4GW8jIP5MErM81QOZeK4c7xYknVxKsgKMnmk="
    os.environ["DATABASE_URL"] = target_url.render_as_string(hide_password=False)
    os.environ["DISABLE_SCHEDULER"] = "true"
    os.environ["SCHEMA_GUARD_ENABLED"] = "true"
    _reset_runtime_state()


def test_postgres_alembic_upgrade_head_bootstraps_runtime_schema(test_database_url: str) -> None:
    target_url, admin_url, db_name = _build_temp_db_urls(test_database_url)
    _create_database(admin_url, db_name)
    runtime_env = _snapshot_runtime_env()

    try:
        _set_runtime_env(target_url)
        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, "head")

        script = ScriptDirectory.from_config(alembic_cfg)
        expected_head = script.get_current_head()
        assert expected_head is not None

        engine = create_engine(target_url, future=True)
        try:
            with engine.connect() as conn:
                tables = set(
                    conn.execute(
                        text(
                            """
                            SELECT tablename
                            FROM pg_tables
                            WHERE schemaname = 'public'
                            """
                        )
                    ).scalars()
                )
                indexes = set(
                    conn.execute(
                        text(
                            """
                            SELECT indexname
                            FROM pg_indexes
                            WHERE schemaname = 'public'
                            """
                        )
                    ).scalars()
                )
                revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()

            assert revision == expected_head

            # Core runtime tables.
            assert {
                "users",
                "inputs",
                "events",
                "snapshots",
                "snapshot_events",
                "changes",
                "sync_runs",
                "notifications",
                "digest_send_log",
                "email_messages",
                "email_rule_labels",
                "email_action_items",
                "email_rule_analysis",
                "email_routes",
            }.issubset(tables)

            # Legacy tables are not part of baseline schema.
            assert "email_rule_candidates" not in tables
            assert "changes_legacy_archive" not in tables
            assert "profiles" not in tables
            assert "profile_terms" not in tables
            assert "user_notification_prefs" not in tables
            assert "course_overrides" not in tables
            assert "task_overrides" not in tables

            # Critical indexes and constraints.
            assert "ix_inputs_due_lookup" in indexes
            assert "ux_inputs_user_single_ics" in indexes
            assert "ix_sync_runs_input_started_desc" in indexes
            assert "ix_notifications_status_deliver_after" in indexes
            assert "ix_email_messages_user_received_at_desc" in indexes
            assert "ix_email_routes_route_routed_at_desc" in indexes
        finally:
            engine.dispose()
    finally:
        _restore_runtime_env(runtime_env)
        _reset_runtime_state()
        _drop_database(admin_url, db_name)


def test_source_api_works_after_postgres_migration(test_database_url: str) -> None:
    target_url, admin_url, db_name = _build_temp_db_urls(test_database_url)
    _create_database(admin_url, db_name)
    runtime_env = _snapshot_runtime_env()

    try:
        _set_runtime_env(target_url)
        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, "head")
        engine = create_engine(target_url, future=True)

        app = create_app()
        with TestClient(app) as client:
            headers = {"X-API-Key": "test-api-key"}
            with engine.begin() as conn:
                user_id = conn.execute(
                    text(
                        """
                        INSERT INTO users (email, notify_email, onboarding_completed_at)
                        VALUES (NULL, 'student@example.com', now())
                        RETURNING id
                        """
                    )
                ).scalar_one()
                conn.execute(
                    text(
                        """
                        INSERT INTO inputs (user_id, type, identity_key, encrypted_url, interval_minutes, is_active)
                        VALUES (:user_id, 'ICS', 'ics-example', 'encrypted', 15, TRUE)
                        """
                    ),
                    {"user_id": user_id},
                )

            list_response = client.get("/v1/inputs", headers=headers)
            assert list_response.status_code == 200
            items = list_response.json()
            assert len(items) == 1
            assert items[0]["display_label"].startswith("Calendar")
        engine.dispose()
    finally:
        _restore_runtime_env(runtime_env)
        _reset_runtime_state()
        _drop_database(admin_url, db_name)
