"""extend channel deliveries for dispatcher flow

Revision ID: 20260324_0015_chan_dispatch
Revises: 20260324_0014_channels
Create Date: 2026-03-24 07:15:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260324_0015_chan_dispatch"
down_revision = "20260324_0014_channels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("channel_deliveries")}

    if "ack_payload_json" not in columns:
        op.add_column("channel_deliveries", sa.Column("ack_payload_json", sa.JSON(), nullable=False, server_default="{}"))
    if "attempt_count" not in columns:
        op.add_column("channel_deliveries", sa.Column("attempt_count", sa.BigInteger(), nullable=False, server_default="0"))
    if "lease_owner" not in columns:
        op.add_column("channel_deliveries", sa.Column("lease_owner", sa.String(length=128), nullable=True))
    if "lease_token" not in columns:
        op.add_column("channel_deliveries", sa.Column("lease_token", sa.String(length=64), nullable=True))
    if "lease_expires_at" not in columns:
        op.add_column("channel_deliveries", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    if "external_message_id" not in columns:
        op.add_column("channel_deliveries", sa.Column("external_message_id", sa.String(length=255), nullable=True))
    if "callback_token_hash" not in columns:
        op.add_column("channel_deliveries", sa.Column("callback_token_hash", sa.String(length=128), nullable=True))
    if "callback_expires_at" not in columns:
        op.add_column("channel_deliveries", sa.Column("callback_expires_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("channel_deliveries")}

    if "callback_expires_at" in columns:
        op.drop_column("channel_deliveries", "callback_expires_at")
    if "callback_token_hash" in columns:
        op.drop_column("channel_deliveries", "callback_token_hash")
    if "external_message_id" in columns:
        op.drop_column("channel_deliveries", "external_message_id")
    if "lease_expires_at" in columns:
        op.drop_column("channel_deliveries", "lease_expires_at")
    if "lease_token" in columns:
        op.drop_column("channel_deliveries", "lease_token")
    if "lease_owner" in columns:
        op.drop_column("channel_deliveries", "lease_owner")
    if "attempt_count" in columns:
        op.drop_column("channel_deliveries", "attempt_count")
    if "ack_payload_json" in columns:
        op.drop_column("channel_deliveries", "ack_payload_json")
