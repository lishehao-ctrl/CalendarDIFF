"""add agent proposal localization params

Revision ID: 20260325_0018_agent_lang
Revises: 20260325_0022
Create Date: 2026-03-25 10:20:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260325_0018_agent_lang"
down_revision = "20260325_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "agent_proposals" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("agent_proposals")}
    if "summary_params_json" not in columns:
        op.add_column(
            "agent_proposals",
            sa.Column("summary_params_json", sa.JSON(), nullable=False, server_default="{}"),
        )
    if "reason_params_json" not in columns:
        op.add_column(
            "agent_proposals",
            sa.Column("reason_params_json", sa.JSON(), nullable=False, server_default="{}"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "agent_proposals" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("agent_proposals")}
    if "reason_params_json" in columns:
        op.drop_column("agent_proposals", "reason_params_json")
    if "summary_params_json" in columns:
        op.drop_column("agent_proposals", "summary_params_json")
