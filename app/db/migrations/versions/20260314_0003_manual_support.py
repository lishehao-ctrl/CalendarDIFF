"""add manual support marker to event entities

Revision ID: 20260314_0003_manual_support
Revises: 20260313_0002_calendar_fanout
Create Date: 2026-03-14 17:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260314_0003_manual_support"
down_revision = "20260313_0002_calendar_fanout"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "event_entities" not in inspector.get_table_names():
        return
    existing_columns = {column["name"] for column in inspector.get_columns("event_entities")}
    if "manual_support" in existing_columns:
        return
    op.add_column(
        "event_entities",
        sa.Column("manual_support", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "event_entities" not in inspector.get_table_names():
        return
    existing_columns = {column["name"] for column in inspector.get_columns("event_entities")}
    if "manual_support" not in existing_columns:
        return
    op.drop_column("event_entities", "manual_support")
