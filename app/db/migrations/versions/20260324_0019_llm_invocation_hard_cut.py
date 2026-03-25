"""drop legacy llm invocation compatibility columns

Revision ID: 20260324_0019
Revises: 20260324_0018
Create Date: 2026-03-24 16:40:00.000000
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect


revision = "20260324_0019"
down_revision = "20260324_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "llm_invocation_logs" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("llm_invocation_logs")}
    for column_name in ("api" "_mode", "route" "_count", "is" "_fallback"):
        if column_name in columns:
            op.drop_column("llm_invocation_logs", column_name)


def downgrade() -> None:
    return None
