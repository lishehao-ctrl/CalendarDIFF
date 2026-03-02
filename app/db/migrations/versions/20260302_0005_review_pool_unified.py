"""add unified review status and source observations

Revision ID: 20260302_0005_review_pool
Revises: 20260302_0004_src_legacy_map
Create Date: 2026-03-02 18:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260302_0005_review_pool"
down_revision = "20260302_0004_src_legacy_map"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "changes" in tables:
        change_columns = {column["name"] for column in inspector.get_columns("changes")}

        if "review_status" not in change_columns:
            op.add_column(
                "changes",
                sa.Column(
                    "review_status",
                    sa.Enum("pending", "approved", "rejected", name="review_status", native_enum=False),
                    nullable=False,
                    server_default="approved",
                ),
            )
        if "reviewed_at" not in change_columns:
            op.add_column("changes", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
        if "review_note" not in change_columns:
            op.add_column("changes", sa.Column("review_note", sa.Text(), nullable=True))
        if "reviewed_by_user_id" not in change_columns:
            op.add_column("changes", sa.Column("reviewed_by_user_id", sa.Integer(), nullable=True))
            op.create_foreign_key(
                "fk_changes_reviewed_by_user_id_users",
                "changes",
                "users",
                ["reviewed_by_user_id"],
                ["id"],
                ondelete="SET NULL",
            )
        if "proposal_merge_key" not in change_columns:
            op.add_column("changes", sa.Column("proposal_merge_key", sa.String(length=128), nullable=True))
        if "proposal_sources_json" not in change_columns:
            op.add_column("changes", sa.Column("proposal_sources_json", sa.JSON(), nullable=True))

        after_snapshot_col = next((column for column in inspector.get_columns("changes") if column["name"] == "after_snapshot_id"), None)
        if after_snapshot_col is not None and not bool(after_snapshot_col.get("nullable", True)):
            op.alter_column("changes", "after_snapshot_id", existing_type=sa.Integer(), nullable=True)

        change_indexes = {index["name"] for index in inspector.get_indexes("changes")}
        if "ix_changes_review_status_detected_at" not in change_indexes:
            op.create_index("ix_changes_review_status_detected_at", "changes", ["review_status", "detected_at"])

        op.execute("UPDATE changes SET review_status = 'approved' WHERE review_status IS NULL")

    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "source_event_observations" not in tables:
        op.create_table(
            "source_event_observations",
            sa.Column("id", sa.BigInteger(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("source_id", sa.Integer(), nullable=False),
            sa.Column(
                "source_kind",
                sa.Enum(
                    "calendar",
                    "email",
                    "task",
                    "exam",
                    "announcement",
                    name="source_kind",
                    native_enum=False,
                ),
                nullable=False,
            ),
            sa.Column("provider", sa.String(length=64), nullable=False),
            sa.Column("external_event_id", sa.String(length=255), nullable=False),
            sa.Column("merge_key", sa.String(length=128), nullable=False),
            sa.Column("event_payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
            sa.Column("event_hash", sa.String(length=64), nullable=False),
            sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("last_request_id", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["source_id"], ["input_sources.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("source_id", "external_event_id", name="uq_source_event_observations_source_external"),
        )

    inspector = sa.inspect(bind)
    if "source_event_observations" in set(inspector.get_table_names()):
        observation_indexes = {index["name"] for index in inspector.get_indexes("source_event_observations")}
        if "ix_source_event_observations_user_merge_active" not in observation_indexes:
            op.create_index(
                "ix_source_event_observations_user_merge_active",
                "source_event_observations",
                ["user_id", "merge_key", "is_active"],
            )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_source_event_observations_user_merge_active")
    op.execute("DROP TABLE IF EXISTS source_event_observations")

    op.execute("DROP INDEX IF EXISTS ix_changes_review_status_detected_at")
    op.execute("ALTER TABLE changes DROP COLUMN IF EXISTS proposal_sources_json")
    op.execute("ALTER TABLE changes DROP COLUMN IF EXISTS proposal_merge_key")
    op.execute("ALTER TABLE changes DROP COLUMN IF EXISTS reviewed_by_user_id")
    op.execute("ALTER TABLE changes DROP COLUMN IF EXISTS review_note")
    op.execute("ALTER TABLE changes DROP COLUMN IF EXISTS reviewed_at")
    op.execute("ALTER TABLE changes DROP COLUMN IF EXISTS review_status")
    op.execute("DROP TYPE IF EXISTS review_status")
