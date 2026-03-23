"""add mcp access tokens

Revision ID: 20260323_0012_mcp_access_tokens
Revises: 20260322_0011_approval_tickets
Create Date: 2026-03-23 01:20:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260323_0012_mcp_access_tokens"
down_revision = "20260322_0011_approval_tickets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "mcp_access_tokens" not in existing_tables:
        op.create_table(
            "mcp_access_tokens",
            sa.Column("token_id", sa.String(length=64), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("label", sa.String(length=128), nullable=False),
            sa.Column("token_hash", sa.String(length=128), nullable=False),
            sa.Column("scopes_json", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_mcp_access_tokens_user_created", "mcp_access_tokens", ["user_id", "created_at"])
        op.create_index("ix_mcp_access_tokens_token_id", "mcp_access_tokens", ["token_id"])
        op.create_index("ix_mcp_access_tokens_revoked", "mcp_access_tokens", ["revoked_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())
    if "mcp_access_tokens" in existing_tables:
        op.drop_index("ix_mcp_access_tokens_revoked", table_name="mcp_access_tokens")
        op.drop_index("ix_mcp_access_tokens_token_id", table_name="mcp_access_tokens")
        op.drop_index("ix_mcp_access_tokens_user_created", table_name="mcp_access_tokens")
        op.drop_table("mcp_access_tokens")
