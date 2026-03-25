"""normalize legacy source monitoring config keys

Revision ID: 20260324_0020
Revises: 20260324_0019
Create Date: 2026-03-24 16:50:00.000000
"""

from __future__ import annotations

from datetime import date

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260324_0020"
down_revision = "20260324_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "input_source_configs" not in inspector.get_table_names():
        return

    rows = bind.execute(sa.text("SELECT source_id, config_json FROM input_source_configs")).mappings().all()
    for row in rows:
        config_json = row["config_json"] if isinstance(row["config_json"], dict) else {}
        next_config = dict(config_json)
        monitor_since = _normalized_monitor_since(config_json)
        if monitor_since is None:
            changed = False
        else:
            changed = next_config.get("monitor_since") != monitor_since
            next_config["monitor_since"] = monitor_since
        for legacy_key in ("term" "_key", "term" "_from", "term" "_to", "pending" "_term" "_rebind"):
            if legacy_key in next_config:
                next_config.pop(legacy_key, None)
                changed = True
        if not changed:
            continue
        bind.execute(
            sa.text("UPDATE input_source_configs SET config_json = :config_json WHERE source_id = :source_id"),
            {"source_id": row["source_id"], "config_json": next_config},
        )


def downgrade() -> None:
    return None


def _normalized_monitor_since(config_json: dict) -> str | None:
    current = config_json.get("monitor_since")
    if isinstance(current, str) and current.strip():
        return current.strip()
    legacy = config_json.get("term" "_from")
    if not isinstance(legacy, str) or not legacy.strip():
        return None
    try:
        return date.fromisoformat(legacy.strip()).isoformat()
    except ValueError:
        return None
