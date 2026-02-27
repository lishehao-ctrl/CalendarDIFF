from __future__ import annotations

import os
import uuid

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import URL, make_url

from app.core.config import get_settings
from app.db.schema_guard import reset_schema_guard_cache
from app.db.session import reset_engine


ENV_KEYS = ("APP_API_KEY", "APP_SECRET_KEY", "DATABASE_URL", "DISABLE_SCHEDULER", "SCHEMA_GUARD_ENABLED")


def _build_temp_db_urls(base_url: str) -> tuple[URL, URL, str]:
    db_name = f"deadline_diff_mig_case_{uuid.uuid4().hex[:8]}"
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


def test_0011_deduplicates_ics_case_insensitively_and_uses_lower_predicate(test_database_url: str) -> None:
    target_url, admin_url, db_name = _build_temp_db_urls(test_database_url)
    _create_database(admin_url, db_name)
    runtime_env = _snapshot_runtime_env()

    try:
        _set_runtime_env(target_url)
        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, "0010_drop_review_candidates")

        engine = create_engine(target_url, future=True)
        try:
            with engine.begin() as conn:
                conn.execute(text("INSERT INTO users (id, email) VALUES (1, 'student@example.com')"))
                conn.execute(
                    text(
                        """
                        INSERT INTO inputs (
                            user_id, type, identity_key, encrypted_url, interval_minutes, is_active, created_at
                        )
                        VALUES
                            (1, 'ics', 'ics-old', 'encrypted://ics-old', 15, TRUE, now() - interval '5 minutes'),
                            (1, 'ICS', 'ics-new', 'encrypted://ics-new', 15, TRUE, now())
                        """
                    )
                )

            command.upgrade(alembic_cfg, "0011_single_ics_per_user")

            with engine.connect() as conn:
                rows = conn.execute(
                    text(
                        """
                        SELECT identity_key
                        FROM inputs
                        WHERE user_id = 1 AND lower(type) = 'ics'
                        ORDER BY created_at DESC, id DESC
                        """
                    )
                ).all()
                assert len(rows) == 1
                assert rows[0][0] == "ics-new"

                index_def = conn.execute(
                    text(
                        """
                        SELECT indexdef
                        FROM pg_indexes
                        WHERE schemaname = 'public'
                          AND tablename = 'inputs'
                          AND indexname = 'ux_inputs_user_single_ics'
                        """
                    )
                ).scalar_one()
                lowered = index_def.lower()
                assert "lower" in lowered
                assert "ics" in lowered
        finally:
            engine.dispose()
    finally:
        _restore_runtime_env(runtime_env)
        _reset_runtime_state()
        _drop_database(admin_url, db_name)


def test_0012_backfill_counts_lowercase_ics_without_clearing_onboarding(test_database_url: str) -> None:
    target_url, admin_url, db_name = _build_temp_db_urls(test_database_url)
    _create_database(admin_url, db_name)
    runtime_env = _snapshot_runtime_env()

    try:
        _set_runtime_env(target_url)
        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, "0011_single_ics_per_user")

        engine = create_engine(target_url, future=True)
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO users (id, email, onboarding_completed_at)
                        VALUES (1, 'student@example.com', now())
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO inputs (
                            user_id, type, identity_key, encrypted_url, interval_minutes, is_active, created_at
                        )
                        VALUES (1, 'ics', 'ics-ready', 'encrypted://ics-ready', 15, TRUE, now())
                        """
                    )
                )

            command.upgrade(alembic_cfg, "0012_ready_requires_single_ics")

            with engine.connect() as conn:
                onboarding_completed_at = conn.execute(
                    text("SELECT onboarding_completed_at FROM users WHERE id = 1")
                ).scalar_one()
                assert onboarding_completed_at is not None
        finally:
            engine.dispose()
    finally:
        _restore_runtime_env(runtime_env)
        _reset_runtime_state()
        _drop_database(admin_url, db_name)


def test_0014_accepts_lowercase_core_change_types_and_archives_legacy_rows(test_database_url: str) -> None:
    target_url, admin_url, db_name = _build_temp_db_urls(test_database_url)
    _create_database(admin_url, db_name)
    runtime_env = _snapshot_runtime_env()

    try:
        _set_runtime_env(target_url)
        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, "0013_core_runtime_ddl_alert")

        engine = create_engine(target_url, future=True)
        try:
            with engine.begin() as conn:
                conn.execute(text("INSERT INTO users (id, email) VALUES (1, 'student@example.com')"))
                conn.execute(
                    text(
                        """
                        INSERT INTO inputs (
                            id, user_id, type, identity_key, encrypted_url, interval_minutes, is_active, created_at
                        )
                        VALUES (1, 1, 'ics', 'ics-main', 'encrypted://ics-main', 15, TRUE, now())
                        """
                    )
                )
                snapshot_id = conn.execute(
                    text(
                        """
                        INSERT INTO snapshots (input_id, content_hash, event_count)
                        VALUES (1, 'snapshot-hash', 0)
                        RETURNING id
                        """
                    )
                ).scalar_one()

                conn.execute(
                    text(
                        """
                        INSERT INTO changes (input_id, event_uid, change_type, after_snapshot_id, detected_at)
                        VALUES
                            (1, 'event-created', 'created', :snapshot_id, now()),
                            (1, 'event-removed', 'removed', :snapshot_id, now()),
                            (1, 'event-due', 'due_changed', :snapshot_id, now()),
                            (1, 'event-legacy', 'title_changed', :snapshot_id, now())
                        """
                    ),
                    {"snapshot_id": snapshot_id},
                )

            command.upgrade(alembic_cfg, "0014_archive_legacy_change_types")

            with engine.begin() as conn:
                remaining_types = {
                    row[0]
                    for row in conn.execute(
                        text("SELECT lower(change_type) FROM changes WHERE event_uid <> 'event-legacy'")
                    ).all()
                }
                assert remaining_types == {"created", "removed", "due_changed"}

                legacy_archive_count = conn.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM changes_legacy_archive
                        WHERE event_uid = 'event-legacy'
                          AND lower(change_type) = 'title_changed'
                        """
                    )
                ).scalar_one()
                assert legacy_archive_count == 1

                legacy_remaining_count = conn.execute(
                    text("SELECT COUNT(*) FROM changes WHERE event_uid = 'event-legacy'")
                ).scalar_one()
                assert legacy_remaining_count == 0

                conn.execute(
                    text(
                        """
                        INSERT INTO changes (input_id, event_uid, change_type, after_snapshot_id, detected_at)
                        VALUES
                            (1, 'event-created-lower', 'created', :snapshot_id, now()),
                            (1, 'event-created-upper', 'CREATED', :snapshot_id, now())
                        """
                    ),
                    {"snapshot_id": snapshot_id},
                )
        finally:
            engine.dispose()
    finally:
        _restore_runtime_env(runtime_env)
        _reset_runtime_state()
        _drop_database(admin_url, db_name)
