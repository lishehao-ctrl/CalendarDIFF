"""baseline runtime schema for reset-db workflow

Revision ID: 20260227_0001_baseline_runtime
Revises:
Create Date: 2026-02-27 01:00:00.000000
"""

from __future__ import annotations

from alembic import op

from app.db import models  # noqa: F401
from app.db.base import Base


revision = "20260227_0001_baseline_runtime"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
