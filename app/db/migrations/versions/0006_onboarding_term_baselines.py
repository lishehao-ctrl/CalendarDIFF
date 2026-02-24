"""onboarding completion + change-level term attribution + input-term baselines

Revision ID: 0006_onboarding_term_baselines
Revises: 0005_drop_profile_schema
Create Date: 2026-02-26 10:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "0006_onboarding_term_baselines"
down_revision = "0005_drop_profile_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("onboarding_completed_at", sa.DateTime(timezone=True), nullable=True))

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

    # Existing users with notify_email and at least one ICS snapshot are treated as onboarding-complete.
    op.execute(
        """
        UPDATE users AS u
        SET onboarding_completed_at = COALESCE(u.onboarding_completed_at, now())
        WHERE u.notify_email IS NOT NULL
          AND btrim(u.notify_email) <> ''
          AND EXISTS (
            SELECT 1
            FROM inputs AS i
            JOIN snapshots AS s ON s.input_id = i.id
            WHERE i.user_id = u.id
              AND i.type = 'ics'
          )
        """
    )

    # Backfill change-level term attribution using event start time mapped to user term windows.
    op.execute(
        """
        WITH candidates AS (
          SELECT
            c.id AS change_id,
            i.user_id AS user_id,
            COALESCE(p.timezone, 'UTC') AS timezone_name,
            CASE
              WHEN c.change_type = 'removed' THEN c.before_json ->> 'start_at_utc'
              ELSE c.after_json ->> 'start_at_utc'
            END AS event_start_raw
          FROM changes AS c
          JOIN inputs AS i ON i.id = c.input_id
          LEFT JOIN user_notification_prefs AS p ON p.user_id = i.user_id
          WHERE c.user_term_id IS NULL
        ),
        parsed AS (
          SELECT
            candidates.change_id,
            candidates.user_id,
            candidates.timezone_name,
            CASE
              WHEN candidates.event_start_raw ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T'
                THEN (candidates.event_start_raw)::timestamptz
              ELSE NULL
            END AS event_start_ts
          FROM candidates
        ),
        matched AS (
          SELECT
            parsed.change_id,
            (
              SELECT ut.id
              FROM user_terms AS ut
              WHERE ut.user_id = parsed.user_id
                AND ((parsed.event_start_ts AT TIME ZONE parsed.timezone_name)::date BETWEEN ut.starts_on AND ut.ends_on)
              ORDER BY ut.starts_on ASC, ut.id ASC
              LIMIT 1
            ) AS user_term_id
          FROM parsed
          WHERE parsed.event_start_ts IS NOT NULL
        )
        UPDATE changes AS c
        SET user_term_id = matched.user_term_id
        FROM matched
        WHERE c.id = matched.change_id
          AND matched.user_term_id IS NOT NULL
        """
    )

    # Seed historical term baselines so migration does not re-silence previously active terms.
    op.execute(
        """
        INSERT INTO input_term_baselines (input_id, user_term_id, first_snapshot_id, established_at, mode)
        SELECT
          c.input_id,
          c.user_term_id,
          MIN(c.after_snapshot_id) AS first_snapshot_id,
          COALESCE(MIN(c.detected_at), now()) AS established_at,
          'auto_silent' AS mode
        FROM changes AS c
        JOIN inputs AS i ON i.id = c.input_id
        WHERE i.type = 'ics'
          AND c.user_term_id IS NOT NULL
        GROUP BY c.input_id, c.user_term_id
        ON CONFLICT (input_id, user_term_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_input_term_baselines_input_term", table_name="input_term_baselines")
    op.drop_table("input_term_baselines")

    op.drop_index("ix_changes_user_term_id", table_name="changes")
    op.drop_constraint("fk_changes_user_term_id_user_terms", "changes", type_="foreignkey")
    op.drop_column("changes", "user_term_id")

    op.drop_column("users", "onboarding_completed_at")
