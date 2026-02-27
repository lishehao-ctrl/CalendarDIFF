"""drop remaining profile schema for user-only model

Revision ID: 0005_drop_profile_schema
Revises: 0004_user_terms_digest
Create Date: 2026-02-25 10:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "0005_drop_profile_schema"
down_revision = "0004_user_terms_digest"
branch_labels = None
depends_on = None


def _drop_fk_constraints_for_columns(table_name: str, columns: tuple[str, ...]) -> None:
    bind = op.get_bind()
    cols = ", ".join(f"'{value}'" for value in columns)
    rows = bind.execute(
        sa.text(
            f"""
            SELECT c.conname
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            JOIN unnest(c.conkey) AS colnum(attnum) ON TRUE
            JOIN pg_attribute a
              ON a.attrelid = t.oid
             AND a.attnum = colnum.attnum
            WHERE n.nspname = 'public'
              AND t.relname = :table_name
              AND c.contype = 'f'
              AND a.attname IN ({cols})
            """
        ),
        {"table_name": table_name},
    ).fetchall()
    for (constraint_name,) in rows:
        op.drop_constraint(constraint_name, table_name, type_="foreignkey")


def upgrade() -> None:
    _drop_fk_constraints_for_columns("inputs", ("profile_id", "term_id"))

    op.drop_constraint("uq_inputs_profile_type_identity_key", "inputs", type_="unique")
    op.drop_index("ix_inputs_profile_id", table_name="inputs")

    op.create_unique_constraint(
        "uq_inputs_user_type_identity_key",
        "inputs",
        ["user_id", "type", "identity_key"],
    )

    op.drop_column("inputs", "term_id")
    op.drop_column("inputs", "profile_id")

    op.drop_index("ix_profile_terms_active_window", table_name="profile_terms")
    op.drop_index("ix_profile_terms_profile_id", table_name="profile_terms")
    op.drop_table("profile_terms")

    op.drop_index("ix_profiles_user_id", table_name="profiles")
    op.drop_table("profiles")


def downgrade() -> None:
    op.create_table(
        "profiles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("normalized_name", sa.String(length=255), nullable=False),
        sa.Column("notify_email", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("calendar_delay_seconds", sa.Integer(), nullable=False, server_default=sa.text("120")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "normalized_name", name="uq_profiles_user_normalized_name"),
    )
    op.create_index("ix_profiles_user_id", "profiles", ["user_id"])

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
    )
    op.create_index("ix_profile_terms_profile_id", "profile_terms", ["profile_id"])
    op.create_index("ix_profile_terms_active_window", "profile_terms", ["profile_id", "is_active", "starts_on", "ends_on"])

    op.add_column("inputs", sa.Column("profile_id", sa.Integer(), nullable=True))
    op.add_column("inputs", sa.Column("term_id", sa.Integer(), nullable=True))

    op.create_foreign_key(
        "fk_inputs_profile_id_profiles",
        "inputs",
        "profiles",
        ["profile_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_inputs_term_id_profile_terms",
        "inputs",
        "profile_terms",
        ["term_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.drop_constraint("uq_inputs_user_type_identity_key", "inputs", type_="unique")
    op.create_index("ix_inputs_profile_id", "inputs", ["profile_id"])
    op.create_unique_constraint(
        "uq_inputs_profile_type_identity_key",
        "inputs",
        ["profile_id", "type", "identity_key"],
    )
