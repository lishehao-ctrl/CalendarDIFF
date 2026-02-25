from __future__ import annotations

import os
import uuid

from alembic import command
from alembic.config import Config
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


def test_postgres_alembic_upgrade_head_bootstraps_current_schema(test_database_url: str) -> None:
    target_url, admin_url, db_name = _build_temp_db_urls(test_database_url)
    _create_database(admin_url, db_name)
    runtime_env = _snapshot_runtime_env()

    try:
        _set_runtime_env(target_url)
        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, "head")

        engine = create_engine(target_url, future=True)
        try:
            with engine.connect() as conn:
                inputs_cols = set(
                    conn.execute(
                        text(
                            """
                            SELECT column_name
                            FROM information_schema.columns
                            WHERE table_schema = 'public' AND table_name = 'inputs'
                            """
                        )
                    ).scalars()
                )
                users_cols = set(
                    conn.execute(
                        text(
                            """
                            SELECT column_name
                            FROM information_schema.columns
                            WHERE table_schema = 'public' AND table_name = 'users'
                            """
                        )
                    ).scalars()
                )
                notifications_cols = set(
                    conn.execute(
                        text(
                            """
                            SELECT column_name
                            FROM information_schema.columns
                            WHERE table_schema = 'public' AND table_name = 'notifications'
                            """
                        )
                    ).scalars()
                )
                changes_cols = set(
                    conn.execute(
                        text(
                            """
                            SELECT column_name
                            FROM information_schema.columns
                            WHERE table_schema = 'public' AND table_name = 'changes'
                            """
                        )
                    ).scalars()
                )
                sync_runs_cols = set(
                    conn.execute(
                        text(
                            """
                            SELECT column_name
                            FROM information_schema.columns
                            WHERE table_schema = 'public' AND table_name = 'sync_runs'
                            """
                        )
                    ).scalars()
                )
                input_indexes = set(
                    conn.execute(
                        text(
                            """
                            SELECT indexname
                            FROM pg_indexes
                            WHERE schemaname = 'public' AND tablename = 'inputs'
                            """
                        )
                    ).scalars()
                )
                changes_indexes = set(
                    conn.execute(
                        text(
                            """
                            SELECT indexname
                            FROM pg_indexes
                            WHERE schemaname = 'public' AND tablename = 'changes'
                            """
                        )
                    ).scalars()
                )
                sync_run_indexes = set(
                    conn.execute(
                        text(
                            """
                            SELECT indexname
                            FROM pg_indexes
                            WHERE schemaname = 'public' AND tablename = 'sync_runs'
                            """
                        )
                    ).scalars()
                )
                input_constraints = set(
                    conn.execute(
                        text(
                            """
                            SELECT constraint_name
                            FROM information_schema.table_constraints
                            WHERE table_schema = 'public'
                              AND table_name = 'inputs'
                              AND constraint_type = 'UNIQUE'
                            """
                        )
                    ).scalars()
                )
                notification_constraints = set(
                    conn.execute(
                        text(
                            """
                            SELECT constraint_name
                            FROM information_schema.table_constraints
                            WHERE table_schema = 'public'
                              AND table_name = 'notifications'
                              AND constraint_type = 'UNIQUE'
                            """
                        )
                    ).scalars()
                )
                input_check_defs = set(
                    conn.execute(
                        text(
                            """
                            SELECT pg_get_constraintdef(c.oid)
                            FROM pg_constraint c
                            JOIN pg_class t ON c.conrelid = t.oid
                            JOIN pg_namespace n ON n.oid = t.relnamespace
                            WHERE n.nspname = 'public'
                              AND t.relname = 'inputs'
                              AND c.contype = 'c'
                            """
                        )
                    ).scalars()
                )
                profiles_exists = conn.execute(text("SELECT to_regclass('public.profiles') IS NOT NULL")).scalar_one()
                profile_terms_exists = conn.execute(text("SELECT to_regclass('public.profile_terms') IS NOT NULL")).scalar_one()
                input_term_baselines_exists = conn.execute(
                    text("SELECT to_regclass('public.input_term_baselines') IS NOT NULL")
                ).scalar_one()
                email_rule_candidates_exists = conn.execute(
                    text("SELECT to_regclass('public.email_rule_candidates') IS NOT NULL")
                ).scalar_one()
                email_messages_exists = conn.execute(
                    text("SELECT to_regclass('public.email_messages') IS NOT NULL")
                ).scalar_one()
                email_rule_labels_exists = conn.execute(
                    text("SELECT to_regclass('public.email_rule_labels') IS NOT NULL")
                ).scalar_one()
                email_action_items_exists = conn.execute(
                    text("SELECT to_regclass('public.email_action_items') IS NOT NULL")
                ).scalar_one()
                email_rule_analysis_exists = conn.execute(
                    text("SELECT to_regclass('public.email_rule_analysis') IS NOT NULL")
                ).scalar_one()
                email_routes_exists = conn.execute(
                    text("SELECT to_regclass('public.email_routes') IS NOT NULL")
                ).scalar_one()
                email_routes_indexes = set(
                    conn.execute(
                        text(
                            """
                            SELECT indexname
                            FROM pg_indexes
                            WHERE schemaname = 'public' AND tablename = 'email_routes'
                            """
                        )
                    ).scalars()
                )
                email_rule_labels_indexes = set(
                    conn.execute(
                        text(
                            """
                            SELECT indexname
                            FROM pg_indexes
                            WHERE schemaname = 'public' AND tablename = 'email_rule_labels'
                            """
                        )
                    ).scalars()
                )
                email_messages_indexes = set(
                    conn.execute(
                        text(
                            """
                            SELECT indexname
                            FROM pg_indexes
                            WHERE schemaname = 'public' AND tablename = 'email_messages'
                            """
                        )
                    ).scalars()
                )
                revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        finally:
            engine.dispose()

        assert "notify_email" in inputs_cols
        assert "onboarding_completed_at" in users_cols
        assert "identity_key" in inputs_cols
        assert "term_id" not in inputs_cols
        assert "user_term_id" not in inputs_cols
        assert "profile_id" not in inputs_cols
        assert "name" not in inputs_cols
        assert "normalized_name" not in inputs_cols
        assert "etag" in inputs_cols
        assert "last_modified" in inputs_cols
        assert "last_content_hash" in inputs_cols
        assert "last_ok_at" in inputs_cols
        assert "last_change_detected_at" in inputs_cols
        assert "last_error_at" in inputs_cols
        assert "last_email_sent_at" in inputs_cols
        assert "provider" in inputs_cols
        assert "gmail_label" in inputs_cols
        assert "gmail_from_contains" in inputs_cols
        assert "gmail_subject_keywords" in inputs_cols
        assert "gmail_history_id" in inputs_cols
        assert "gmail_account_email" in inputs_cols
        assert "encrypted_access_token" in inputs_cols
        assert "encrypted_refresh_token" in inputs_cols
        assert "access_token_expires_at" in inputs_cols
        assert "idempotency_key" in notifications_cols
        assert "deliver_after" in notifications_cols
        assert "enqueue_reason" in notifications_cols
        assert "notified_at" in notifications_cols
        assert "user_term_id" not in changes_cols
        assert "status" in sync_runs_cols
        assert "changes_count" in sync_runs_cols
        assert "error_code" in sync_runs_cols
        assert "error_message" in sync_runs_cols
        assert "ix_inputs_due_lookup" in input_indexes
        assert "ix_inputs_user_term_id" not in input_indexes
        assert "ix_changes_user_term_id" not in changes_indexes
        assert "ix_sync_runs_input_started_desc" in sync_run_indexes
        assert "ix_sync_runs_started_at" in sync_run_indexes
        assert "ix_sync_runs_status_started_at" in sync_run_indexes
        assert "uq_inputs_user_type_identity_key" in input_constraints
        assert any("interval_minutes" in definition and "= 15" in definition for definition in input_check_defs)
        assert profiles_exists is False
        assert profile_terms_exists is False
        assert input_term_baselines_exists is False
        assert email_rule_candidates_exists is False
        assert email_messages_exists is True
        assert email_rule_labels_exists is True
        assert email_action_items_exists is True
        assert email_rule_analysis_exists is True
        assert email_routes_exists is True
        assert "ix_email_routes_route_routed_at_desc" in email_routes_indexes
        assert "ix_email_rule_labels_event_type" in email_rule_labels_indexes
        assert "ix_email_messages_user_received_at_desc" in email_messages_indexes
        assert "uq_notifications_idempotency_key" in notification_constraints
        assert "uq_notifications_change_channel" in notification_constraints
        assert revision == "0010_drop_review_candidates"
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
                conn.execute(
                    text(
                        """
                        INSERT INTO users (email, notify_email, onboarding_completed_at)
                        VALUES (NULL, 'student@example.com', now())
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO inputs (user_id, type, identity_key, encrypted_url, interval_minutes, is_active)
                        VALUES (1, 'ICS', 'ics-example', 'encrypted', 15, TRUE)
                        """
                    )
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
