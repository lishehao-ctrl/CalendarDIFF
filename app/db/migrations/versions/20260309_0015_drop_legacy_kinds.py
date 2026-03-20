"""historical bridge for legacy production revision

Revision ID: 20260309_0015_drop_legacy_kinds
Revises:
Create Date: 2026-03-09 16:05:00.000000
"""

from __future__ import annotations


revision = "20260309_0015_drop_legacy_kinds"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Keep the historical production revision addressable.

    Older deployed databases were stamped at this revision before the
    semantic-core baseline replaced the legacy migration chain.
    """


def downgrade() -> None:
    """The historical bridge does not own schema changes."""
