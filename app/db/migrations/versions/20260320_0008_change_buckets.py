"""add explicit change intake and review bucket fields

Revision ID: 20260320_0008_change_buckets
Revises: 20260320_0007_gmail_parse_cache
Create Date: 2026-03-20 21:10:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = "20260320_0008_change_buckets"
down_revision = "20260320_0007_gmail_parse_cache"
branch_labels = None
depends_on = None


CHANGE_INTAKE_PHASE_ENUM = sa.Enum(
    "baseline",
    "replay",
    name="change_intake_phase",
    native_enum=False,
)
CHANGE_REVIEW_BUCKET_ENUM = sa.Enum(
    "initial_review",
    "changes",
    name="change_review_bucket",
    native_enum=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "changes" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("changes")}
    existing_indexes = {index["name"] for index in inspector.get_indexes("changes")}

    if "intake_phase" not in existing_columns:
        op.add_column(
            "changes",
            sa.Column(
                "intake_phase",
                CHANGE_INTAKE_PHASE_ENUM,
                nullable=False,
                server_default="replay",
            ),
        )
    if "review_bucket" not in existing_columns:
        op.add_column(
            "changes",
            sa.Column(
                "review_bucket",
                CHANGE_REVIEW_BUCKET_ENUM,
                nullable=False,
                server_default="changes",
            ),
        )

    bind.execute(
        text(
            """
            UPDATE changes
            SET intake_phase = COALESCE(NULLIF(intake_phase, ''), 'replay')
            """
        )
    )
    bind.execute(
        text(
            """
            UPDATE changes
            SET review_bucket = COALESCE(NULLIF(review_bucket, ''), 'changes')
            """
        )
    )

    if "ix_changes_user_bucket_status_detected" not in existing_indexes:
        op.create_index(
            "ix_changes_user_bucket_status_detected",
            "changes",
            ["user_id", "review_bucket", "review_status", "detected_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "changes" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("changes")}
    existing_indexes = {index["name"] for index in inspector.get_indexes("changes")}

    if "ix_changes_user_bucket_status_detected" in existing_indexes:
        op.drop_index("ix_changes_user_bucket_status_detected", table_name="changes")
    if "review_bucket" in existing_columns:
        op.drop_column("changes", "review_bucket")
    if "intake_phase" in existing_columns:
        op.drop_column("changes", "intake_phase")

    bind.execute(text("DROP TYPE IF EXISTS change_review_bucket"))
    bind.execute(text("DROP TYPE IF EXISTS change_intake_phase"))
