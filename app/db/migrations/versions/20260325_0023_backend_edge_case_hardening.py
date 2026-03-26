"""add approval ticket open uniqueness index

Revision ID: 20260325_0023
Revises: 20260325_0018_agent_lang
Create Date: 2026-03-25 13:05:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260325_0023"
down_revision = "20260325_0018_agent_lang"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "approval_tickets" not in tables:
        return
    index_names = {index["name"] for index in inspector.get_indexes("approval_tickets")}
    if "uq_approval_tickets_open_proposal" not in index_names:
        op.create_index(
            "uq_approval_tickets_open_proposal",
            "approval_tickets",
            ["proposal_id"],
            unique=True,
            postgresql_where=sa.text("status = 'open'"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "approval_tickets" not in tables:
        return
    index_names = {index["name"] for index in inspector.get_indexes("approval_tickets")}
    if "uq_approval_tickets_open_proposal" in index_names:
        op.drop_index("uq_approval_tickets_open_proposal", table_name="approval_tickets")
