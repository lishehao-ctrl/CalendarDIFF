"""add course work item label families

Revision ID: 20260309_0014_course_families
Revises: 20260309_0013_kind_mappings
Create Date: 2026-03-09 15:10:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260309_0014_course_families"
down_revision = "20260309_0013_kind_mappings"
branch_labels = None
depends_on = None


_TABLE_NAME = "course_work_item_label_families"
_INDEX_NAME = "ix_course_work_item_families_user_course_updated"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if _TABLE_NAME not in tables:
        op.create_table(
            _TABLE_NAME,
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("course_key", sa.String(length=128), nullable=False),
            sa.Column("normalized_course_key", sa.String(length=128), nullable=False),
            sa.Column("canonical_label", sa.String(length=128), nullable=False),
            sa.Column("normalized_canonical_label", sa.String(length=128), nullable=False),
            sa.Column("aliases_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("user_id", "normalized_course_key", "normalized_canonical_label", name="uq_course_work_item_families_user_course_label"),
        )
        op.create_index(_INDEX_NAME, _TABLE_NAME, ["user_id", "normalized_course_key", "updated_at"])
        return

    indexes = {index["name"] for index in inspector.get_indexes(_TABLE_NAME) if index.get("name")}
    if _INDEX_NAME not in indexes:
        op.create_index(_INDEX_NAME, _TABLE_NAME, ["user_id", "normalized_course_key", "updated_at"])



def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if _TABLE_NAME not in tables:
        return
    indexes = {index["name"] for index in inspector.get_indexes(_TABLE_NAME) if index.get("name")}
    if _INDEX_NAME in indexes:
        op.drop_index(_INDEX_NAME, table_name=_TABLE_NAME)
    op.drop_table(_TABLE_NAME)
