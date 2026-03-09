"""add user work item kind mappings

Revision ID: 20260309_0013_kind_mappings
Revises: 20260306_0012_user_auth_sessions
Create Date: 2026-03-09 10:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260309_0013_kind_mappings"
down_revision = "20260306_0012_user_auth_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "work_item_mappings_state" not in user_columns:
        op.add_column(
            "users",
            sa.Column("work_item_mappings_state", sa.String(length=32), nullable=False, server_default="idle"),
        )
    if "work_item_mappings_last_rebuilt_at" not in user_columns:
        op.add_column("users", sa.Column("work_item_mappings_last_rebuilt_at", sa.DateTime(timezone=True), nullable=True))
    if "work_item_mappings_last_error" not in user_columns:
        op.add_column("users", sa.Column("work_item_mappings_last_error", sa.Text(), nullable=True))

    tables = set(inspector.get_table_names())
    if "user_work_item_kind_mappings" not in tables:
        op.create_table(
            "user_work_item_kind_mappings",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(length=128), nullable=False),
            sa.Column("normalized_name", sa.String(length=128), nullable=False),
            sa.Column("aliases_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("user_id", "normalized_name", name="uq_user_work_item_kind_mappings_user_normalized_name"),
        )
        op.create_index(
            "ix_user_work_item_kind_mappings_user_updated",
            "user_work_item_kind_mappings",
            ["user_id", "updated_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "user_work_item_kind_mappings" in tables:
        indexes = {index["name"] for index in inspector.get_indexes("user_work_item_kind_mappings") if index.get("name")}
        if "ix_user_work_item_kind_mappings_user_updated" in indexes:
            op.drop_index("ix_user_work_item_kind_mappings_user_updated", table_name="user_work_item_kind_mappings")
        op.drop_table("user_work_item_kind_mappings")

    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "work_item_mappings_last_error" in user_columns:
        op.drop_column("users", "work_item_mappings_last_error")
    if "work_item_mappings_last_rebuilt_at" in user_columns:
        op.drop_column("users", "work_item_mappings_last_rebuilt_at")
    if "work_item_mappings_state" in user_columns:
        op.drop_column("users", "work_item_mappings_state")
