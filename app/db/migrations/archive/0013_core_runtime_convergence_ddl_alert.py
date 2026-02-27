"""core runtime convergence for ddl-alert demo surface

Revision ID: 0013_core_runtime_ddl_alert
Revises: 0012_ready_requires_single_ics
Create Date: 2026-02-28 10:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0013_core_runtime_ddl_alert"
down_revision = "0012_ready_requires_single_ics"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names(schema="public")


def _drop_table_if_exists(table_name: str) -> None:
    if _table_exists(table_name):
        op.drop_table(table_name)


def upgrade() -> None:
    # Normalize any pre-existing notify rows before shrinking route enum surface.
    op.execute(
        sa.text(
            """
            UPDATE email_routes
            SET route = 'archive'
            WHERE route = 'notify'
            """
        )
    )

    op.drop_constraint("ck_email_routes_route", "email_routes", type_="check")
    op.create_check_constraint(
        "ck_email_routes_route",
        "email_routes",
        "route IN ('drop', 'archive', 'review')",
    )

    _drop_table_if_exists("course_overrides")
    _drop_table_if_exists("task_overrides")
    _drop_table_if_exists("user_notification_prefs")


def downgrade() -> None:
    op.drop_constraint("ck_email_routes_route", "email_routes", type_="check")
    op.create_check_constraint(
        "ck_email_routes_route",
        "email_routes",
        "route IN ('drop', 'archive', 'notify', 'review')",
    )

    if not _table_exists("user_notification_prefs"):
        op.create_table(
            "user_notification_prefs",
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("digest_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column(
                "timezone",
                sa.String(length=128),
                nullable=False,
                server_default="America/Los_Angeles",
            ),
            sa.Column("digest_times", sa.JSON(), nullable=False, server_default='["09:00"]'),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        )

    if not _table_exists("course_overrides"):
        op.create_table(
            "course_overrides",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("input_id", sa.Integer(), sa.ForeignKey("inputs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("original_course_label", sa.String(length=64), nullable=False),
            sa.Column("display_course_label", sa.String(length=64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("input_id", "original_course_label", name="uq_course_overrides_input_label"),
        )

    if not _table_exists("task_overrides"):
        op.create_table(
            "task_overrides",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("input_id", sa.Integer(), sa.ForeignKey("inputs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("event_uid", sa.String(length=255), nullable=False),
            sa.Column("display_title", sa.String(length=512), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("input_id", "event_uid", name="uq_task_overrides_input_uid"),
        )
