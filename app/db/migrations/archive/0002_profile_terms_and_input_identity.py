"""profile terms + input identity-key schema

Revision ID: 0002_profile_terms_identity
Revises: 0001_input_first_baseline
Create Date: 2026-02-23 11:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "0002_profile_terms_identity"
down_revision = "0001_input_first_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "profile_terms",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("profile_id", sa.Integer(), sa.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("profile_id", "code", name="uq_profile_terms_profile_code"),
        sa.CheckConstraint("starts_on <= ends_on", name="ck_profile_terms_start_before_end"),
    )
    op.create_index("ix_profile_terms_profile_id", "profile_terms", ["profile_id"])
    op.create_index("ix_profile_terms_active_window", "profile_terms", ["profile_id", "is_active", "starts_on", "ends_on"])

    op.add_column("inputs", sa.Column("term_id", sa.Integer(), nullable=True))
    op.add_column("inputs", sa.Column("identity_key", sa.String(length=128), nullable=True))
    op.create_foreign_key("fk_inputs_term_id_profile_terms", "inputs", "profile_terms", ["term_id"], ["id"], ondelete="SET NULL")

    op.execute("UPDATE inputs SET identity_key = CONCAT('legacy:', id::text) WHERE identity_key IS NULL")
    op.alter_column("inputs", "identity_key", existing_type=sa.String(length=128), nullable=False)

    op.drop_constraint("uq_inputs_profile_type_normalized_name", "inputs", type_="unique")
    op.create_unique_constraint("uq_inputs_profile_type_identity_key", "inputs", ["profile_id", "type", "identity_key"])

    op.drop_column("inputs", "normalized_name")
    op.drop_column("inputs", "name")


def downgrade() -> None:
    op.add_column("inputs", sa.Column("name", sa.String(length=255), nullable=True))
    op.add_column("inputs", sa.Column("normalized_name", sa.String(length=255), nullable=True))
    op.execute("UPDATE inputs SET name = CONCAT('input-', id::text) WHERE name IS NULL")
    op.execute("UPDATE inputs SET normalized_name = LOWER(name) WHERE normalized_name IS NULL")
    op.alter_column("inputs", "name", existing_type=sa.String(length=255), nullable=False)
    op.alter_column("inputs", "normalized_name", existing_type=sa.String(length=255), nullable=False)

    op.drop_constraint("uq_inputs_profile_type_identity_key", "inputs", type_="unique")
    op.create_unique_constraint("uq_inputs_profile_type_normalized_name", "inputs", ["profile_id", "type", "normalized_name"])

    op.drop_constraint("fk_inputs_term_id_profile_terms", "inputs", type_="foreignkey")
    op.drop_column("inputs", "identity_key")
    op.drop_column("inputs", "term_id")

    op.drop_index("ix_profile_terms_active_window", table_name="profile_terms")
    op.drop_index("ix_profile_terms_profile_id", table_name="profile_terms")
    op.drop_table("profile_terms")
