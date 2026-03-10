from __future__ import annotations

import os

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.core.config import get_settings


def test_upgrade_from_kind_mappings_revision_creates_course_family_table(test_database_url: str) -> None:
    previous_database_url = os.environ.get("DATABASE_URL")
    alembic_cfg = Config("alembic.ini")
    try:
        os.environ["DATABASE_URL"] = test_database_url
        get_settings.cache_clear()

        command.downgrade(alembic_cfg, "20260309_0013_kind_mappings")

        engine = create_engine(test_database_url, future=True)
        try:
            inspector = inspect(engine)
            tables = set(inspector.get_table_names())
            assert "user_work_item_kind_mappings" in tables
            assert "course_work_item_label_families" not in tables
        finally:
            engine.dispose()

        get_settings.cache_clear()
        command.upgrade(alembic_cfg, "head")

        engine = create_engine(test_database_url, future=True)
        try:
            inspector = inspect(engine)
            tables = set(inspector.get_table_names())
            indexes = {index["name"] for index in inspector.get_indexes("course_work_item_label_families") if index.get("name")}
            assert "course_work_item_label_families" in tables
            assert "user_work_item_kind_mappings" not in tables
            assert "ix_course_work_item_families_user_course_updated" in indexes
        finally:
            engine.dispose()
    finally:
        get_settings.cache_clear()
        command.upgrade(alembic_cfg, "head")
        if previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database_url
        get_settings.cache_clear()
