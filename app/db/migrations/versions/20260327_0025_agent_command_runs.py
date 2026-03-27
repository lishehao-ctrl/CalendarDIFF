"""add agent command runs

Revision ID: 20260327_0025
Revises: 20260326_0024
Create Date: 2026-03-27 03:40:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = "20260327_0025"
down_revision = "20260326_0024"
branch_labels = None
depends_on = None


AGENT_COMMAND_RUN_STATUS_ENUM = sa.Enum(
    "planned",
    "clarification_required",
    "unsupported",
    "executing",
    "completed",
    "failed",
    name="agent_command_run_status",
    native_enum=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "agent_command_runs" not in existing_tables:
        AGENT_COMMAND_RUN_STATUS_ENUM.create(bind, checkfirst=True)
        op.create_table(
            "agent_command_runs",
            sa.Column("command_id", sa.String(length=64), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("input_text", sa.Text(), nullable=False),
            sa.Column("scope_kind", sa.String(length=16), nullable=False, server_default="workspace"),
            sa.Column("scope_id", sa.String(length=255), nullable=True),
            sa.Column("language_code", sa.String(length=16), nullable=False, server_default="en"),
            sa.Column("language_resolution_source", sa.String(length=32), nullable=False, server_default="default"),
            sa.Column("status", AGENT_COMMAND_RUN_STATUS_ENUM, nullable=False, server_default="planned"),
            sa.Column("status_reason", sa.Text(), nullable=True),
            sa.Column("plan_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("execution_results_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_agent_command_runs_user_created", "agent_command_runs", ["user_id", "created_at"])
        op.create_index(
            "ix_agent_command_runs_user_status_updated",
            "agent_command_runs",
            ["user_id", "status", "updated_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())
    if "agent_command_runs" in existing_tables:
        op.drop_index("ix_agent_command_runs_user_status_updated", table_name="agent_command_runs")
        op.drop_index("ix_agent_command_runs_user_created", table_name="agent_command_runs")
        op.drop_table("agent_command_runs")
    bind.execute(text("DROP TYPE IF EXISTS agent_command_run_status"))
