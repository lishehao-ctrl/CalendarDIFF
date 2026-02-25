"""drop legacy review_candidates domain and fold remaining rows into email queue

Revision ID: 0010_drop_review_candidates
Revises: 0009_drop_terms_runtime
Create Date: 2026-02-26 23:15:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0010_drop_review_candidates"
down_revision = "0009_drop_terms_runtime"
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


def _drop_table_if_exists(table_name: str) -> None:
    if _table_exists(table_name):
        op.drop_table(table_name)


def _backfill_email_rule_candidates() -> None:
    if not _table_exists("email_rule_candidates"):
        return
    if not _table_exists("email_messages"):
        return

    op.execute(
        sa.text(
            """
            INSERT INTO email_messages (
                email_id,
                user_id,
                from_addr,
                subject,
                date_rfc822,
                received_at,
                evidence_key
            )
            SELECT
                c.gmail_message_id,
                c.user_id,
                c.from_header,
                c.subject,
                NULL,
                COALESCE(c.created_at, now()),
                CASE
                    WHEN c.source_change_id IS NULL THEN
                        jsonb_build_object('kind', 'review_candidate_backfill', 'gmail_message_id', c.gmail_message_id)
                    ELSE
                        jsonb_build_object(
                            'kind',
                            'review_candidate_backfill',
                            'gmail_message_id',
                            c.gmail_message_id,
                            'source_change_id',
                            c.source_change_id
                        )
                END
            FROM email_rule_candidates c
            ON CONFLICT (email_id) DO UPDATE
            SET
                user_id = EXCLUDED.user_id,
                from_addr = COALESCE(email_messages.from_addr, EXCLUDED.from_addr),
                subject = COALESCE(email_messages.subject, EXCLUDED.subject),
                evidence_key = COALESCE(email_messages.evidence_key, EXCLUDED.evidence_key)
            """
        )
    )

    op.execute(
        sa.text(
            """
            INSERT INTO email_rule_labels (
                email_id,
                label,
                confidence,
                reasons,
                course_hints,
                event_type,
                raw_extract,
                notes
            )
            SELECT
                c.gmail_message_id,
                'KEEP',
                COALESCE(c.confidence, 0),
                COALESCE(c.reasons::jsonb, '[]'::jsonb),
                CASE
                    WHEN c.proposed_course_hint IS NULL OR btrim(c.proposed_course_hint) = '' THEN '[]'::jsonb
                    ELSE jsonb_build_array(c.proposed_course_hint)
                END,
                c.proposed_event_type,
                COALESCE(c.raw_extract::jsonb, '{}'::jsonb),
                NULL
            FROM email_rule_candidates c
            ON CONFLICT (email_id) DO UPDATE
            SET
                label = EXCLUDED.label,
                confidence = EXCLUDED.confidence,
                reasons = EXCLUDED.reasons,
                course_hints = EXCLUDED.course_hints,
                event_type = EXCLUDED.event_type,
                raw_extract = EXCLUDED.raw_extract,
                notes = COALESCE(email_rule_labels.notes, EXCLUDED.notes)
            """
        )
    )

    op.execute(
        sa.text(
            """
            INSERT INTO email_action_items (email_id, action, due_iso, where_text)
            SELECT
                c.gmail_message_id,
                CASE
                    WHEN c.proposed_title IS NOT NULL AND btrim(c.proposed_title) <> '' THEN c.proposed_title
                    ELSE 'Review timeline update'
                END,
                CASE
                    WHEN c.proposed_due_at IS NOT NULL THEN to_char(c.proposed_due_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
                    ELSE NULL
                END,
                NULL
            FROM email_rule_candidates c
            WHERE NOT EXISTS (
                SELECT 1 FROM email_action_items ai WHERE ai.email_id = c.gmail_message_id
            )
            """
        )
    )

    op.execute(
        sa.text(
            """
            INSERT INTO email_rule_analysis (email_id, event_flags, matched_snippets, drop_reason_codes)
            SELECT
                c.gmail_message_id,
                CASE
                    WHEN c.proposed_event_type IS NULL THEN '{}'::jsonb
                    ELSE jsonb_build_object(c.proposed_event_type, true)
                END,
                CASE
                    WHEN c.snippet IS NULL OR btrim(c.snippet) = '' THEN '[]'::jsonb
                    ELSE jsonb_build_array(jsonb_build_object('rule', COALESCE(c.proposed_event_type, 'candidate'), 'snippet', left(c.snippet, 240)))
                END,
                '[]'::jsonb
            FROM email_rule_candidates c
            ON CONFLICT (email_id) DO UPDATE
            SET
                event_flags = CASE
                    WHEN email_rule_analysis.event_flags = '{}'::jsonb THEN EXCLUDED.event_flags
                    ELSE email_rule_analysis.event_flags
                END,
                matched_snippets = CASE
                    WHEN email_rule_analysis.matched_snippets = '[]'::jsonb THEN EXCLUDED.matched_snippets
                    ELSE email_rule_analysis.matched_snippets
                END,
                drop_reason_codes = CASE
                    WHEN email_rule_analysis.drop_reason_codes = '[]'::jsonb THEN EXCLUDED.drop_reason_codes
                    ELSE email_rule_analysis.drop_reason_codes
                END
            """
        )
    )

    op.execute(
        sa.text(
            """
            INSERT INTO email_routes (email_id, route, routed_at, viewed_at, notified_at)
            SELECT
                c.gmail_message_id,
                CASE c.status
                    WHEN 'pending' THEN 'review'
                    WHEN 'applied' THEN 'archive'
                    WHEN 'dismissed' THEN 'drop'
                    WHEN 'failed' THEN 'archive'
                    ELSE 'review'
                END,
                COALESCE(c.updated_at, c.created_at, now()),
                CASE c.status
                    WHEN 'applied' THEN COALESCE(c.applied_at, c.updated_at, c.created_at)
                    WHEN 'dismissed' THEN COALESCE(c.dismissed_at, c.updated_at, c.created_at)
                    ELSE NULL
                END,
                NULL
            FROM email_rule_candidates c
            ON CONFLICT (email_id) DO NOTHING
            """
        )
    )


def upgrade() -> None:
    _backfill_email_rule_candidates()
    _drop_index_if_exists("email_rule_candidates", "ix_email_rule_candidates_user_status_created")
    _drop_table_if_exists("email_rule_candidates")


review_candidate_status_enum = sa.Enum(
    "pending",
    "applied",
    "dismissed",
    "failed",
    name="review_candidate_status",
    native_enum=False,
)


def downgrade() -> None:
    op.create_table(
        "email_rule_candidates",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("input_id", sa.Integer(), sa.ForeignKey("inputs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("gmail_message_id", sa.Text(), nullable=False),
        sa.Column("source_change_id", sa.Integer(), sa.ForeignKey("changes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", review_candidate_status_enum, nullable=False, server_default="pending"),
        sa.Column("rule_version", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("proposed_event_type", sa.String(length=32), nullable=True),
        sa.Column("proposed_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("proposed_title", sa.String(length=512), nullable=True),
        sa.Column("proposed_course_hint", sa.String(length=128), nullable=True),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("raw_extract", sa.JSON(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("from_header", sa.Text(), nullable=True),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("applied_change_id", sa.Integer(), sa.ForeignKey("changes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "input_id",
            "gmail_message_id",
            "rule_version",
            name="uq_email_rule_candidates_input_message_rule",
        ),
    )
    op.create_index(
        "ix_email_rule_candidates_user_status_created",
        "email_rule_candidates",
        ["user_id", "status", "created_at"],
    )
