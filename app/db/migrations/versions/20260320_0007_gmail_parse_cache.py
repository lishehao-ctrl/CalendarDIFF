"""add gmail message parse cache

Revision ID: 20260320_0007_gmail_parse_cache
Revises: 20260319_0006_sync_stage
Create Date: 2026-03-20 16:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = "20260320_0007_gmail_parse_cache"
down_revision = "20260319_0006_sync_stage"
branch_labels = None
depends_on = None


GMAIL_PARSE_CACHE_STATUS_ENUM = sa.Enum(
    "PARSED",
    "EMPTY",
    "NON_RETRYABLE_SKIP",
    name="gmail_message_parse_cache_status",
    native_enum=False,
)
CALENDAR_PARSE_CACHE_STATUS_ENUM = sa.Enum(
    "PARSED",
    "EMPTY",
    "NON_RETRYABLE_SKIP",
    name="calendar_component_parse_cache_status",
    native_enum=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "gmail_message_parse_cache" in inspector.get_table_names():
        return

    op.create_table(
        "gmail_message_parse_cache",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("source_id", sa.BigInteger(), sa.ForeignKey("input_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("message_id", sa.String(length=255), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("status", GMAIL_PARSE_CACHE_STATUS_ENUM, nullable=False),
        sa.Column("records_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("hit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("source_id", "message_id", "content_hash", name="uq_gmail_message_parse_cache_source_message_hash"),
    )
    op.create_index(
        "ix_gmail_message_parse_cache_source_message",
        "gmail_message_parse_cache",
        ["source_id", "message_id"],
    )
    op.create_index(
        "ix_gmail_message_parse_cache_source_updated",
        "gmail_message_parse_cache",
        ["source_id", "updated_at"],
    )
    op.create_table(
        "calendar_component_parse_cache",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("source_id", sa.BigInteger(), sa.ForeignKey("input_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("fingerprint", sa.String(length=128), nullable=False),
        sa.Column("status", CALENDAR_PARSE_CACHE_STATUS_ENUM, nullable=False),
        sa.Column("records_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("hit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("source_id", "fingerprint", name="uq_calendar_component_parse_cache_source_fingerprint"),
    )
    op.create_index(
        "ix_calendar_component_parse_cache_source_fingerprint",
        "calendar_component_parse_cache",
        ["source_id", "fingerprint"],
    )
    op.create_index(
        "ix_calendar_component_parse_cache_source_updated",
        "calendar_component_parse_cache",
        ["source_id", "updated_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "gmail_message_parse_cache" in inspector.get_table_names():
        op.drop_index("ix_gmail_message_parse_cache_source_updated", table_name="gmail_message_parse_cache")
        op.drop_index("ix_gmail_message_parse_cache_source_message", table_name="gmail_message_parse_cache")
        op.drop_table("gmail_message_parse_cache")
    if "calendar_component_parse_cache" in inspector.get_table_names():
        op.drop_index("ix_calendar_component_parse_cache_source_updated", table_name="calendar_component_parse_cache")
        op.drop_index("ix_calendar_component_parse_cache_source_fingerprint", table_name="calendar_component_parse_cache")
        op.drop_table("calendar_component_parse_cache")
    bind.execute(text("DROP TYPE IF EXISTS calendar_component_parse_cache_status"))
    bind.execute(text("DROP TYPE IF EXISTS gmail_message_parse_cache_status"))
