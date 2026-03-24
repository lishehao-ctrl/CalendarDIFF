"""add agent audit origin fields

Revision ID: 20260324_0013_agent_audit
Revises: 20260323_0012_mcp_access_tokens
Create Date: 2026-03-24 01:45:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260324_0013_agent_audit"
down_revision = "20260323_0012_mcp_access_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    proposal_columns = {column["name"] for column in inspector.get_columns("agent_proposals")}
    if "origin_kind" not in proposal_columns:
        op.add_column("agent_proposals", sa.Column("origin_kind", sa.String(length=32), nullable=False, server_default="unknown"))
    if "origin_label" not in proposal_columns:
        op.add_column("agent_proposals", sa.Column("origin_label", sa.String(length=64), nullable=False, server_default="unknown"))

    ticket_columns = {column["name"] for column in inspector.get_columns("approval_tickets")}
    if "origin_kind" not in ticket_columns:
        op.add_column("approval_tickets", sa.Column("origin_kind", sa.String(length=32), nullable=False, server_default="unknown"))
    if "origin_label" not in ticket_columns:
        op.add_column("approval_tickets", sa.Column("origin_label", sa.String(length=64), nullable=False, server_default="unknown"))
    if "last_transition_kind" not in ticket_columns:
        op.add_column("approval_tickets", sa.Column("last_transition_kind", sa.String(length=32), nullable=False, server_default="unknown"))
    if "last_transition_label" not in ticket_columns:
        op.add_column("approval_tickets", sa.Column("last_transition_label", sa.String(length=64), nullable=False, server_default="unknown"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    ticket_columns = {column["name"] for column in inspector.get_columns("approval_tickets")}
    if "last_transition_label" in ticket_columns:
        op.drop_column("approval_tickets", "last_transition_label")
    if "last_transition_kind" in ticket_columns:
        op.drop_column("approval_tickets", "last_transition_kind")
    if "origin_label" in ticket_columns:
        op.drop_column("approval_tickets", "origin_label")
    if "origin_kind" in ticket_columns:
        op.drop_column("approval_tickets", "origin_kind")

    proposal_columns = {column["name"] for column in inspector.get_columns("agent_proposals")}
    if "origin_label" in proposal_columns:
        op.drop_column("agent_proposals", "origin_label")
    if "origin_kind" in proposal_columns:
        op.drop_column("agent_proposals", "origin_kind")
