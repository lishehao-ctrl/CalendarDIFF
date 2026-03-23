"""add agent proposals table

Revision ID: 20260322_0010_agent_proposals
Revises: 20260322_0009_user_language
Create Date: 2026-03-22 23:10:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = "20260322_0010_agent_proposals"
down_revision = "20260322_0009_user_language"
branch_labels = None
depends_on = None


AGENT_PROPOSAL_TYPE_ENUM = sa.Enum(
    "change_decision",
    "source_recovery",
    name="agent_proposal_type",
    native_enum=False,
)
AGENT_PROPOSAL_STATUS_ENUM = sa.Enum(
    "open",
    "accepted",
    "rejected",
    "expired",
    "superseded",
    name="agent_proposal_status",
    native_enum=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "agent_proposals" not in existing_tables:
        op.create_table(
            "agent_proposals",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("proposal_type", AGENT_PROPOSAL_TYPE_ENUM, nullable=False),
            sa.Column("status", AGENT_PROPOSAL_STATUS_ENUM, nullable=False, server_default="open"),
            sa.Column("target_kind", sa.String(length=64), nullable=False),
            sa.Column("target_id", sa.String(length=255), nullable=False),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("summary_code", sa.String(length=128), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("reason_code", sa.String(length=128), nullable=False),
            sa.Column("risk_level", sa.String(length=16), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
            sa.Column("suggested_action", sa.String(length=64), nullable=False),
            sa.Column("payload_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("context_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("target_snapshot_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_agent_proposals_user_created", "agent_proposals", ["user_id", "created_at"])
        op.create_index("ix_agent_proposals_type_target", "agent_proposals", ["proposal_type", "target_kind", "target_id"])
        op.create_index("ix_agent_proposals_status_expires", "agent_proposals", ["status", "expires_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())
    if "agent_proposals" in existing_tables:
        op.drop_index("ix_agent_proposals_status_expires", table_name="agent_proposals")
        op.drop_index("ix_agent_proposals_type_target", table_name="agent_proposals")
        op.drop_index("ix_agent_proposals_user_created", table_name="agent_proposals")
        op.drop_table("agent_proposals")
    bind.execute(text("DROP TYPE IF EXISTS agent_proposal_status"))
    bind.execute(text("DROP TYPE IF EXISTS agent_proposal_type"))
