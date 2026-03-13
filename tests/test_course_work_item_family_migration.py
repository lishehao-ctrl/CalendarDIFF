from __future__ import annotations

import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.core.config import get_settings


def test_upgrade_head_creates_semantic_only_schema(test_database_url: str) -> None:
    previous_database_url = os.environ.get("DATABASE_URL")
    alembic_cfg = Config("alembic.ini")
    try:
        os.environ["DATABASE_URL"] = test_database_url
        get_settings.cache_clear()

        command.upgrade(alembic_cfg, "head")

        engine = create_engine(test_database_url, future=True)
        try:
            inspector = inspect(engine)
            tables = set(inspector.get_table_names())
            entity_columns = {column["name"] for column in inspector.get_columns("event_entities")}
            raw_type_indexes = {index["name"] for index in inspector.get_indexes("course_work_item_raw_types") if index.get("name")}

            assert "course_work_item_label_families" in tables
            assert "course_work_item_raw_types" in tables
            assert "course_raw_type_suggestions" in tables
            assert "event_entities" in tables
            assert "events" not in tables
            assert {"family_id", "raw_type", "event_name", "due_date", "due_time", "time_precision", "course_dept", "course_number"}.issubset(entity_columns)
            assert {"course_display", "course_label", "title", "start_at_utc", "end_at_utc"}.isdisjoint(entity_columns)
            assert "ix_course_work_item_raw_types_family" in raw_type_indexes
        finally:
            engine.dispose()
    finally:
        get_settings.cache_clear()
        if previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database_url
        get_settings.cache_clear()


def test_migration_chain_is_flattened_to_single_current_baseline() -> None:
    versions_dir = Path("app/db/migrations/versions")
    revision_files = sorted(path.name for path in versions_dir.glob("*.py") if path.name != "__init__.py")
    assert revision_files == ["20260311_0001_semantic_core.py"]
