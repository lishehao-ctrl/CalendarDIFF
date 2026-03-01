"""add llm provider registry and source-level llm bindings

Revision ID: 20260301_0002_llm_gateway
Revises: 20260227_0001_baseline_runtime
Create Date: 2026-03-01 03:10:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260301_0002_llm_gateway"
down_revision = "20260227_0001_baseline_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "llm_providers" not in existing_tables:
        op.create_table(
            "llm_providers",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("provider_id", sa.String(length=64), nullable=False),
            sa.Column("name", sa.String(length=128), nullable=False),
            sa.Column("vendor", sa.String(length=64), nullable=False),
            sa.Column("base_url", sa.Text(), nullable=False),
            sa.Column(
                "api_mode",
                sa.Enum("CHAT_COMPLETIONS", "RESPONSES", name="llm_api_mode", native_enum=False),
                nullable=False,
                server_default="CHAT_COMPLETIONS",
            ),
            sa.Column("model", sa.String(length=255), nullable=False),
            sa.Column("api_key_ref", sa.String(length=128), nullable=False),
            sa.Column("timeout_seconds", sa.Float(), nullable=False, server_default="12"),
            sa.Column("max_retries", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("max_input_chars", sa.Integer(), nullable=False, server_default="12000"),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("extra_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("provider_id", name="uq_llm_providers_provider_id"),
        )

    if "source_llm_bindings" not in existing_tables:
        op.create_table(
            "source_llm_bindings",
            sa.Column("source_id", sa.Integer(), nullable=False),
            sa.Column("llm_provider_id", sa.Integer(), nullable=False),
            sa.Column("model_override", sa.String(length=255), nullable=True),
            sa.Column(
                "api_mode_override",
                sa.Enum("CHAT_COMPLETIONS", "RESPONSES", name="llm_api_mode", native_enum=False),
                nullable=True,
            ),
            sa.Column("prompt_profile", sa.String(length=128), nullable=True),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["llm_provider_id"], ["llm_providers.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["source_id"], ["input_sources.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("source_id"),
        )

    inspector = sa.inspect(bind)
    llm_provider_indexes = (
        {idx["name"] for idx in inspector.get_indexes("llm_providers")}
        if "llm_providers" in set(inspector.get_table_names())
        else set()
    )
    if "ix_llm_providers_enabled_default" not in llm_provider_indexes:
        op.create_index("ix_llm_providers_enabled_default", "llm_providers", ["enabled", "is_default"])

    source_binding_indexes = (
        {idx["name"] for idx in inspector.get_indexes("source_llm_bindings")}
        if "source_llm_bindings" in set(inspector.get_table_names())
        else set()
    )
    if "ix_source_llm_bindings_provider_id" not in source_binding_indexes:
        op.create_index("ix_source_llm_bindings_provider_id", "source_llm_bindings", ["llm_provider_id"])


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_source_llm_bindings_provider_id")
    op.execute("DROP TABLE IF EXISTS source_llm_bindings")
    op.execute("DROP INDEX IF EXISTS ix_llm_providers_enabled_default")
    op.execute("DROP TABLE IF EXISTS llm_providers")
