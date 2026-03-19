"""remove legacy event link tables

Revision ID: 20260319_0005_remove_event_links
Revises: 20260314_0004_gmail_skip
Create Date: 2026-03-19 10:00:00
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect, text


revision = "20260319_0005_remove_event_links"
down_revision = "20260314_0004_gmail_skip"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "event_link_candidates" in existing_tables:
        op.drop_table("event_link_candidates")
    if "event_link_blocks" in existing_tables:
        op.drop_table("event_link_blocks")
    if "event_entity_links" in existing_tables:
        op.drop_table("event_entity_links")

    bind.execute(text("DROP TYPE IF EXISTS event_link_candidate_reason"))
    bind.execute(text("DROP TYPE IF EXISTS event_link_candidate_status"))
    bind.execute(text("DROP TYPE IF EXISTS event_link_origin"))


def downgrade() -> None:
    raise RuntimeError("downgrade is not supported for remove_event_links migration")
