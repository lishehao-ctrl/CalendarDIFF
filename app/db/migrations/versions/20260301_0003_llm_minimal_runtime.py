"""drop llm provider registry and source bindings for minimal runtime

Revision ID: 20260301_0003_llm_minimal
Revises: 20260301_0002_llm_gateway
Create Date: 2026-03-01 08:00:00.000000
"""

from __future__ import annotations

from alembic import op


revision = "20260301_0003_llm_minimal"
down_revision = "20260301_0002_llm_gateway"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_source_llm_bindings_provider_id")
    op.execute("DROP TABLE IF EXISTS source_llm_bindings")
    op.execute("DROP INDEX IF EXISTS ix_llm_providers_enabled_default")
    op.execute("DROP TABLE IF EXISTS llm_providers")


def downgrade() -> None:
    # Do not recreate removed provider registry tables in minimal runtime mode.
    pass
