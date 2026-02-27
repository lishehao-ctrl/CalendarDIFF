"""input-first baseline schema

Revision ID: 0001_input_first_baseline
Revises:
Create Date: 2026-02-22 16:30:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision = "0001_input_first_baseline"
down_revision = None
branch_labels = None
depends_on = None


input_type_enum = sa.Enum("ics", "email", name="input_type", native_enum=False)
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
sync_trigger_type_enum = sa.Enum("scheduler", "manual", name="sync_trigger_type", native_enum=False)
sync_run_status_enum = sa.Enum(
    "NO_CHANGE",
    "CHANGED",
    "FETCH_FAILED",
    "PARSE_FAILED",
    "DIFF_FAILED",
    "EMAIL_FAILED",
    "LOCK_SKIPPED",
    name="sync_run_status",
    native_enum=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    input_type_enum.create(bind, checkfirst=True)
    change_type_enum.create(bind, checkfirst=True)
    notification_channel_enum.create(bind, checkfirst=True)
    notification_status_enum.create(bind, checkfirst=True)
    sync_trigger_type_enum.create(bind, checkfirst=True)
    sync_run_status_enum.create(bind, checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "profiles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("normalized_name", sa.String(length=255), nullable=False),
        sa.Column("notify_email", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("calendar_delay_seconds", sa.Integer(), nullable=False, server_default="120"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "normalized_name", name="uq_profiles_user_normalized_name"),
    )
    op.create_index("ix_profiles_user_id", "profiles", ["user_id"])

    op.create_table(
        "inputs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("profile_id", sa.Integer(), sa.ForeignKey("profiles.id", ondelete="SET NULL"), nullable=True),
        sa.Column("type", input_type_enum, nullable=False, server_default="ics"),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("normalized_name", sa.String(length=255), nullable=False),
        sa.Column("encrypted_url", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("gmail_label", sa.String(length=255), nullable=True),
        sa.Column("gmail_from_contains", sa.String(length=255), nullable=True),
        sa.Column("gmail_subject_keywords", JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("gmail_history_id", sa.Text(), nullable=True),
        sa.Column("gmail_account_email", sa.String(length=255), nullable=True),
        sa.Column("encrypted_access_token", sa.Text(), nullable=True),
        sa.Column("encrypted_refresh_token", sa.Text(), nullable=True),
        sa.Column("access_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("etag", sa.Text(), nullable=True),
        sa.Column("last_modified", sa.Text(), nullable=True),
        sa.Column("last_content_hash", sa.String(length=64), nullable=True),
        sa.Column("notify_email", sa.String(length=255), nullable=True),
        sa.Column("interval_minutes", sa.Integer(), nullable=False, server_default="15"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_ok_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_change_detected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_email_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("profile_id", "type", "normalized_name", name="uq_inputs_profile_type_normalized_name"),
    )
    op.create_index("ix_inputs_active_last_checked", "inputs", ["is_active", "last_checked_at"])
    op.create_index("ix_inputs_due_lookup", "inputs", ["is_active", "last_checked_at", "interval_minutes"])
    op.create_index("ix_inputs_profile_id", "inputs", ["profile_id"])

    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("input_id", sa.Integer(), sa.ForeignKey("inputs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("uid", sa.String(length=255), nullable=False),
        sa.Column("course_label", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("start_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("input_id", "uid", name="uq_events_input_id_uid"),
    )

    op.create_table(
        "snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("input_id", sa.Integer(), sa.ForeignKey("inputs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("etag", sa.String(length=255), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column("raw_evidence_key", JSONB(astext_type=sa.Text()), nullable=True),
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
        sa.Column("input_id", sa.Integer(), sa.ForeignKey("inputs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_uid", sa.String(length=255), nullable=False),
        sa.Column("change_type", change_type_enum, nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("before_json", JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after_json", JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("delta_seconds", sa.Integer(), nullable=True),
        sa.Column("viewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("viewed_note", sa.Text(), nullable=True),
        sa.Column("before_snapshot_id", sa.Integer(), sa.ForeignKey("snapshots.id", ondelete="SET NULL"), nullable=True),
        sa.Column("after_snapshot_id", sa.Integer(), sa.ForeignKey("snapshots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("evidence_keys", JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index("ix_changes_input_detected_desc", "changes", ["input_id", "detected_at"])

    op.create_table(
        "course_overrides",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("input_id", sa.Integer(), sa.ForeignKey("inputs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("original_course_label", sa.String(length=64), nullable=False),
        sa.Column("display_course_label", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("input_id", "original_course_label", name="uq_course_overrides_input_label"),
    )

    op.create_table(
        "task_overrides",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("input_id", sa.Integer(), sa.ForeignKey("inputs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_uid", sa.String(length=255), nullable=False),
        sa.Column("display_title", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("input_id", "event_uid", name="uq_task_overrides_input_uid"),
    )

    op.create_table(
        "sync_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("input_id", sa.Integer(), sa.ForeignKey("inputs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("trigger_type", sync_trigger_type_enum, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sync_run_status_enum, nullable=False),
        sa.Column("changes_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=512), nullable=True),
        sa.Column("lock_owner", sa.String(length=128), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
    )
    op.create_index("ix_sync_runs_input_started_desc", "sync_runs", ["input_id", "started_at"])
    op.create_index("ix_sync_runs_started_at", "sync_runs", ["started_at"])
    op.create_index("ix_sync_runs_status_started_at", "sync_runs", ["status", "started_at"])

    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("change_id", sa.Integer(), sa.ForeignKey("changes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel", notification_channel_enum, nullable=False, server_default="email"),
        sa.Column("status", notification_status_enum, nullable=False, server_default="pending"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("deliver_after", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("enqueue_reason", sa.String(length=64), nullable=True),
        sa.UniqueConstraint("idempotency_key", name="uq_notifications_idempotency_key"),
        sa.UniqueConstraint("change_id", "channel", name="uq_notifications_change_channel"),
    )
    op.create_index("ix_notifications_status_deliver_after", "notifications", ["status", "deliver_after"])


def downgrade() -> None:
    op.drop_index("ix_notifications_status_deliver_after", table_name="notifications")
    op.drop_table("notifications")
    op.drop_index("ix_sync_runs_status_started_at", table_name="sync_runs")
    op.drop_index("ix_sync_runs_started_at", table_name="sync_runs")
    op.drop_index("ix_sync_runs_input_started_desc", table_name="sync_runs")
    op.drop_table("sync_runs")
    op.drop_table("task_overrides")
    op.drop_table("course_overrides")
    op.drop_index("ix_changes_input_detected_desc", table_name="changes")
    op.drop_table("changes")
    op.drop_table("snapshot_events")
    op.drop_table("snapshots")
    op.drop_table("events")
    op.drop_index("ix_inputs_profile_id", table_name="inputs")
    op.drop_index("ix_inputs_due_lookup", table_name="inputs")
    op.drop_index("ix_inputs_active_last_checked", table_name="inputs")
    op.drop_table("inputs")
    op.drop_index("ix_profiles_user_id", table_name="profiles")
    op.drop_table("profiles")
    op.drop_table("users")

    bind = op.get_bind()
    sync_run_status_enum.drop(bind, checkfirst=True)
    sync_trigger_type_enum.drop(bind, checkfirst=True)
    notification_status_enum.drop(bind, checkfirst=True)
    notification_channel_enum.drop(bind, checkfirst=True)
    change_type_enum.drop(bind, checkfirst=True)
    input_type_enum.drop(bind, checkfirst=True)
