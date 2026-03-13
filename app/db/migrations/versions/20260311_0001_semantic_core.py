"""semantic-only fresh baseline

Revision ID: 20260311_0001_semantic_core
Revises:
Create Date: 2026-03-11 12:00:00
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect, text

from app.db.base import Base
from app.db.model_registry import load_all_models

revision = "20260311_0001_semantic_core"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    load_all_models()
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    load_all_models()
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())
    target_tables = [table for table in Base.metadata.sorted_tables if table.name in existing_tables]
    for table in reversed(target_tables):
        table.drop(bind=bind, checkfirst=True)
    bind.execute(text("DROP TABLE IF EXISTS alembic_version"))
