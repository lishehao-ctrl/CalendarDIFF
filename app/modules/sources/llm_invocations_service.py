from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.runtime import LlmInvocationLog


def list_sync_request_llm_invocations(
    db: Session,
    *,
    request_id: str,
    limit: int,
) -> dict[str, Any]:
    rows = list(
        db.scalars(
            select(LlmInvocationLog)
            .where(LlmInvocationLog.request_id == request_id)
            .order_by(LlmInvocationLog.created_at.desc(), LlmInvocationLog.id.desc())
            .limit(limit)
        ).all()
    )
    return {
        "request_id": request_id,
        "items": [_serialize_log(row) for row in rows],
        "summary": _build_summary(rows),
    }


def list_source_llm_invocations(
    db: Session,
    *,
    source_id: int,
    request_id: str | None,
    limit: int,
) -> dict[str, Any]:
    stmt = select(LlmInvocationLog).where(LlmInvocationLog.source_id == source_id)
    if isinstance(request_id, str) and request_id.strip():
        stmt = stmt.where(LlmInvocationLog.request_id == request_id.strip())
    rows = list(
        db.scalars(
            stmt.order_by(LlmInvocationLog.created_at.desc(), LlmInvocationLog.id.desc()).limit(limit)
        ).all()
    )
    normalized_request_id = request_id.strip() if isinstance(request_id, str) and request_id.strip() else None
    return {
        "source_id": source_id,
        "request_id": normalized_request_id,
        "items": [_serialize_log(row) for row in rows],
        "summary": _build_summary(rows),
    }


def _serialize_log(row: LlmInvocationLog) -> dict[str, Any]:
    return {
        "request_id": row.request_id,
        "source_id": row.source_id,
        "task_name": row.task_name,
        "profile_family": row.profile_family,
        "route_id": row.route_id,
        "route_index": row.route_index,
        "provider_id": row.provider_id,
        "vendor": row.vendor,
        "protocol": row.protocol,
        "model": row.model,
        "session_cache_enabled": row.session_cache_enabled,
        "success": row.success,
        "latency_ms": row.latency_ms,
        "upstream_request_id": row.upstream_request_id,
        "response_id": row.response_id,
        "error_code": row.error_code,
        "retryable": row.retryable,
        "http_status": row.http_status,
        "usage": dict(row.usage_json) if isinstance(row.usage_json, dict) else None,
        "created_at": row.created_at,
    }


def _build_summary(rows: list[LlmInvocationLog]) -> dict[str, Any]:
    total_count = len(rows)
    success_count = sum(1 for row in rows if row.success)
    failure_count = total_count - success_count
    latency_values = [int(row.latency_ms) for row in rows if row.latency_ms is not None]
    summary: dict[str, Any] = {
        "total_count": total_count,
        "success_count": success_count,
        "failure_count": failure_count,
        "avg_latency_ms": int(sum(latency_values) / len(latency_values)) if latency_values else None,
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 0,
        "task_counts": {},
        "model_counts": {},
        "protocol_counts": {},
    }
    for row in rows:
        _increment(summary["task_counts"], row.task_name)
        _increment(summary["model_counts"], row.model)
        _increment(summary["protocol_counts"], row.protocol)
        usage = row.usage_json if isinstance(row.usage_json, dict) else {}
        for key in (
            "input_tokens",
            "cached_input_tokens",
            "cache_creation_input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "total_tokens",
        ):
            try:
                summary[key] += max(int(usage.get(key) or 0), 0)
            except Exception:
                continue
    return summary


def _increment(mapping: dict[str, int], key: str | None) -> None:
    if not isinstance(key, str) or not key:
        return
    mapping[key] = max(int(mapping.get(key) or 0), 0) + 1


__all__ = [
    "list_source_llm_invocations",
    "list_sync_request_llm_invocations",
]
