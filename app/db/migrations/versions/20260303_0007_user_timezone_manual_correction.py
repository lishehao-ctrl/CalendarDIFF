"""add user timezone for manual correction runtime

Revision ID: 20260303_0007_user_timezone
Revises: 20260303_0006_hard_cut_cleanup
Create Date: 2026-03-03 02:40:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260303_0007_user_timezone"
down_revision = "20260303_0006_hard_cut_cleanup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "users" not in set(inspector.get_table_names()):
        return

    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "timezone_name" not in user_columns:
        op.add_column(
            "users",
            sa.Column("timezone_name", sa.String(length=64), nullable=False, server_default="UTC"),
        )


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS timezone_name")
