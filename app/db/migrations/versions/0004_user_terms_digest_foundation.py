"""user-term foundation + digest scheduling tables

Revision ID: 0004_user_terms_digest
Revises: 0003_fixed_interval_notify
Create Date: 2026-02-24 22:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0004_user_terms_digest"
down_revision = "0003_fixed_interval_notify"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("notify_email", sa.String(length=255), nullable=True))
    op.add_column(
        "users",
        sa.Column("calendar_delay_seconds", sa.Integer(), nullable=False, server_default=sa.text("120")),
    )

    op.create_table(
        "user_terms",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "code", name="uq_user_terms_user_code"),
    )
    op.create_index("ix_user_terms_user_id", "user_terms", ["user_id"])
    op.create_index("ix_user_terms_active_window", "user_terms", ["user_id", "is_active", "starts_on", "ends_on"])

    op.add_column("inputs", sa.Column("user_term_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_inputs_user_term_id_user_terms",
        "inputs",
        "user_terms",
        ["user_term_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_inputs_user_term_id", "inputs", ["user_term_id"])

    op.create_table(
        "user_notification_prefs",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("digest_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "timezone",
            sa.String(length=128),
            nullable=False,
            server_default=sa.text("'America/Los_Angeles'"),
        ),
        sa.Column(
            "digest_times",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[\"09:00\"]'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "digest_send_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scheduled_local_date", sa.Date(), nullable=False),
        sa.Column("scheduled_local_time", sa.String(length=5), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("item_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint("status IN ('sent','skipped_empty','failed')", name="ck_digest_send_log_status"),
        sa.UniqueConstraint("user_id", "scheduled_local_date", "scheduled_local_time", name="uq_digest_send_log_slot"),
    )
    op.create_index(
        "ix_digest_send_log_user_slot",
        "digest_send_log",
        ["user_id", "scheduled_local_date", "scheduled_local_time"],
    )

    op.add_column("notifications", sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_notifications_status_notified_enqueue",
        "notifications",
        ["status", "notified_at", "enqueue_reason"],
    )

    # Backfill user-level notify settings from first profile of each user.
    op.execute(
        """
        UPDATE users AS u
        SET notify_email = p.notify_email,
            calendar_delay_seconds = COALESCE(p.calendar_delay_seconds, 120)
        FROM (
            SELECT DISTINCT ON (user_id)
                user_id,
                notify_email,
                calendar_delay_seconds
            FROM profiles
            ORDER BY user_id, id
        ) AS p
        WHERE u.id = p.user_id
        """
    )

    # Backfill user terms from profile terms.
    op.execute(
        """
        INSERT INTO user_terms (user_id, code, label, starts_on, ends_on, is_active, created_at, updated_at)
        SELECT p.user_id, pt.code, pt.label, pt.starts_on, pt.ends_on, pt.is_active, pt.created_at, pt.updated_at
        FROM profile_terms AS pt
        JOIN profiles AS p ON p.id = pt.profile_id
        ON CONFLICT (user_id, code) DO NOTHING
        """
    )

    # Map legacy inputs.term_id -> inputs.user_term_id.
    op.execute(
        """
        UPDATE inputs AS i
        SET user_term_id = ut.id
        FROM profile_terms AS pt
        JOIN profiles AS p ON p.id = pt.profile_id
        JOIN user_terms AS ut
          ON ut.user_id = p.user_id
         AND ut.code = pt.code
        WHERE i.term_id = pt.id
          AND i.user_term_id IS NULL
        """
    )

    # Existing sent notifications are treated as already notified.
    op.execute(
        """
        UPDATE notifications
        SET notified_at = sent_at
        WHERE status = 'sent'
          AND sent_at IS NOT NULL
          AND notified_at IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_status_notified_enqueue", table_name="notifications")
    op.drop_column("notifications", "notified_at")

    op.drop_index("ix_digest_send_log_user_slot", table_name="digest_send_log")
    op.drop_table("digest_send_log")

    op.drop_table("user_notification_prefs")

    op.drop_index("ix_inputs_user_term_id", table_name="inputs")
    op.drop_constraint("fk_inputs_user_term_id_user_terms", "inputs", type_="foreignkey")
    op.drop_column("inputs", "user_term_id")

    op.drop_index("ix_user_terms_active_window", table_name="user_terms")
    op.drop_index("ix_user_terms_user_id", table_name="user_terms")
    op.drop_table("user_terms")

    op.drop_column("users", "calendar_delay_seconds")
    op.drop_column("users", "notify_email")
