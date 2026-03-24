"""add social channel foundation tables

Revision ID: 20260324_0014_channels
Revises: 20260324_0013_agent_audit
Create Date: 2026-03-24 06:20:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260324_0014_channels"
down_revision = "20260324_0013_agent_audit"
branch_labels = None
depends_on = None


CHANNEL_ACCOUNT_TYPE_ENUM = sa.Enum("telegram", "slack", "wechat", "wecom", name="channel_account_type", native_enum=False)
CHANNEL_ACCOUNT_STATUS_ENUM = sa.Enum("active", "paused", "revoked", name="channel_account_status", native_enum=False)
CHANNEL_ACCOUNT_VERIFICATION_STATUS_ENUM = sa.Enum(
    "pending",
    "verified",
    "revoked",
    name="channel_account_verification_status",
    native_enum=False,
)
CHANNEL_DELIVERY_STATUS_ENUM = sa.Enum(
    "pending",
    "sent",
    "acknowledged",
    "failed",
    "canceled",
    name="channel_delivery_status",
    native_enum=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "channel_accounts" not in existing_tables:
        op.create_table(
            "channel_accounts",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("channel_type", CHANNEL_ACCOUNT_TYPE_ENUM, nullable=False),
            sa.Column("account_label", sa.String(length=128), nullable=False),
            sa.Column("external_user_id", sa.String(length=255), nullable=True),
            sa.Column("external_workspace_id", sa.String(length=255), nullable=True),
            sa.Column("status", CHANNEL_ACCOUNT_STATUS_ENUM, nullable=False, server_default="active"),
            sa.Column("verification_status", CHANNEL_ACCOUNT_VERIFICATION_STATUS_ENUM, nullable=False, server_default="pending"),
            sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_channel_accounts_user_created", "channel_accounts", ["user_id", "created_at"])
        op.create_index("ix_channel_accounts_user_type_status", "channel_accounts", ["user_id", "channel_type", "status"])

    if "channel_deliveries" not in existing_tables:
        op.create_table(
            "channel_deliveries",
            sa.Column("delivery_id", sa.String(length=64), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("channel_account_id", sa.BigInteger(), sa.ForeignKey("channel_accounts.id", ondelete="SET NULL"), nullable=True),
            sa.Column("proposal_id", sa.BigInteger(), sa.ForeignKey("agent_proposals.id", ondelete="SET NULL"), nullable=True),
            sa.Column("ticket_id", sa.String(length=64), sa.ForeignKey("approval_tickets.ticket_id", ondelete="SET NULL"), nullable=True),
            sa.Column("delivery_kind", sa.String(length=64), nullable=False),
            sa.Column("status", CHANNEL_DELIVERY_STATUS_ENUM, nullable=False, server_default="pending"),
            sa.Column("summary_code", sa.String(length=128), nullable=True),
            sa.Column("detail_code", sa.String(length=128), nullable=True),
            sa.Column("cta_code", sa.String(length=128), nullable=True),
            sa.Column("payload_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("origin_kind", sa.String(length=32), nullable=False, server_default="unknown"),
            sa.Column("origin_label", sa.String(length=64), nullable=False, server_default="unknown"),
            sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("error_text", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_channel_deliveries_user_created", "channel_deliveries", ["user_id", "created_at"])
        op.create_index("ix_channel_deliveries_account_status", "channel_deliveries", ["channel_account_id", "status"])
        op.create_index("ix_channel_deliveries_ticket_status", "channel_deliveries", ["ticket_id", "status"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "channel_deliveries" in existing_tables:
        op.drop_index("ix_channel_deliveries_ticket_status", table_name="channel_deliveries")
        op.drop_index("ix_channel_deliveries_account_status", table_name="channel_deliveries")
        op.drop_index("ix_channel_deliveries_user_created", table_name="channel_deliveries")
        op.drop_table("channel_deliveries")
    if "channel_accounts" in existing_tables:
        op.drop_index("ix_channel_accounts_user_type_status", table_name="channel_accounts")
        op.drop_index("ix_channel_accounts_user_created", table_name="channel_accounts")
        op.drop_table("channel_accounts")
