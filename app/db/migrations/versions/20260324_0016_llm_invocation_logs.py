"""add llm invocation logs

Revision ID: 20260324_0016_llm_inv_logs
Revises: 20260324_0017_mcp_audit
Create Date: 2026-03-24 18:10:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260324_0016_llm_inv_logs"
down_revision = "20260324_0017_mcp_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "llm_invocation_logs" in inspector.get_table_names():
        return

    op.create_table(
        "llm_invocation_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("task_name", sa.String(length=128), nullable=False),
        sa.Column("profile_family", sa.String(length=32), nullable=False),
        sa.Column("route_id", sa.String(length=255), nullable=False),
        sa.Column("route_index", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("provider_id", sa.String(length=64), nullable=False),
        sa.Column("vendor", sa.String(length=64), nullable=False),
        sa.Column("protocol", sa.String(length=64), nullable=False, server_default="responses"),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("session_cache_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("upstream_request_id", sa.String(length=128), nullable=True),
        sa.Column("response_id", sa.String(length=128), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("retryable", sa.Boolean(), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("usage_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_llm_invocation_logs_created", "llm_invocation_logs", ["created_at"])
    op.create_index("ix_llm_invocation_logs_request", "llm_invocation_logs", ["request_id", "created_at"])
    op.create_index("ix_llm_invocation_logs_source_task", "llm_invocation_logs", ["source_id", "task_name", "created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "llm_invocation_logs" not in inspector.get_table_names():
        return
    op.drop_index("ix_llm_invocation_logs_source_task", table_name="llm_invocation_logs")
    op.drop_index("ix_llm_invocation_logs_request", table_name="llm_invocation_logs")
    op.drop_index("ix_llm_invocation_logs_created", table_name="llm_invocation_logs")
    op.drop_table("llm_invocation_logs")
