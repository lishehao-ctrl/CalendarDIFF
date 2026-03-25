"""add llm invocation protocol column

Revision ID: 20260324_0018
Revises: 20260324_0016_llm_inv_logs
Create Date: 2026-03-24 12:05:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = "20260324_0018"
down_revision = "20260324_0016_llm_inv_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "llm_invocation_logs" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("llm_invocation_logs")}
    if "protocol" not in columns:
        op.add_column(
            "llm_invocation_logs",
            sa.Column("protocol", sa.String(length=64), nullable=True),
        )
        legacy_protocol_column = "api" "_mode"
        if legacy_protocol_column in columns:
            op.execute(f"UPDATE llm_invocation_logs SET protocol = {legacy_protocol_column} WHERE protocol IS NULL")
        else:
            op.execute("UPDATE llm_invocation_logs SET protocol = 'responses' WHERE protocol IS NULL")
        op.alter_column("llm_invocation_logs", "protocol", nullable=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "llm_invocation_logs" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("llm_invocation_logs")}
    if "protocol" in columns:
        op.drop_column("llm_invocation_logs", "protocol")
