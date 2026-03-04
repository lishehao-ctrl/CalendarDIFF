"""drop legacy email audit tables after review-items hard cut

Revision ID: 20260304_0011_drop_email_audit
Revises: 20260304_0010_link_alerts
Create Date: 2026-03-04 23:05:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260304_0011_drop_email_audit"
down_revision = "20260304_0010_link_alerts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    # Drop from child to parent to satisfy FK dependencies.
    for table_name in [
        "email_action_items",
        "email_rule_labels",
        "email_rule_analysis",
        "email_routes",
        "email_messages",
    ]:
        if table_name in tables:
            op.drop_table(table_name)


def downgrade() -> None:
    raise RuntimeError(
        "Irreversible migration: legacy email audit tables were dropped with no data retention strategy."
    )
