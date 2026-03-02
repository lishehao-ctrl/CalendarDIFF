"""add source -> legacy input bridge table

Revision ID: 20260302_0004_src_legacy_map
Revises: 20260301_0003_llm_minimal
Create Date: 2026-03-02 10:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260302_0004_src_legacy_map"
down_revision = "20260301_0003_llm_minimal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "source_legacy_inputs" not in existing_tables:
        op.create_table(
            "source_legacy_inputs",
            sa.Column("source_id", sa.Integer(), nullable=False),
            sa.Column("input_id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["source_id"], ["input_sources.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["input_id"], ["inputs.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("source_id"),
            sa.UniqueConstraint("input_id", name="uq_source_legacy_inputs_input_id"),
        )

    inspector = sa.inspect(bind)
    bridge_indexes = (
        {idx["name"] for idx in inspector.get_indexes("source_legacy_inputs")}
        if "source_legacy_inputs" in set(inspector.get_table_names())
        else set()
    )
    if "ix_source_legacy_inputs_input_id" not in bridge_indexes:
        op.create_index("ix_source_legacy_inputs_input_id", "source_legacy_inputs", ["input_id"])


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_source_legacy_inputs_input_id")
    op.execute("DROP TABLE IF EXISTS source_legacy_inputs")
