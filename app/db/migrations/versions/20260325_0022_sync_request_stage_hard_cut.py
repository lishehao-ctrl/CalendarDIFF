"""normalize legacy workflow_stage into sync request stage fields

Revision ID: 20260325_0022
Revises: 20260325_0021
Create Date: 2026-03-25 09:35:00.000000
"""

from __future__ import annotations

from datetime import datetime

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = "20260325_0022"
down_revision = "20260325_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "sync_requests" not in tables or "ingest_jobs" not in tables:
        return

    sync_columns = {column["name"] for column in inspector.get_columns("sync_requests")}
    if not {"request_id", "stage", "substage", "stage_updated_at", "progress_json"}.issubset(sync_columns):
        return

    sync_rows = {
        row["request_id"]: row
        for row in bind.execute(
            text(
                """
                SELECT request_id, stage, substage, stage_updated_at, progress_json
                FROM sync_requests
                """
            )
        ).mappings()
    }

    job_rows = bind.execute(text("SELECT request_id, payload_json, updated_at FROM ingest_jobs")).mappings().all()
    for row in job_rows:
        request_id = row["request_id"]
        current = sync_rows.get(request_id)
        if current is None:
            continue
        if isinstance(current.get("progress_json"), dict) or current.get("substage") is not None:
            continue

        payload = row["payload_json"] if isinstance(row["payload_json"], dict) else {}
        stage_payload = _map_workflow_stage(payload.get("workflow_stage"))
        progress_payload = _extract_progress_payload(payload)
        if stage_payload is None and progress_payload is None:
            continue

        updated_at = _parse_datetime(payload.get("sync_progress_updated_at"))
        if updated_at is None and isinstance(row.get("updated_at"), datetime):
            updated_at = row["updated_at"]
        if updated_at is None:
            updated_at = current.get("stage_updated_at")

        bind.execute(
            text(
                """
                UPDATE sync_requests
                SET stage = COALESCE(:stage, stage),
                    substage = COALESCE(:substage, substage),
                    stage_updated_at = COALESCE(:stage_updated_at, stage_updated_at),
                    progress_json = COALESCE(:progress_json, progress_json)
                WHERE request_id = :request_id
                """
            ),
            {
                "request_id": request_id,
                "stage": stage_payload[0] if stage_payload is not None else None,
                "substage": stage_payload[1] if stage_payload is not None else None,
                "stage_updated_at": updated_at,
                "progress_json": progress_payload,
            },
        )


def downgrade() -> None:
    return None


def _map_workflow_stage(value: object) -> tuple[str, str] | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return {
        "LLM_ENQUEUE_PENDING": ("llm_queue", "parse_payload_ready"),
        "LLM_QUEUED": ("llm_parse", "llm_task_queued"),
        "LLM_RUNNING": ("llm_parse", "llm_parse"),
        "LLM_CALENDAR_FANOUT_QUEUED": ("llm_parse", "calendar_child_queue"),
        "LLM_CALENDAR_REDUCE_WAITING": ("provider_reduce", "calendar_reduce_wait"),
        "LLM_RATE_LIMIT_BACKPRESSURE": ("llm_parse", "llm_backpressure"),
        "CONNECTOR_RETRY_WAITING": ("connector_fetch", "connector_retry_waiting"),
        "CONNECTOR_DEAD_LETTER": ("failed", "connector_dead_letter"),
        "LLM_DEAD_LETTER": ("failed", "llm_dead_letter"),
    }.get(value.strip().upper())


def _extract_progress_payload(payload: dict) -> dict | None:
    for key in ("sync_progress", "gmail_progress"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return None


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip()
    try:
        return datetime.fromisoformat(candidate[:-1] + "+00:00" if candidate.endswith("Z") else candidate)
    except ValueError:
        return None
