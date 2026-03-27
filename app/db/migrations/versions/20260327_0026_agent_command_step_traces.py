"""add agent command step traces

Revision ID: 20260327_0026
Revises: 20260327_0025
Create Date: 2026-03-27 10:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260327_0026"
down_revision = "20260327_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "agent_command_step_traces" not in existing_tables:
        op.create_table(
            "agent_command_step_traces",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("eval_run_id", sa.String(length=64), nullable=False),
            sa.Column("operation_id", sa.String(length=64), nullable=False),
            sa.Column("command_id", sa.String(length=64), sa.ForeignKey("agent_command_runs.command_id", ondelete="SET NULL"), nullable=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("step_id", sa.String(length=64), nullable=False),
            sa.Column("tool_name", sa.String(length=128), nullable=True),
            sa.Column("scope_kind", sa.String(length=16), nullable=True),
            sa.Column("execution_boundary", sa.String(length=32), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("payload_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index(
            "ix_agent_command_step_traces_eval_created",
            "agent_command_step_traces",
            ["eval_run_id", "created_at"],
        )
        op.create_index(
            "ix_agent_command_step_traces_command_step",
            "agent_command_step_traces",
            ["command_id", "step_id"],
        )
        op.create_index(
            "ix_agent_command_step_traces_user_created",
            "agent_command_step_traces",
            ["user_id", "created_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())
    if "agent_command_step_traces" in existing_tables:
        op.drop_index("ix_agent_command_step_traces_user_created", table_name="agent_command_step_traces")
        op.drop_index("ix_agent_command_step_traces_command_step", table_name="agent_command_step_traces")
        op.drop_index("ix_agent_command_step_traces_eval_created", table_name="agent_command_step_traces")
        op.drop_table("agent_command_step_traces")
