"""initial mvp schema

Revision ID: 0001_mvp_schema
Revises: 
Create Date: 2026-02-20 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0001_mvp_schema"
down_revision = None
branch_labels = None
depends_on = None


source_type_enum = sa.Enum("ics", name="source_type", native_enum=False)
change_type_enum = sa.Enum(
    "created",
    "removed",
    "due_changed",
    "title_changed",
    "course_changed",
    name="change_type",
    native_enum=False,
)
notification_channel_enum = sa.Enum("email", name="notification_channel", native_enum=False)
notification_status_enum = sa.Enum("pending", "sent", "failed", name="notification_status", native_enum=False)


def upgrade() -> None:
    bind = op.get_bind()
    source_type_enum.create(bind, checkfirst=True)
    change_type_enum.create(bind, checkfirst=True)
    notification_channel_enum.create(bind, checkfirst=True)
    notification_status_enum.create(bind, checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "sources",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", source_type_enum, nullable=False, server_default="ics"),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("encrypted_url", sa.Text(), nullable=False),
        sa.Column("interval_minutes", sa.Integer(), nullable=False, server_default="15"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_sources_active_last_checked", "sources", ["is_active", "last_checked_at"])

    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("uid", sa.String(length=255), nullable=False),
        sa.Column("course_label", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("start_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("source_id", "uid", name="uq_events_source_id_uid"),
    )

    op.create_table(
        "snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("etag", sa.String(length=255), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False),
    )

    op.create_table(
        "snapshot_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("snapshot_id", sa.Integer(), sa.ForeignKey("snapshots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("uid", sa.String(length=255), nullable=False),
        sa.Column("course_label", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("start_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at_utc", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "changes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_uid", sa.String(length=255), nullable=False),
        sa.Column("change_type", change_type_enum, nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("before_json", sa.JSON(), nullable=True),
        sa.Column("after_json", sa.JSON(), nullable=True),
        sa.Column("delta_seconds", sa.Integer(), nullable=True),
    )
    op.create_index("ix_changes_source_detected_desc", "changes", ["source_id", "detected_at"])

    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("change_id", sa.Integer(), sa.ForeignKey("changes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel", notification_channel_enum, nullable=False, server_default="email"),
        sa.Column("status", notification_status_enum, nullable=False, server_default="pending"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("notifications")
    op.drop_index("ix_changes_source_detected_desc", table_name="changes")
    op.drop_table("changes")
    op.drop_table("snapshot_events")
    op.drop_table("snapshots")
    op.drop_table("events")
    op.drop_index("ix_sources_active_last_checked", table_name="sources")
    op.drop_table("sources")
    op.drop_table("users")

    bind = op.get_bind()
    notification_status_enum.drop(bind, checkfirst=True)
    notification_channel_enum.drop(bind, checkfirst=True)
    change_type_enum.drop(bind, checkfirst=True)
    source_type_enum.drop(bind, checkfirst=True)
