"""add persisted user language preference

Revision ID: 20260322_0009_user_language
Revises: 20260320_0008_change_buckets
Create Date: 2026-03-22 13:10:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = "20260322_0009_user_language"
down_revision = "20260320_0008_change_buckets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "users" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("users")}
    if "language_code" not in existing_columns:
        op.add_column(
            "users",
            sa.Column("language_code", sa.String(length=16), nullable=False, server_default="en"),
        )
    bind.execute(text("UPDATE users SET language_code = COALESCE(NULLIF(language_code, ''), 'en')"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "users" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("users")}
    if "language_code" in existing_columns:
        op.drop_column("users", "language_code")
