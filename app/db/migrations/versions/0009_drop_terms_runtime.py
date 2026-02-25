"""drop runtime term subsystem and term-bound columns

Revision ID: 0009_drop_terms_runtime
Revises: 0008_email_review_queue
Create Date: 2026-02-26 20:10:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0009_drop_terms_runtime"
down_revision = "0008_email_review_queue"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names(schema="public")


def _drop_index_if_exists(table_name: str, index_name: str) -> None:
    if not _table_exists(table_name):
        return
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {row["name"] for row in inspector.get_indexes(table_name, schema="public")}
    if index_name in existing:
        op.drop_index(index_name, table_name=table_name)


def _drop_fk_if_exists(table_name: str, fk_name: str) -> None:
    if not _table_exists(table_name):
        return
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {row["name"] for row in inspector.get_foreign_keys(table_name, schema="public")}
    if fk_name in existing:
        op.drop_constraint(fk_name, table_name, type_="foreignkey")


def _drop_column_if_exists(table_name: str, column_name: str) -> None:
    if not _table_exists(table_name):
        return
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {row["name"] for row in inspector.get_columns(table_name, schema="public")}
    if column_name in existing:
        op.drop_column(table_name, column_name)


def upgrade() -> None:
    _drop_index_if_exists("input_term_baselines", "ix_input_term_baselines_input_term")
    if _table_exists("input_term_baselines"):
        op.drop_table("input_term_baselines")

    _drop_index_if_exists("changes", "ix_changes_user_term_id")
    _drop_fk_if_exists("changes", "fk_changes_user_term_id_user_terms")
    _drop_column_if_exists("changes", "user_term_id")

    _drop_index_if_exists("inputs", "ix_inputs_user_term_id")
    _drop_fk_if_exists("inputs", "fk_inputs_user_term_id_user_terms")
    _drop_column_if_exists("inputs", "user_term_id")

    _drop_index_if_exists("user_terms", "ix_user_terms_active_window")
    _drop_index_if_exists("user_terms", "ix_user_terms_user_id")
    if _table_exists("user_terms"):
        op.drop_table("user_terms")


def downgrade() -> None:
    op.create_table(
        "user_terms",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "code", name="uq_user_terms_user_code"),
    )
    op.create_index("ix_user_terms_user_id", "user_terms", ["user_id"])
    op.create_index("ix_user_terms_active_window", "user_terms", ["user_id", "is_active", "starts_on", "ends_on"])

    op.add_column("inputs", sa.Column("user_term_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_inputs_user_term_id_user_terms",
        "inputs",
        "user_terms",
        ["user_term_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_inputs_user_term_id", "inputs", ["user_term_id"])

    op.add_column("changes", sa.Column("user_term_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_changes_user_term_id_user_terms",
        "changes",
        "user_terms",
        ["user_term_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_changes_user_term_id", "changes", ["user_term_id"])

    op.create_table(
        "input_term_baselines",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("input_id", sa.Integer(), sa.ForeignKey("inputs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_term_id", sa.Integer(), sa.ForeignKey("user_terms.id", ondelete="CASCADE"), nullable=False),
        sa.Column("first_snapshot_id", sa.Integer(), sa.ForeignKey("snapshots.id", ondelete="SET NULL"), nullable=True),
        sa.Column("established_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("mode", sa.String(length=32), nullable=False, server_default=sa.text("'auto_silent'")),
        sa.UniqueConstraint("input_id", "user_term_id", name="uq_input_term_baselines_input_term"),
    )
    op.create_index("ix_input_term_baselines_input_term", "input_term_baselines", ["input_id", "user_term_id"])
