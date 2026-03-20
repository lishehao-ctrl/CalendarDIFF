from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.runtime import GmailMessageParseCache, GmailMessageParseCacheStatus
from app.modules.runtime.kernel import utcnow


def load_cached_gmail_parse_records(
    *,
    db: Session,
    source_id: int,
    payload_item: dict[str, Any],
) -> list[dict] | None:
    if not bool(get_settings().gmail_message_parse_cache_enabled):
        return None
    cache_key = _build_gmail_parse_cache_key(payload_item)
    if cache_key is None:
        return None

    row = db.scalar(
        select(GmailMessageParseCache).where(
            GmailMessageParseCache.source_id == source_id,
            GmailMessageParseCache.message_id == cache_key["message_id"],
            GmailMessageParseCache.content_hash == cache_key["content_hash"],
        )
    )
    if row is None:
        return None

    row.hit_count = max(int(row.hit_count or 0), 0) + 1
    row.last_used_at = utcnow()
    db.commit()
    return list(row.records_json) if isinstance(row.records_json, list) else []


def store_cached_gmail_parse_records(
    *,
    db: Session,
    source_id: int,
    payload_item: dict[str, Any],
    records: list[dict],
    error_code: str | None = None,
) -> None:
    if not bool(get_settings().gmail_message_parse_cache_enabled):
        return
    cache_key = _build_gmail_parse_cache_key(payload_item)
    if cache_key is None:
        return

    status = GmailMessageParseCacheStatus.PARSED if records else GmailMessageParseCacheStatus.EMPTY
    _upsert_gmail_parse_cache_row(
        db=db,
        source_id=source_id,
        message_id=cache_key["message_id"],
        content_hash=cache_key["content_hash"],
        status=status,
        records=records,
        error_code=error_code,
    )


def store_non_retryable_gmail_parse_skip(
    *,
    db: Session,
    source_id: int,
    payload_item: dict[str, Any],
    error_code: str,
) -> None:
    if not bool(get_settings().gmail_message_parse_cache_enabled):
        return
    cache_key = _build_gmail_parse_cache_key(payload_item)
    if cache_key is None:
        return

    _upsert_gmail_parse_cache_row(
        db=db,
        source_id=source_id,
        message_id=cache_key["message_id"],
        content_hash=cache_key["content_hash"],
        status=GmailMessageParseCacheStatus.NON_RETRYABLE_SKIP,
        records=[],
        error_code=error_code,
    )


def _upsert_gmail_parse_cache_row(
    *,
    db: Session,
    source_id: int,
    message_id: str,
    content_hash: str,
    status: GmailMessageParseCacheStatus,
    records: list[dict],
    error_code: str | None,
) -> None:
    row = db.scalar(
        select(GmailMessageParseCache).where(
            GmailMessageParseCache.source_id == source_id,
            GmailMessageParseCache.message_id == message_id,
            GmailMessageParseCache.content_hash == content_hash,
        )
    )
    now = utcnow()
    normalized_records = [row for row in records if isinstance(row, dict)]
    if row is None:
        row = GmailMessageParseCache(
            source_id=source_id,
            message_id=message_id,
            content_hash=content_hash,
            status=status,
            records_json=normalized_records,
            error_code=error_code,
            hit_count=0,
            last_used_at=now,
        )
        db.add(row)
    else:
        row.status = status
        row.records_json = normalized_records
        row.error_code = error_code
        row.last_used_at = now
    db.commit()


def _build_gmail_parse_cache_key(payload_item: dict[str, Any]) -> dict[str, str] | None:
    message_id = payload_item.get("message_id")
    if not isinstance(message_id, str) or not message_id.strip():
        return None
    normalized = {
        "from_header": payload_item.get("from_header"),
        "subject": payload_item.get("subject"),
        "snippet": payload_item.get("snippet"),
        "body_text": payload_item.get("body_text"),
        "internal_date": payload_item.get("internal_date"),
        "label_ids": payload_item.get("label_ids"),
    }
    serialized = json.dumps(normalized, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return {
        "message_id": message_id.strip(),
        "content_hash": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
    }


__all__ = [
    "load_cached_gmail_parse_records",
    "store_cached_gmail_parse_records",
    "store_non_retryable_gmail_parse_skip",
]
