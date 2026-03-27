from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.agents import AgentCommandStepTrace


def persist_command_step_traces(db: Session, *, traces: list[dict[str, Any]]) -> None:
    if not bool(get_settings().agent_trace_persistence_enabled):
        return
    for trace in traces:
        if not trace.get("user_id"):
            continue
        db.add(
            AgentCommandStepTrace(
                eval_run_id=str(trace.get("eval_run_id") or "")[:64],
                operation_id=str(trace.get("operation_id") or "")[:64],
                command_id=str(trace.get("command_id") or "")[:64] if trace.get("command_id") else None,
                user_id=int(trace.get("user_id")),
                step_id=str(trace.get("step_id") or "")[:64],
                tool_name=str(trace.get("tool_name") or "")[:128] if trace.get("tool_name") else None,
                scope_kind=str(trace.get("scope_kind") or "")[:16] if trace.get("scope_kind") else None,
                execution_boundary=str(trace.get("execution_boundary") or "")[:32] if trace.get("execution_boundary") else None,
                status=str(trace.get("status") or "")[:32],
                payload_json=dict(trace.get("payload") or {}),
                started_at=_parse_dt(trace.get("started_at")),
                finished_at=_parse_dt(trace.get("finished_at")),
            )
        )


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


__all__ = ["persist_command_step_traces"]
