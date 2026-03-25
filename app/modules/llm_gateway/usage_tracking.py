from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.db.models.input import SyncRequest
from app.db.session import get_session_factory
from app.modules.llm_gateway.contracts import LlmInvokeRequest, LlmInvokeResult
from app.modules.llm_gateway.usage_normalizer import normalize_llm_usage

logger = logging.getLogger(__name__)

LLM_USAGE_SUMMARY_KEY = "llm_usage_summary"

_NUMERIC_KEYS = (
    "successful_call_count",
    "usage_record_count",
    "latency_ms_total",
    "latency_ms_max",
    "input_tokens",
    "cached_input_tokens",
    "cache_creation_input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "total_tokens",
)


def empty_llm_usage_summary() -> dict[str, Any]:
    return {
        "successful_call_count": 0,
        "usage_record_count": 0,
        "latency_ms_total": 0,
        "latency_ms_max": 0,
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 0,
        "protocols": {},
        "models": {},
        "task_counts": {},
        "tasks": {},
        "last_observed_at": None,
    }


def merge_llm_usage_summary(
    existing: dict[str, Any] | None,
    *,
    invoke_request: LlmInvokeRequest,
    result: LlmInvokeResult,
) -> dict[str, Any]:
    summary = _coerce_summary(existing)
    normalized_usage = normalize_llm_usage(result.raw_usage if isinstance(result.raw_usage, dict) else None)

    summary["successful_call_count"] += 1
    summary["latency_ms_total"] += max(int(result.latency_ms), 0)
    summary["latency_ms_max"] = max(summary["latency_ms_max"], max(int(result.latency_ms), 0))

    if any(value is not None for value in normalized_usage.values()):
        summary["usage_record_count"] += 1
    for key, value in normalized_usage.items():
        if value is None:
            continue
        summary[key] += max(int(value), 0)

    protocol = str(result.protocol or "").strip()
    if protocol:
        _increment_count(summary["protocols"], protocol)
    model = str(result.model or "").strip()
    if model:
        _increment_count(summary["models"], model)
    task_name = str(invoke_request.task_name or "").strip()
    if task_name:
        _increment_count(summary["task_counts"], task_name)
        summary["tasks"][task_name] = _merge_task_summary(
            summary["tasks"].get(task_name),
            result=result,
            normalized_usage=normalized_usage,
            model=model,
            protocol=protocol,
        )

    summary["last_observed_at"] = datetime.now(UTC).isoformat()
    return summary


def record_sync_request_llm_usage(
    *,
    invoke_request: LlmInvokeRequest,
    result: LlmInvokeResult,
) -> None:
    request_id = str(invoke_request.request_id or "").strip()
    if not request_id:
        return
    try:
        session_factory = get_session_factory()
        with session_factory() as db:
            sync_request = db.scalar(
                select(SyncRequest).where(SyncRequest.request_id == request_id).with_for_update()
            )
            if sync_request is None:
                return
            metadata = dict(sync_request.metadata_json) if isinstance(sync_request.metadata_json, dict) else {}
            metadata[LLM_USAGE_SUMMARY_KEY] = merge_llm_usage_summary(
                metadata.get(LLM_USAGE_SUMMARY_KEY) if isinstance(metadata.get(LLM_USAGE_SUMMARY_KEY), dict) else None,
                invoke_request=invoke_request,
                result=result,
            )
            sync_request.metadata_json = metadata
            db.commit()
    except Exception as exc:
        logger.warning(
            "llm_usage_tracking.persist_failed request_id=%s source_id=%s task_name=%s error=%s",
            request_id,
            invoke_request.source_id if invoke_request.source_id is not None else "-",
            invoke_request.task_name,
            exc,
        )


def _coerce_summary(existing: dict[str, Any] | None) -> dict[str, Any]:
    summary = empty_llm_usage_summary()
    if not isinstance(existing, dict):
        return summary
    for key in _NUMERIC_KEYS:
        try:
            summary[key] = max(int(existing.get(key) or 0), 0)
        except Exception:
            summary[key] = 0
    for mapping_key in ("protocols", "models", "task_counts"):
        summary[mapping_key] = _coerce_counter_map(existing.get(mapping_key))
    tasks = existing.get("tasks")
    if isinstance(tasks, dict):
        normalized_tasks: dict[str, Any] = {}
        for key, value in tasks.items():
            if not isinstance(key, str) or not isinstance(value, dict):
                continue
            normalized_tasks[key] = _coerce_task_summary(value)
        summary["tasks"] = normalized_tasks
    summary["last_observed_at"] = existing.get("last_observed_at") if isinstance(existing.get("last_observed_at"), str) else None
    return summary


def _coerce_task_summary(existing: dict[str, Any] | None) -> dict[str, Any]:
    task_summary = {
        "successful_call_count": 0,
        "usage_record_count": 0,
        "latency_ms_total": 0,
        "latency_ms_max": 0,
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 0,
        "models": {},
        "protocols": {},
    }
    if not isinstance(existing, dict):
        return task_summary
    for key in (
        "successful_call_count",
        "usage_record_count",
        "latency_ms_total",
        "latency_ms_max",
        "input_tokens",
        "cached_input_tokens",
        "cache_creation_input_tokens",
        "output_tokens",
        "reasoning_tokens",
        "total_tokens",
    ):
        try:
            task_summary[key] = max(int(existing.get(key) or 0), 0)
        except Exception:
            task_summary[key] = 0
    task_summary["models"] = _coerce_counter_map(existing.get("models"))
    task_summary["protocols"] = _coerce_counter_map(existing.get("protocols"))
    return task_summary


def _merge_task_summary(
    existing: dict[str, Any] | None,
    *,
    result: LlmInvokeResult,
    normalized_usage: dict[str, int | None],
    model: str,
    protocol: str,
) -> dict[str, Any]:
    task_summary = _coerce_task_summary(existing)
    task_summary["successful_call_count"] += 1
    task_summary["latency_ms_total"] += max(int(result.latency_ms), 0)
    task_summary["latency_ms_max"] = max(task_summary["latency_ms_max"], max(int(result.latency_ms), 0))
    if any(value is not None for value in normalized_usage.values()):
        task_summary["usage_record_count"] += 1
    for key, value in normalized_usage.items():
        if value is None:
            continue
        task_summary[key] += max(int(value), 0)
    if model:
        _increment_count(task_summary["models"], model)
    if protocol:
        _increment_count(task_summary["protocols"], protocol)
    return task_summary


def _coerce_counter_map(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, int] = {}
    for key, raw in value.items():
        if not isinstance(key, str):
            continue
        try:
            count = max(int(raw or 0), 0)
        except Exception:
            continue
        if count > 0:
            out[key] = count
    return out


def _increment_count(mapping: dict[str, int], key: str) -> None:
    mapping[key] = max(int(mapping.get(key) or 0), 0) + 1


def present_llm_usage_summary(summary: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(summary, dict):
        return None
    normalized = _coerce_summary(summary)
    call_count = max(int(normalized.get("successful_call_count") or 0), 0)
    input_tokens = max(int(normalized.get("input_tokens") or 0), 0)
    presented = {
        "successful_call_count": call_count,
        "usage_record_count": max(int(normalized.get("usage_record_count") or 0), 0),
        "latency_ms_total": max(int(normalized.get("latency_ms_total") or 0), 0),
        "latency_ms_max": max(int(normalized.get("latency_ms_max") or 0), 0),
        "input_tokens": input_tokens,
        "cached_input_tokens": max(int(normalized.get("cached_input_tokens") or 0), 0),
        "cache_creation_input_tokens": max(int(normalized.get("cache_creation_input_tokens") or 0), 0),
        "output_tokens": max(int(normalized.get("output_tokens") or 0), 0),
        "reasoning_tokens": max(int(normalized.get("reasoning_tokens") or 0), 0),
        "total_tokens": max(int(normalized.get("total_tokens") or 0), 0),
        "protocols": dict(normalized.get("protocols") or {}),
        "models": dict(normalized.get("models") or {}),
        "task_counts": dict(normalized.get("task_counts") or {}),
        "last_observed_at": normalized.get("last_observed_at"),
        "avg_latency_ms": (
            int(normalized["latency_ms_total"] / call_count)
            if call_count > 0
            else None
        ),
        "cache_hit_ratio": (
            round(normalized["cached_input_tokens"] / input_tokens, 4)
            if input_tokens > 0
            else None
        ),
    }
    return presented


__all__ = [
    "LLM_USAGE_SUMMARY_KEY",
    "empty_llm_usage_summary",
    "merge_llm_usage_summary",
    "present_llm_usage_summary",
    "record_sync_request_llm_usage",
]
