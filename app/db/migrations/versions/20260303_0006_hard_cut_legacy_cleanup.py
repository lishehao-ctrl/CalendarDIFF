"""hard cut cleanup for legacy bridge/runtime and canonical-only inputs

Revision ID: 20260303_0006_hard_cut_cleanup
Revises: 20260302_0005_review_pool
Create Date: 2026-03-03 00:00:00.000000
"""

from __future__ import annotations

from alembic import op


revision = "20260303_0006_hard_cut_cleanup"
down_revision = "20260302_0005_review_pool"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Legacy source<->input bridge is removed from runtime.
    op.execute("DROP INDEX IF EXISTS ix_source_legacy_inputs_input_id")
    op.execute("DROP TABLE IF EXISTS source_legacy_inputs")

    # Legacy sync_runs runtime table is removed.
    op.execute("DROP INDEX IF EXISTS ix_sync_runs_input_started_desc")
    op.execute("DROP INDEX IF EXISTS ix_sync_runs_started_at")
    op.execute("DROP INDEX IF EXISTS ix_sync_runs_status_started_at")
    op.execute("DROP TABLE IF EXISTS sync_runs")

    # Inputs table is now canonical-only minimal shape.
    op.execute("DROP INDEX IF EXISTS ix_inputs_active_last_checked")
    op.execute("DROP INDEX IF EXISTS ix_inputs_due_lookup")
    op.execute("ALTER TABLE inputs DROP CONSTRAINT IF EXISTS ck_inputs_interval_minutes_fixed_15")
    op.execute("ALTER TABLE inputs DROP COLUMN IF EXISTS encrypted_url")
    op.execute("ALTER TABLE inputs DROP COLUMN IF EXISTS gmail_label")
    op.execute("ALTER TABLE inputs DROP COLUMN IF EXISTS gmail_from_contains")
    op.execute("ALTER TABLE inputs DROP COLUMN IF EXISTS gmail_subject_keywords")
    op.execute("ALTER TABLE inputs DROP COLUMN IF EXISTS gmail_history_id")
    op.execute("ALTER TABLE inputs DROP COLUMN IF EXISTS gmail_account_email")
    op.execute("ALTER TABLE inputs DROP COLUMN IF EXISTS encrypted_access_token")
    op.execute("ALTER TABLE inputs DROP COLUMN IF EXISTS encrypted_refresh_token")
    op.execute("ALTER TABLE inputs DROP COLUMN IF EXISTS access_token_expires_at")
    op.execute("ALTER TABLE inputs DROP COLUMN IF EXISTS etag")
    op.execute("ALTER TABLE inputs DROP COLUMN IF EXISTS last_modified")
    op.execute("ALTER TABLE inputs DROP COLUMN IF EXISTS last_content_hash")
    op.execute("ALTER TABLE inputs DROP COLUMN IF EXISTS notify_email")
    op.execute("ALTER TABLE inputs DROP COLUMN IF EXISTS interval_minutes")
    op.execute("ALTER TABLE inputs DROP COLUMN IF EXISTS last_checked_at")
    op.execute("ALTER TABLE inputs DROP COLUMN IF EXISTS last_ok_at")
    op.execute("ALTER TABLE inputs DROP COLUMN IF EXISTS last_change_detected_at")
    op.execute("ALTER TABLE inputs DROP COLUMN IF EXISTS last_error_at")
    op.execute("ALTER TABLE inputs DROP COLUMN IF EXISTS last_email_sent_at")
    op.execute("ALTER TABLE inputs DROP COLUMN IF EXISTS last_error")
    op.execute("ALTER TABLE inputs DROP COLUMN IF EXISTS provider")

    # Drop now-unused enum types from legacy sync runtime.
    op.execute("DROP TYPE IF EXISTS sync_run_status")
    op.execute("DROP TYPE IF EXISTS sync_trigger_type")


def downgrade() -> None:
    raise RuntimeError("irreversible migration: legacy cleanup hard cut")
