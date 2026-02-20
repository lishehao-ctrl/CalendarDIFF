"""add idempotency key to notifications

Revision ID: 0003_notification_idempotency_key
Revises: 0002_ics_audit_evidence
Create Date: 2026-02-20 00:40:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "0003_notification_idempotency_key"
down_revision = "0002_ics_audit_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    notification_columns = {column["name"] for column in inspector.get_columns("notifications")}

    if "idempotency_key" not in notification_columns:
        op.add_column("notifications", sa.Column("idempotency_key", sa.String(length=255), nullable=True))

    rows = bind.execute(sa.text("SELECT id, change_id FROM notifications ORDER BY id ASC")).fetchall()
    first_seen_by_change: set[int] = set()
    for row in rows:
        notification_id = int(row.id)
        change_id = int(row.change_id)
        base_key = f"email:change:{change_id}"
        if change_id in first_seen_by_change:
            key = f"{base_key}:dup:{notification_id}"
        else:
            key = base_key
            first_seen_by_change.add(change_id)

        bind.execute(
            sa.text("UPDATE notifications SET idempotency_key = :key WHERE id = :id"),
            {"key": key, "id": notification_id},
        )

    op.alter_column("notifications", "idempotency_key", existing_type=sa.String(length=255), nullable=False)
    op.create_unique_constraint("uq_notifications_idempotency_key", "notifications", ["idempotency_key"])


def downgrade() -> None:
    op.drop_constraint("uq_notifications_idempotency_key", "notifications", type_="unique")
    op.drop_column("notifications", "idempotency_key")
