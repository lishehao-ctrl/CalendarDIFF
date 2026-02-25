"""enforce one-user-one-ics invariant

Revision ID: 0011_single_ics_per_user
Revises: 0010_drop_review_candidates
Create Date: 2026-02-27 12:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0011_single_ics_per_user"
down_revision = "0010_drop_review_candidates"
branch_labels = None
depends_on = None


UNIQUE_ICS_PER_USER_INDEX = "ux_inputs_user_single_ics"


def upgrade() -> None:
    # Keep only the newest ICS input row per user before adding the hard uniqueness invariant.
    op.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY user_id
                        ORDER BY created_at DESC, id DESC
                    ) AS rn
                FROM inputs
                WHERE type = 'ICS'
            )
            DELETE FROM inputs i
            USING ranked r
            WHERE i.id = r.id
              AND r.rn > 1
            """
        )
    )

    op.create_index(
        UNIQUE_ICS_PER_USER_INDEX,
        "inputs",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("type = 'ICS'"),
    )


def downgrade() -> None:
    op.drop_index(UNIQUE_ICS_PER_USER_INDEX, table_name="inputs")

