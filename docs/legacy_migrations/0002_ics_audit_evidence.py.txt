"""add ICS evidence references to snapshots and changes

Revision ID: 0002_ics_audit_evidence
Revises: 0001_mvp_schema
Create Date: 2026-02-20 00:20:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0002_ics_audit_evidence"
down_revision = "0001_mvp_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    json_type = postgresql.JSONB() if bind.dialect.name.startswith("postgresql") else sa.JSON()

    snapshot_columns = {column["name"] for column in inspector.get_columns("snapshots")}
    if "retrieved_at" not in snapshot_columns:
        op.add_column(
            "snapshots",
            sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
    if "content_hash" not in snapshot_columns:
        op.add_column("snapshots", sa.Column("content_hash", sa.String(length=64), nullable=False, server_default=""))
    if "raw_evidence_key" not in snapshot_columns:
        op.add_column("snapshots", sa.Column("raw_evidence_key", json_type, nullable=True))

    change_columns = {column["name"] for column in inspector.get_columns("changes")}
    if "before_snapshot_id" not in change_columns:
        op.add_column("changes", sa.Column("before_snapshot_id", sa.Integer(), nullable=True))
    if "after_snapshot_id" not in change_columns:
        op.add_column("changes", sa.Column("after_snapshot_id", sa.Integer(), nullable=True))
    if "evidence_keys" not in change_columns:
        op.add_column("changes", sa.Column("evidence_keys", json_type, nullable=True))

    change_foreign_keys = {fk["name"] for fk in inspector.get_foreign_keys("changes") if fk.get("name")}
    if "fk_changes_before_snapshot_id_snapshots" not in change_foreign_keys:
        op.create_foreign_key(
            "fk_changes_before_snapshot_id_snapshots",
            "changes",
            "snapshots",
            ["before_snapshot_id"],
            ["id"],
            ondelete="SET NULL",
        )
    if "fk_changes_after_snapshot_id_snapshots" not in change_foreign_keys:
        op.create_foreign_key(
            "fk_changes_after_snapshot_id_snapshots",
            "changes",
            "snapshots",
            ["after_snapshot_id"],
            ["id"],
            ondelete="CASCADE",
        )

    op.execute(
        sa.text(
            """
            UPDATE changes AS c
            SET after_snapshot_id = COALESCE(
                (
                    SELECT s.id
                    FROM snapshots AS s
                    WHERE s.source_id = c.source_id
                      AND s.retrieved_at <= c.detected_at
                    ORDER BY s.retrieved_at DESC, s.id DESC
                    LIMIT 1
                ),
                (
                    SELECT s2.id
                    FROM snapshots AS s2
                    WHERE s2.source_id = c.source_id
                    ORDER BY s2.retrieved_at DESC, s2.id DESC
                    LIMIT 1
                )
            )
            WHERE c.after_snapshot_id IS NULL
            """
        )
    )

    unresolved_after_snapshot_ids = bind.execute(
        sa.text("SELECT count(*) FROM changes WHERE after_snapshot_id IS NULL")
    ).scalar_one()
    if unresolved_after_snapshot_ids:
        raise RuntimeError(
            "Unable to backfill changes.after_snapshot_id for all existing rows. "
            "Please repair data before re-running migration."
        )

    op.alter_column("changes", "after_snapshot_id", existing_type=sa.Integer(), nullable=False)


def downgrade() -> None:
    op.alter_column("changes", "after_snapshot_id", existing_type=sa.Integer(), nullable=True)

    op.drop_constraint("fk_changes_after_snapshot_id_snapshots", "changes", type_="foreignkey")
    op.drop_constraint("fk_changes_before_snapshot_id_snapshots", "changes", type_="foreignkey")

    op.drop_column("changes", "evidence_keys")
    op.drop_column("changes", "after_snapshot_id")
    op.drop_column("changes", "before_snapshot_id")
    op.drop_column("snapshots", "raw_evidence_key")
