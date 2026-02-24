"""add email review candidates table for watcher rule queue

Revision ID: 0007_email_rule_candidates
Revises: 0006_onboarding_term_baselines
Create Date: 2026-02-24 19:10:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0007_email_rule_candidates"
down_revision = "0006_onboarding_term_baselines"
branch_labels = None
depends_on = None


review_candidate_status_enum = sa.Enum(
    "pending",
    "applied",
    "dismissed",
    "failed",
    name="review_candidate_status",
    native_enum=False,
)


def upgrade() -> None:
    op.create_table(
        "email_rule_candidates",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("input_id", sa.Integer(), sa.ForeignKey("inputs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("gmail_message_id", sa.Text(), nullable=False),
        sa.Column("source_change_id", sa.Integer(), sa.ForeignKey("changes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", review_candidate_status_enum, nullable=False, server_default="pending"),
        sa.Column("rule_version", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("proposed_event_type", sa.String(length=32), nullable=True),
        sa.Column("proposed_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("proposed_title", sa.String(length=512), nullable=True),
        sa.Column("proposed_course_hint", sa.String(length=128), nullable=True),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("raw_extract", sa.JSON(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("from_header", sa.Text(), nullable=True),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("applied_change_id", sa.Integer(), sa.ForeignKey("changes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "input_id",
            "gmail_message_id",
            "rule_version",
            name="uq_email_rule_candidates_input_message_rule",
        ),
    )
    op.create_index(
        "ix_email_rule_candidates_user_status_created",
        "email_rule_candidates",
        ["user_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_email_rule_candidates_user_status_created", table_name="email_rule_candidates")
    op.drop_table("email_rule_candidates")
