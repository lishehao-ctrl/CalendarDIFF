"""fix input interval to 15m and deprecate input-level notify

Revision ID: 0003_fixed_interval_notify
Revises: 0002_profile_terms_identity
Create Date: 2026-02-23 19:00:00.000000
"""

from __future__ import annotations

from alembic import op


# revision identifiers, used by Alembic.
revision = "0003_fixed_interval_notify"
down_revision = "0002_profile_terms_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE inputs SET interval_minutes = 15")
    op.execute("UPDATE inputs SET notify_email = NULL")
    op.create_check_constraint(
        "ck_inputs_interval_minutes_fixed_15",
        "inputs",
        "interval_minutes = 15",
    )


def downgrade() -> None:
    op.drop_constraint("ck_inputs_interval_minutes_fixed_15", "inputs", type_="check")
