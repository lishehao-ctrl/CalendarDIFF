"""add gmail onboarding skip timestamp

Revision ID: 20260314_0004_gmail_skip
Revises: 20260314_0003_manual_support
Create Date: 2026-03-14 12:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260314_0004_gmail_skip"
down_revision = "20260314_0003_manual_support"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "users" not in inspector.get_table_names():
        return
    existing_columns = {column["name"] for column in inspector.get_columns("users")}
    if "gmail_onboarding_skipped_at" in existing_columns:
        return
    op.add_column("users", sa.Column("gmail_onboarding_skipped_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "users" not in inspector.get_table_names():
        return
    existing_columns = {column["name"] for column in inspector.get_columns("users")}
    if "gmail_onboarding_skipped_at" not in existing_columns:
        return
    op.drop_column("users", "gmail_onboarding_skipped_at")
