"""add mcp invocation audit and request ids

Revision ID: 20260324_0017_mcp_audit
Revises: 20260324_0015_chan_dispatch
Create Date: 2026-03-24 08:10:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260324_0017_mcp_audit"
down_revision = "20260324_0015_chan_dispatch"
branch_labels = None
depends_on = None


MCP_TOOL_INVOCATION_STATUS_ENUM = sa.Enum(
    "started",
    "succeeded",
    "failed",
    name="mcp_tool_invocation_status",
    native_enum=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    proposal_columns = {column["name"] for column in inspector.get_columns("agent_proposals")}
    if "origin_request_id" not in proposal_columns:
        op.add_column("agent_proposals", sa.Column("origin_request_id", sa.String(length=64), nullable=True))

    ticket_columns = {column["name"] for column in inspector.get_columns("approval_tickets")}
    if "origin_request_id" not in ticket_columns:
        op.add_column("approval_tickets", sa.Column("origin_request_id", sa.String(length=64), nullable=True))

    if "mcp_tool_invocations" not in existing_tables:
        op.create_table(
            "mcp_tool_invocations",
            sa.Column("invocation_id", sa.String(length=64), primary_key=True),
            sa.Column("transport_request_id", sa.String(length=64), nullable=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("tool_name", sa.String(length=128), nullable=False),
            sa.Column("transport", sa.String(length=32), nullable=False),
            sa.Column("auth_mode", sa.String(length=32), nullable=False),
            sa.Column("status", MCP_TOOL_INVOCATION_STATUS_ENUM, nullable=False, server_default="started"),
            sa.Column("input_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("output_summary_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("error_text", sa.Text(), nullable=True),
            sa.Column("proposal_id", sa.BigInteger(), sa.ForeignKey("agent_proposals.id", ondelete="SET NULL"), nullable=True),
            sa.Column("ticket_id", sa.String(length=64), sa.ForeignKey("approval_tickets.ticket_id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_mcp_tool_invocations_user_created", "mcp_tool_invocations", ["user_id", "created_at"])
        op.create_index("ix_mcp_tool_invocations_tool_created", "mcp_tool_invocations", ["tool_name", "created_at"])
        op.create_index("ix_mcp_tool_invocations_status_created", "mcp_tool_invocations", ["status", "created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "mcp_tool_invocations" in existing_tables:
        op.drop_index("ix_mcp_tool_invocations_status_created", table_name="mcp_tool_invocations")
        op.drop_index("ix_mcp_tool_invocations_tool_created", table_name="mcp_tool_invocations")
        op.drop_index("ix_mcp_tool_invocations_user_created", table_name="mcp_tool_invocations")
        op.drop_table("mcp_tool_invocations")

    proposal_columns = {column["name"] for column in inspector.get_columns("agent_proposals")}
    if "origin_request_id" in proposal_columns:
        op.drop_column("agent_proposals", "origin_request_id")

    ticket_columns = {column["name"] for column in inspector.get_columns("approval_tickets")}
    if "origin_request_id" in ticket_columns:
        op.drop_column("approval_tickets", "origin_request_id")
