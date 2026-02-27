"""enforce ready-state requires exactly one ICS input

Revision ID: 0012_ready_requires_single_ics
Revises: 0011_single_ics_per_user
Create Date: 2026-02-27 14:30:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0012_ready_requires_single_ics"
down_revision = "0011_single_ics_per_user"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # If onboarding_completed_at is set but no ICS row exists, force onboarding back
    # to incomplete so runtime gate behavior remains deterministic.
    op.execute(
        sa.text(
            """
            WITH ics_counts AS (
                SELECT
                    u.id AS user_id,
                    COUNT(i.id) FILTER (WHERE lower(i.type) = 'ics') AS ics_count
                FROM users u
                LEFT JOIN inputs i ON i.user_id = u.id
                GROUP BY u.id
            )
            UPDATE users u
            SET onboarding_completed_at = NULL
            FROM ics_counts c
            WHERE u.id = c.user_id
              AND u.onboarding_completed_at IS NOT NULL
              AND c.ics_count <> 1
            """
        )
    )


def downgrade() -> None:
    # No reversible data operation required.
    pass
