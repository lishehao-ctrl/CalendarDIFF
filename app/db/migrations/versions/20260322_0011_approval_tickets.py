"""add approval tickets table

Revision ID: 20260322_0011_approval_tickets
Revises: 20260322_0010_agent_proposals
Create Date: 2026-03-22 23:50:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = "20260322_0011_approval_tickets"
down_revision = "20260322_0010_agent_proposals"
branch_labels = None
depends_on = None


APPROVAL_TICKET_STATUS_ENUM = sa.Enum(
    "open",
    "executed",
    "canceled",
    "expired",
    "failed",
    name="approval_ticket_status",
    native_enum=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "approval_tickets" not in existing_tables:
        op.create_table(
            "approval_tickets",
            sa.Column("ticket_id", sa.String(length=64), primary_key=True),
            sa.Column("proposal_id", sa.BigInteger(), sa.ForeignKey("agent_proposals.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("channel", sa.String(length=32), nullable=False, server_default="web"),
            sa.Column("action_type", sa.String(length=64), nullable=False),
            sa.Column("target_kind", sa.String(length=64), nullable=False),
            sa.Column("target_id", sa.String(length=255), nullable=False),
            sa.Column("payload_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("payload_hash", sa.String(length=128), nullable=False),
            sa.Column("target_snapshot_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("risk_level", sa.String(length=16), nullable=False),
            sa.Column("status", APPROVAL_TICKET_STATUS_ENUM, nullable=False, server_default="open"),
            sa.Column("executed_result_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_approval_tickets_user_created", "approval_tickets", ["user_id", "created_at"])
        op.create_index("ix_approval_tickets_proposal_status", "approval_tickets", ["proposal_id", "status"])
        op.create_index("ix_approval_tickets_status_expires", "approval_tickets", ["status", "expires_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())
    if "approval_tickets" in existing_tables:
        op.drop_index("ix_approval_tickets_status_expires", table_name="approval_tickets")
        op.drop_index("ix_approval_tickets_proposal_status", table_name="approval_tickets")
        op.drop_index("ix_approval_tickets_user_created", table_name="approval_tickets")
        op.drop_table("approval_tickets")
    bind.execute(text("DROP TYPE IF EXISTS approval_ticket_status"))
