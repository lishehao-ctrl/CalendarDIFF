"""add deterministic email review queue tables

Revision ID: 0008_email_review_queue
Revises: 0007_email_rule_candidates
Create Date: 2026-02-26 15:40:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0008_email_review_queue"
down_revision = "0007_email_rule_candidates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_messages",
        sa.Column("email_id", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, server_default="1"),
        sa.Column("from_addr", sa.Text(), nullable=True),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("date_rfc822", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("evidence_key", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    op.create_table(
        "email_rule_labels",
        sa.Column("email_id", sa.Text(), sa.ForeignKey("email_messages.email_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("course_hints", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("event_type", sa.Text(), nullable=True),
        sa.Column(
            "raw_extract",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text(
                "jsonb_build_object('deadline_text', NULL, 'time_text', NULL, 'location_text', NULL)"
            ),
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.CheckConstraint("label IN ('KEEP', 'DROP')", name="ck_email_rule_labels_label"),
        sa.CheckConstraint(
            "event_type IS NULL OR event_type IN ('deadline','exam','schedule_change','assignment','grade','action_required','announcement','other')",
            name="ck_email_rule_labels_event_type",
        ),
    )

    op.create_table(
        "email_action_items",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("email_id", sa.Text(), sa.ForeignKey("email_messages.email_id", ondelete="CASCADE"), nullable=False),
        sa.Column("action", sa.Text(), nullable=True),
        sa.Column("due_iso", sa.Text(), nullable=True),
        sa.Column("where_text", sa.Text(), nullable=True),
    )

    op.create_table(
        "email_rule_analysis",
        sa.Column("email_id", sa.Text(), sa.ForeignKey("email_messages.email_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("event_flags", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "matched_snippets",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "drop_reason_codes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )

    op.create_table(
        "email_routes",
        sa.Column("email_id", sa.Text(), sa.ForeignKey("email_messages.email_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("route", sa.Text(), nullable=False),
        sa.Column("routed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("viewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("route IN ('drop', 'archive', 'notify', 'review')", name="ck_email_routes_route"),
    )

    op.create_index(
        "ix_email_routes_route_routed_at_desc",
        "email_routes",
        ["route", "routed_at"],
    )
    op.create_index("ix_email_rule_labels_event_type", "email_rule_labels", ["event_type"])
    op.create_index("ix_email_messages_user_received_at_desc", "email_messages", ["user_id", "received_at"])


def downgrade() -> None:
    op.drop_index("ix_email_messages_user_received_at_desc", table_name="email_messages")
    op.drop_index("ix_email_rule_labels_event_type", table_name="email_rule_labels")
    op.drop_index("ix_email_routes_route_routed_at_desc", table_name="email_routes")

    op.drop_table("email_routes")
    op.drop_table("email_rule_analysis")
    op.drop_table("email_action_items")
    op.drop_table("email_rule_labels")
    op.drop_table("email_messages")
