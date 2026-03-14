"""add calendar component fanout tracking

Revision ID: 20260313_0002_calendar_fanout
Revises: 20260311_0001_semantic_core
Create Date: 2026-03-13 19:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260313_0002_calendar_fanout"
down_revision = "20260311_0001_semantic_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "calendar_component_parse_tasks" in inspector.get_table_names():
        return

    op.create_table(
        "calendar_component_parse_tasks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("component_key", sa.String(length=255), nullable=False),
        sa.Column("external_event_id", sa.String(length=255), nullable=False),
        sa.Column("vevent_uid", sa.String(length=255), nullable=False),
        sa.Column("recurrence_id", sa.String(length=255), nullable=True),
        sa.Column("fingerprint", sa.String(length=128), nullable=True),
        sa.Column("component_ical_b64", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "RUNNING",
                "SUCCEEDED",
                "UNRESOLVED",
                "FAILED",
                name="calendar_component_parse_status",
                native_enum=False,
            ),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("parsed_record_json", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["source_id"], ["input_sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "request_id",
            "component_key",
            name="uq_calendar_component_parse_tasks_request_component",
        ),
    )
    op.create_index(
        "ix_calendar_component_parse_tasks_request_status",
        "calendar_component_parse_tasks",
        ["request_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_calendar_component_parse_tasks_source_request",
        "calendar_component_parse_tasks",
        ["source_id", "request_id"],
        unique=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "calendar_component_parse_tasks" not in inspector.get_table_names():
        return

    op.drop_index("ix_calendar_component_parse_tasks_source_request", table_name="calendar_component_parse_tasks")
    op.drop_index("ix_calendar_component_parse_tasks_request_status", table_name="calendar_component_parse_tasks")
    op.drop_table("calendar_component_parse_tasks")
    op.execute("DROP TYPE IF EXISTS calendar_component_parse_status")
