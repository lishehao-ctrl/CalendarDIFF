"""add event entities table for canonical/enrichment linker

Revision ID: 20260303_0008_event_entities
Revises: 20260303_0007_user_timezone
Create Date: 2026-03-03 09:10:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260303_0008_event_entities"
down_revision = "20260303_0007_user_timezone"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "event_entities" in tables:
        return

    op.create_table(
        "event_entities",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("entity_uid", sa.String(length=128), nullable=False),
        sa.Column("course_best_json", sa.JSON(), nullable=True),
        sa.Column("course_best_strength", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("course_aliases_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("title_aliases_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "entity_uid", name="uq_event_entities_user_entity_uid"),
    )
    op.create_index("ix_event_entities_user_updated", "event_entities", ["user_id", "updated_at"])


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_event_entities_user_updated")
    op.execute("DROP TABLE IF EXISTS event_entities")
