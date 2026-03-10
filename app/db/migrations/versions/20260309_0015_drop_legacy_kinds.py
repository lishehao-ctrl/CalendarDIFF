"""drop legacy user kind mappings

Revision ID: 20260309_0015_drop_legacy_kinds
Revises: 20260309_0014_course_families
Create Date: 2026-03-09 16:05:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260309_0015_drop_legacy_kinds"
down_revision = "20260309_0014_course_families"
branch_labels = None
depends_on = None


_TABLE_NAME = "user_work_item_kind_mappings"
_INDEX_NAME = "ix_user_work_item_kind_mappings_user_updated"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if _TABLE_NAME not in tables:
        return
    indexes = {index["name"] for index in inspector.get_indexes(_TABLE_NAME) if index.get("name")}
    if _INDEX_NAME in indexes:
        op.drop_index(_INDEX_NAME, table_name=_TABLE_NAME)
    op.drop_table(_TABLE_NAME)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if _TABLE_NAME in tables:
        return
    op.create_table(
        _TABLE_NAME,
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("normalized_name", sa.String(length=128), nullable=False),
        sa.Column("aliases_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("user_id", "normalized_name", name="uq_user_work_item_kind_mappings_user_normalized_name"),
    )
    op.create_index(_INDEX_NAME, _TABLE_NAME, ["user_id", "updated_at"])
