"""archive removed legacy change types and tighten change_type constraint

Revision ID: 0014_archive_legacy_change_types
Revises: 0013_core_runtime_ddl_alert
Create Date: 2026-02-28 14:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0014_archive_legacy_change_types"
down_revision = "0013_core_runtime_ddl_alert"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names(schema="public")


def _drop_change_type_check_constraints() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT c.conname
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE n.nspname = 'public'
              AND t.relname = 'changes'
              AND c.contype = 'c'
              AND pg_get_constraintdef(c.oid) ILIKE '%change_type%'
            """
        )
    ).all()
    for (name,) in rows:
        op.execute(sa.text(f'ALTER TABLE changes DROP CONSTRAINT IF EXISTS "{name}"'))


def upgrade() -> None:
    if not _table_exists("changes_legacy_archive"):
        op.create_table(
            "changes_legacy_archive",
            sa.Column("archive_id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("original_change_id", sa.Integer(), nullable=False),
            sa.Column("input_id", sa.Integer(), nullable=False),
            sa.Column("event_uid", sa.String(length=255), nullable=False),
            sa.Column("change_type", sa.String(length=64), nullable=False),
            sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("before_json", sa.JSON(), nullable=True),
            sa.Column("after_json", sa.JSON(), nullable=True),
            sa.Column("delta_seconds", sa.Integer(), nullable=True),
            sa.Column("viewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("viewed_note", sa.Text(), nullable=True),
            sa.Column("before_snapshot_id", sa.Integer(), nullable=True),
            sa.Column("after_snapshot_id", sa.Integer(), nullable=False),
            sa.Column("evidence_keys", sa.JSON(), nullable=True),
            sa.Column(
                "archived_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "archive_reason",
                sa.String(length=64),
                nullable=False,
                server_default="deprecated_change_type",
            ),
            sa.UniqueConstraint("original_change_id", name="uq_changes_legacy_archive_original_change_id"),
        )
        op.create_index(
            "ix_changes_legacy_archive_change_type_detected",
            "changes_legacy_archive",
            ["change_type", "detected_at"],
        )

    op.execute(
        sa.text(
            """
            INSERT INTO changes_legacy_archive (
                original_change_id,
                input_id,
                event_uid,
                change_type,
                detected_at,
                before_json,
                after_json,
                delta_seconds,
                viewed_at,
                viewed_note,
                before_snapshot_id,
                after_snapshot_id,
                evidence_keys,
                archive_reason
            )
            SELECT
                c.id,
                c.input_id,
                c.event_uid,
                c.change_type,
                c.detected_at,
                c.before_json,
                c.after_json,
                c.delta_seconds,
                c.viewed_at,
                c.viewed_note,
                c.before_snapshot_id,
                c.after_snapshot_id,
                c.evidence_keys,
                'deprecated_change_type'
            FROM changes c
            WHERE lower(c.change_type) IN ('title_changed', 'course_changed')
            ON CONFLICT (original_change_id) DO NOTHING
            """
        )
    )

    op.execute(
        sa.text(
            """
            DELETE FROM changes
            WHERE lower(change_type) IN ('title_changed', 'course_changed')
            """
        )
    )

    _drop_change_type_check_constraints()
    op.create_check_constraint(
        "ck_changes_change_type",
        "changes",
        "change_type IN ('CREATED', 'REMOVED', 'DUE_CHANGED')",
    )


def downgrade() -> None:
    _drop_change_type_check_constraints()
    op.create_check_constraint(
        "ck_changes_change_type",
        "changes",
        "change_type IN ('CREATED', 'REMOVED', 'DUE_CHANGED', 'TITLE_CHANGED', 'COURSE_CHANGED')",
    )

    if _table_exists("changes_legacy_archive"):
        op.execute(
            sa.text(
                """
                INSERT INTO changes (
                    id,
                    input_id,
                    event_uid,
                    change_type,
                    detected_at,
                    before_json,
                    after_json,
                    delta_seconds,
                    viewed_at,
                    viewed_note,
                    before_snapshot_id,
                    after_snapshot_id,
                    evidence_keys
                )
                SELECT
                    a.original_change_id,
                    a.input_id,
                    a.event_uid,
                    upper(a.change_type),
                    a.detected_at,
                    a.before_json,
                    a.after_json,
                    a.delta_seconds,
                    a.viewed_at,
                    a.viewed_note,
                    a.before_snapshot_id,
                    a.after_snapshot_id,
                    a.evidence_keys
                FROM changes_legacy_archive a
                WHERE lower(a.change_type) IN ('title_changed', 'course_changed')
                  AND EXISTS (SELECT 1 FROM inputs i WHERE i.id = a.input_id)
                  AND EXISTS (SELECT 1 FROM snapshots s_after WHERE s_after.id = a.after_snapshot_id)
                  AND (
                    a.before_snapshot_id IS NULL
                    OR EXISTS (SELECT 1 FROM snapshots s_before WHERE s_before.id = a.before_snapshot_id)
                  )
                ON CONFLICT (id) DO NOTHING
                """
            )
        )
        op.drop_index(
            "ix_changes_legacy_archive_change_type_detected",
            table_name="changes_legacy_archive",
        )
        op.drop_table("changes_legacy_archive")
