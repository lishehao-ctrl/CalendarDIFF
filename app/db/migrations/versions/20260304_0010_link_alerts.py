"""add link alert queue for auto-link follow-up

Revision ID: 20260304_0010_link_alerts
Revises: 20260303_0009_linker
Create Date: 2026-03-04 18:20:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260304_0010_link_alerts"
down_revision = "20260303_0009_linker"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "event_link_alerts" not in tables:
        op.create_table(
            "event_link_alerts",
            sa.Column("id", sa.BigInteger(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("source_id", sa.Integer(), nullable=False),
            sa.Column("external_event_id", sa.String(length=255), nullable=False),
            sa.Column("entity_uid", sa.String(length=128), nullable=False),
            sa.Column("link_id", sa.BigInteger(), nullable=True),
            sa.Column(
                "risk_level",
                sa.Enum("medium", name="event_link_alert_risk_level", native_enum=False),
                nullable=False,
                server_default="medium",
            ),
            sa.Column(
                "reason_code",
                sa.Enum("auto_link_without_canonical_change", name="event_link_alert_reason", native_enum=False),
                nullable=False,
                server_default="auto_link_without_canonical_change",
            ),
            sa.Column(
                "status",
                sa.Enum("pending", "dismissed", "marked_safe", "resolved", name="event_link_alert_status", native_enum=False),
                nullable=False,
                server_default="pending",
            ),
            sa.Column(
                "resolution_code",
                sa.Enum(
                    "dismissed_by_user",
                    "marked_safe_by_user",
                    "canonical_pending_created",
                    "candidate_opened",
                    "link_removed",
                    "link_relinked",
                    name="event_link_alert_resolution",
                    native_enum=False,
                ),
                nullable=True,
            ),
            sa.Column("evidence_snapshot_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
            sa.Column("reviewed_by_user_id", sa.Integer(), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("review_note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["source_id"], ["input_sources.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "user_id",
                "source_id",
                "external_event_id",
                "entity_uid",
                name="uq_event_link_alerts_user_source_external_entity",
            ),
        )
        op.create_index(
            "ix_event_link_alerts_user_status_created",
            "event_link_alerts",
            ["user_id", "status", "created_at"],
        )
        op.create_index(
            "ix_event_link_alerts_source_external",
            "event_link_alerts",
            ["source_id", "external_event_id"],
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_event_link_alerts_source_external")
    op.execute("DROP INDEX IF EXISTS ix_event_link_alerts_user_status_created")
    op.execute("DROP TABLE IF EXISTS event_link_alerts")
