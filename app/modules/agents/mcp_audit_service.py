from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.agents import McpToolInvocation, McpToolInvocationStatus


def create_mcp_tool_invocation(
    db: Session,
    *,
    user_id: int,
    tool_name: str,
    transport: str,
    auth_mode: str,
    transport_request_id: str | None,
    input_payload: dict | None,
) -> McpToolInvocation:
    row = McpToolInvocation(
        invocation_id=uuid4().hex,
        transport_request_id=transport_request_id.strip()[:64] if isinstance(transport_request_id, str) and transport_request_id.strip() else None,
        user_id=user_id,
        tool_name=tool_name.strip()[:128],
        transport=transport.strip()[:32],
        auth_mode=auth_mode.strip()[:32],
        status=McpToolInvocationStatus.STARTED,
        input_json=dict(jsonable_encoder(input_payload or {})),
        output_summary_json={},
        error_text=None,
        proposal_id=None,
        ticket_id=None,
        completed_at=None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def mark_mcp_tool_invocation_succeeded(
    db: Session,
    *,
    invocation_id: str,
    output_summary: dict | None,
    proposal_id: int | None,
    ticket_id: str | None,
) -> McpToolInvocation:
    row = _require_mcp_tool_invocation(db, invocation_id=invocation_id)
    row.status = McpToolInvocationStatus.SUCCEEDED
    row.output_summary_json = dict(jsonable_encoder(output_summary or {}))
    row.proposal_id = proposal_id
    row.ticket_id = ticket_id
    row.completed_at = datetime.now(UTC)
    db.commit()
    db.refresh(row)
    return row


def mark_mcp_tool_invocation_failed(
    db: Session,
    *,
    invocation_id: str,
    error_text: str,
) -> McpToolInvocation:
    row = _require_mcp_tool_invocation(db, invocation_id=invocation_id)
    row.status = McpToolInvocationStatus.FAILED
    row.error_text = error_text[:2000]
    row.completed_at = datetime.now(UTC)
    db.commit()
    db.refresh(row)
    return row


def list_mcp_tool_invocations(db: Session, *, user_id: int, limit: int = 20) -> list[McpToolInvocation]:
    return list(
        db.scalars(
            select(McpToolInvocation)
            .where(McpToolInvocation.user_id == user_id)
            .order_by(McpToolInvocation.created_at.desc(), McpToolInvocation.invocation_id.desc())
            .limit(limit)
        ).all()
    )


def summarize_mcp_tool_output(payload: object) -> dict:
    if not isinstance(payload, dict):
        return {}
    return {
        key: payload.get(key)
        for key in (
            "proposal_id",
            "ticket_id",
            "status",
            "target_kind",
            "target_id",
            "summary_code",
            "action_type",
            "risk_level",
            "delivery_kind",
        )
        if key in payload
    }


def _require_mcp_tool_invocation(db: Session, *, invocation_id: str) -> McpToolInvocation:
    row = db.scalar(select(McpToolInvocation).where(McpToolInvocation.invocation_id == invocation_id).limit(1))
    if row is None:
        raise RuntimeError("MCP tool invocation not found")
    return row


__all__ = [
    "create_mcp_tool_invocation",
    "list_mcp_tool_invocations",
    "mark_mcp_tool_invocation_failed",
    "mark_mcp_tool_invocation_succeeded",
    "summarize_mcp_tool_output",
]
