from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.db.models.input import SyncRequest
from app.db.session import get_session_factory

logger = logging.getLogger(__name__)

GMAIL_PARSE_SUMMARY_KEY = "gmail_parse_summary"
_NUMERIC_KEYS = (
    "message_count",
    "final_parse_cache_hit_count",
    "purpose_cache_hit_count",
    "purpose_cache_hit_unknown_count",
    "purpose_cache_hit_atomic_count",
    "purpose_cache_hit_directive_count",
    "purpose_cache_shared_content_hit_count",
    "purpose_cache_fingerprint_hit_count",
    "deterministic_fast_path_unknown_count",
    "llm_purpose_classify_call_count",
    "purpose_unknown_count",
    "purpose_atomic_count",
    "purpose_directive_count",
)


def empty_gmail_parse_summary() -> dict[str, Any]:
    return {
        **{key: 0 for key in _NUMERIC_KEYS},
        "last_observed_at": None,
    }


def merge_gmail_parse_summary(existing: dict[str, Any] | None, delta: dict[str, Any] | None) -> dict[str, Any]:
    summary = empty_gmail_parse_summary()
    if isinstance(existing, dict):
        for key in _NUMERIC_KEYS:
            try:
                summary[key] = max(int(existing.get(key) or 0), 0)
            except Exception:
                summary[key] = 0
        if isinstance(existing.get("last_observed_at"), str):
            summary["last_observed_at"] = existing["last_observed_at"]
    if isinstance(delta, dict):
        for key in _NUMERIC_KEYS:
            try:
                summary[key] += max(int(delta.get(key) or 0), 0)
            except Exception:
                continue
    summary["last_observed_at"] = datetime.now(UTC).isoformat()
    return summary


def record_sync_request_gmail_parse_summary(*, request_id: str, delta: dict[str, Any] | None) -> None:
    normalized_request_id = str(request_id or "").strip()
    if not normalized_request_id or not isinstance(delta, dict):
        return
    if not any(int(delta.get(key) or 0) > 0 for key in _NUMERIC_KEYS):
        return
    try:
        session_factory = get_session_factory()
        with session_factory() as db:
            sync_request = db.scalar(
                select(SyncRequest).where(SyncRequest.request_id == normalized_request_id).with_for_update()
            )
            if sync_request is None:
                return
            metadata = dict(sync_request.metadata_json) if isinstance(sync_request.metadata_json, dict) else {}
            metadata[GMAIL_PARSE_SUMMARY_KEY] = merge_gmail_parse_summary(
                metadata.get(GMAIL_PARSE_SUMMARY_KEY) if isinstance(metadata.get(GMAIL_PARSE_SUMMARY_KEY), dict) else None,
                delta,
            )
            sync_request.metadata_json = metadata
            db.commit()
    except Exception as exc:
        logger.warning(
            "gmail_parse_summary.persist_failed request_id=%s error=%s",
            normalized_request_id,
            exc,
        )


def present_gmail_parse_summary(summary: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(summary, dict):
        return None
    normalized = merge_gmail_parse_summary(summary, None)
    total_decisions = (
        normalized["purpose_unknown_count"]
        + normalized["purpose_atomic_count"]
        + normalized["purpose_directive_count"]
    )
    out = {key: normalized[key] for key in _NUMERIC_KEYS}
    out["last_observed_at"] = normalized.get("last_observed_at")
    out["unknown_ratio"] = round(normalized["purpose_unknown_count"] / total_decisions, 4) if total_decisions > 0 else None
    return out


__all__ = [
    "GMAIL_PARSE_SUMMARY_KEY",
    "empty_gmail_parse_summary",
    "merge_gmail_parse_summary",
    "present_gmail_parse_summary",
    "record_sync_request_gmail_parse_summary",
]
