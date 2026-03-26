"""add gmail purpose-mode cache

Revision ID: 20260326_0024
Revises: 20260325_0023
Create Date: 2026-03-26 03:20:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260326_0024"
down_revision = "20260325_0023"
branch_labels = None
depends_on = None


GMAIL_MESSAGE_PURPOSE_CACHE_MODE_ENUM = sa.Enum(
    "unknown",
    "atomic",
    "directive",
    name="gmail_message_purpose_cache_mode",
    native_enum=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "gmail_message_purpose_cache" not in inspector.get_table_names():
        GMAIL_MESSAGE_PURPOSE_CACHE_MODE_ENUM.create(bind, checkfirst=True)
        op.create_table(
            "gmail_message_purpose_cache",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("source_id", sa.Integer(), sa.ForeignKey("input_sources.id", ondelete="CASCADE"), nullable=False),
            sa.Column("message_id", sa.String(length=255), nullable=False),
            sa.Column("content_hash", sa.String(length=64), nullable=False),
            sa.Column("classifier_version", sa.String(length=128), nullable=False),
            sa.Column("message_fingerprint", sa.String(length=64), nullable=False),
            sa.Column("mode", GMAIL_MESSAGE_PURPOSE_CACHE_MODE_ENUM, nullable=False),
            sa.Column("evidence", sa.Text(), nullable=True),
            sa.Column("reason_code", sa.String(length=64), nullable=True),
            sa.Column("decision_source", sa.String(length=32), nullable=False, server_default="llm"),
            sa.Column("provider_id", sa.String(length=64), nullable=True),
            sa.Column("model", sa.String(length=128), nullable=True),
            sa.Column("protocol", sa.String(length=64), nullable=True),
            sa.Column("hit_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint(
                "source_id",
                "message_id",
                "content_hash",
                "classifier_version",
                name="uq_gmail_message_purpose_cache_source_message_hash_version",
            ),
        )
        op.create_index(
            "ix_gmail_message_purpose_cache_source_hash",
            "gmail_message_purpose_cache",
            ["source_id", "content_hash", "classifier_version"],
        )
        op.create_index(
            "ix_gmail_message_purpose_cache_source_fingerprint",
            "gmail_message_purpose_cache",
            ["source_id", "message_fingerprint", "classifier_version", "mode"],
        )
        op.create_index(
            "ix_gmail_message_purpose_cache_source_updated",
            "gmail_message_purpose_cache",
            ["source_id", "updated_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "gmail_message_purpose_cache" in inspector.get_table_names():
        op.drop_index("ix_gmail_message_purpose_cache_source_updated", table_name="gmail_message_purpose_cache")
        op.drop_index("ix_gmail_message_purpose_cache_source_fingerprint", table_name="gmail_message_purpose_cache")
        op.drop_index("ix_gmail_message_purpose_cache_source_hash", table_name="gmail_message_purpose_cache")
        op.drop_table("gmail_message_purpose_cache")
    GMAIL_MESSAGE_PURPOSE_CACHE_MODE_ENUM.drop(bind, checkfirst=True)
