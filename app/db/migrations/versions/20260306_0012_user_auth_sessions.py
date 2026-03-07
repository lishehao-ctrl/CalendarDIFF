"""add user auth fields and session table

Revision ID: 20260306_0012_user_auth_sessions
Revises: 20260304_0011_drop_email_audit
Create Date: 2026-03-06 18:10:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260306_0012_user_auth_sessions"
down_revision = "20260304_0011_drop_email_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "password_hash" not in user_columns:
        op.add_column("users", sa.Column("password_hash", sa.Text(), nullable=True))
    if "updated_at" not in user_columns:
        op.add_column(
            "users",
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )

    existing_uniques = {constraint["name"] for constraint in inspector.get_unique_constraints("users") if constraint.get("name")}
    if "uq_users_notify_email" not in existing_uniques:
        op.create_unique_constraint("uq_users_notify_email", "users", ["notify_email"])

    tables = set(inspector.get_table_names())
    if "user_sessions" not in tables:
        op.create_table(
            "user_sessions",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("session_id", sa.String(length=128), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("session_id", name="uq_user_sessions_session_id"),
        )
        op.create_index("ix_user_sessions_user_expires", "user_sessions", ["user_id", "expires_at"])
        op.create_index("ix_user_sessions_expires", "user_sessions", ["expires_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "user_sessions" in tables:
        indexes = {index["name"] for index in inspector.get_indexes("user_sessions") if index.get("name")}
        if "ix_user_sessions_expires" in indexes:
            op.drop_index("ix_user_sessions_expires", table_name="user_sessions")
        if "ix_user_sessions_user_expires" in indexes:
            op.drop_index("ix_user_sessions_user_expires", table_name="user_sessions")
        op.drop_table("user_sessions")

    existing_uniques = {constraint["name"] for constraint in inspector.get_unique_constraints("users") if constraint.get("name")}
    if "uq_users_notify_email" in existing_uniques:
        op.drop_constraint("uq_users_notify_email", "users", type_="unique")

    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "updated_at" in user_columns:
        op.drop_column("users", "updated_at")
    if "password_hash" in user_columns:
        op.drop_column("users", "password_hash")
