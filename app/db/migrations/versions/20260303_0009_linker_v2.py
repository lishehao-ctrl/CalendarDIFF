"""add linker v2 normalized tables

Revision ID: 20260303_0009_linker_v2
Revises: 20260303_0008_event_entities
Create Date: 2026-03-03 12:10:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260303_0009_linker_v2"
down_revision = "20260303_0008_event_entities"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "event_entity_links" not in tables:
        op.create_table(
            "event_entity_links",
            sa.Column("id", sa.BigInteger(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("entity_uid", sa.String(length=128), nullable=False),
            sa.Column("source_id", sa.Integer(), nullable=False),
            sa.Column(
                "source_kind",
                sa.Enum("calendar", "email", "task", "exam", "announcement", name="source_kind", native_enum=False),
                nullable=False,
            ),
            sa.Column(
                "link_origin",
                sa.Enum("auto", "manual_candidate", name="event_link_origin", native_enum=False),
                nullable=False,
                server_default="auto",
            ),
            sa.Column("external_event_id", sa.String(length=255), nullable=False),
            sa.Column("link_score", sa.Float(), nullable=True),
            sa.Column("signals_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["source_id"], ["input_sources.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "user_id",
                "source_id",
                "external_event_id",
                name="uq_event_entity_links_user_source_external",
            ),
        )
        op.create_index("ix_event_entity_links_user_entity", "event_entity_links", ["user_id", "entity_uid"])
        op.create_index("ix_event_entity_links_source_external", "event_entity_links", ["source_id", "external_event_id"])

    if "event_link_candidates" not in tables:
        op.create_table(
            "event_link_candidates",
            sa.Column("id", sa.BigInteger(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("source_id", sa.Integer(), nullable=False),
            sa.Column("external_event_id", sa.String(length=255), nullable=False),
            sa.Column("proposed_entity_uid", sa.String(length=128), nullable=True),
            sa.Column("score", sa.Float(), nullable=True),
            sa.Column("score_breakdown_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
            sa.Column(
                "reason_code",
                sa.Enum(
                    "score_band",
                    "no_time_anchor",
                    "low_confidence",
                    name="event_link_candidate_reason",
                    native_enum=False,
                ),
                nullable=False,
            ),
            sa.Column(
                "status",
                sa.Enum("pending", "approved", "rejected", name="event_link_candidate_status", native_enum=False),
                nullable=False,
                server_default="pending",
            ),
            sa.Column("reviewed_by_user_id", sa.Integer(), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("review_note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["source_id"], ["input_sources.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "user_id",
                "source_id",
                "external_event_id",
                "proposed_entity_uid",
                "status",
                name="uq_event_link_candidates_user_pair_entity_status",
            ),
        )
        op.create_index(
            "ix_event_link_candidates_user_status_created",
            "event_link_candidates",
            ["user_id", "status", "created_at"],
        )
        op.create_index(
            "ix_event_link_candidates_source_external",
            "event_link_candidates",
            ["source_id", "external_event_id"],
        )

    if "event_link_blocks" not in tables:
        op.create_table(
            "event_link_blocks",
            sa.Column("id", sa.BigInteger(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("source_id", sa.Integer(), nullable=False),
            sa.Column("external_event_id", sa.String(length=255), nullable=False),
            sa.Column("blocked_entity_uid", sa.String(length=128), nullable=False),
            sa.Column("created_by_user_id", sa.Integer(), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["source_id"], ["input_sources.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "user_id",
                "source_id",
                "external_event_id",
                "blocked_entity_uid",
                name="uq_event_link_blocks_user_source_external_entity",
            ),
        )
        op.create_index("ix_event_link_blocks_source_external", "event_link_blocks", ["source_id", "external_event_id"])


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_event_link_blocks_source_external")
    op.execute("DROP TABLE IF EXISTS event_link_blocks")

    op.execute("DROP INDEX IF EXISTS ix_event_link_candidates_source_external")
    op.execute("DROP INDEX IF EXISTS ix_event_link_candidates_user_status_created")
    op.execute("DROP TABLE IF EXISTS event_link_candidates")

    op.execute("DROP INDEX IF EXISTS ix_event_entity_links_source_external")
    op.execute("DROP INDEX IF EXISTS ix_event_entity_links_user_entity")
    op.execute("DROP TABLE IF EXISTS event_entity_links")
