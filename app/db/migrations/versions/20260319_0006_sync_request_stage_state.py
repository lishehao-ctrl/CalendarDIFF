"""add explicit sync request stage state

Revision ID: 20260319_0006_sync_stage
Revises: 20260319_0005_remove_event_links
Create Date: 2026-03-19 14:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = "20260319_0006_sync_stage"
down_revision = "20260319_0005_remove_event_links"
branch_labels = None
depends_on = None


SYNC_STAGE_ENUM = sa.Enum(
    "connector_fetch",
    "llm_queue",
    "llm_parse",
    "provider_reduce",
    "result_ready",
    "applying",
    "completed",
    "failed",
    name="sync_request_stage",
    native_enum=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "sync_requests" not in inspector.get_table_names():
        return
    existing_columns = {column["name"] for column in inspector.get_columns("sync_requests")}

    if "stage" not in existing_columns:
        op.add_column(
            "sync_requests",
            sa.Column(
                "stage",
                SYNC_STAGE_ENUM,
                nullable=False,
                server_default="connector_fetch",
            ),
        )
    if "substage" not in existing_columns:
        op.add_column("sync_requests", sa.Column("substage", sa.String(length=128), nullable=True))
    if "stage_updated_at" not in existing_columns:
        op.add_column("sync_requests", sa.Column("stage_updated_at", sa.DateTime(timezone=True), nullable=True))
    if "progress_json" not in existing_columns:
        op.add_column("sync_requests", sa.Column("progress_json", sa.JSON(), nullable=True))

    bind.execute(
        text(
            """
            UPDATE sync_requests
            SET stage = CASE
                WHEN status = 'SUCCEEDED' THEN 'completed'
                WHEN status = 'FAILED' THEN 'failed'
                ELSE 'connector_fetch'
            END
            WHERE stage IS NULL OR stage = ''
            """
        )
    )
    bind.execute(
        text(
            """
            UPDATE sync_requests
            SET stage_updated_at = COALESCE(stage_updated_at, updated_at, created_at)
            WHERE stage_updated_at IS NULL
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "sync_requests" not in inspector.get_table_names():
        return
    existing_columns = {column["name"] for column in inspector.get_columns("sync_requests")}
    if "progress_json" in existing_columns:
        op.drop_column("sync_requests", "progress_json")
    if "stage_updated_at" in existing_columns:
        op.drop_column("sync_requests", "stage_updated_at")
    if "substage" in existing_columns:
        op.drop_column("sync_requests", "substage")
    if "stage" in existing_columns:
        op.drop_column("sync_requests", "stage")
    bind.execute(text("DROP TYPE IF EXISTS sync_request_stage"))
