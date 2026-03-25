"""hard-cut user identity to email-only

Revision ID: 20260325_0021
Revises: 20260324_0020
Create Date: 2026-03-25 09:05:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = "20260325_0021"
down_revision = "20260324_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "users" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("users")}
    if "email" not in columns:
        return

    if "notify_email" in columns:
        bind.execute(
            text(
                """
                UPDATE users
                SET email = COALESCE(
                    NULLIF(notify_email, ''),
                    NULLIF(email, ''),
                    'user-' || CAST(id AS TEXT) || '@local.invalid'
                )
                """
            )
        )
    else:
        bind.execute(
            text(
                """
                UPDATE users
                SET email = COALESCE(
                    NULLIF(email, ''),
                    'user-' || CAST(id AS TEXT) || '@local.invalid'
                )
                """
            )
        )

    unique_constraints = inspector.get_unique_constraints("users")
    email_unique_exists = any(set(constraint.get("column_names") or []) == {"email"} for constraint in unique_constraints)

    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("email", existing_type=sa.String(length=255), nullable=False)
        if not email_unique_exists:
            batch_op.create_unique_constraint("uq_users_email", ["email"])
        if "notify_email" in columns:
            batch_op.drop_column("notify_email")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "users" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("users")}
    unique_constraints = inspector.get_unique_constraints("users")
    email_unique_name = next(
        (
            constraint.get("name")
            for constraint in unique_constraints
            if set(constraint.get("column_names") or []) == {"email"} and constraint.get("name")
        ),
        None,
    )

    with op.batch_alter_table("users") as batch_op:
        if "notify_email" not in columns:
            batch_op.add_column(sa.Column("notify_email", sa.String(length=255), nullable=True))
            batch_op.create_unique_constraint("uq_users_notify_email", ["notify_email"])
        if email_unique_name is not None:
            batch_op.drop_constraint(email_unique_name, type_="unique")
        batch_op.alter_column("email", existing_type=sa.String(length=255), nullable=True)

    bind.execute(text("UPDATE users SET notify_email = email WHERE notify_email IS NULL"))
