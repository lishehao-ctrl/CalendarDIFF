from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.runtime import CalendarComponentParseCache, CalendarComponentParseCacheStatus
from app.modules.runtime.kernel import utcnow


def load_cached_calendar_component_records(
    *,
    db: Session,
    source_id: int,
    fingerprint: str | None,
) -> list[dict] | None:
    if not bool(get_settings().calendar_component_parse_cache_enabled):
        return None
    if not isinstance(fingerprint, str) or not fingerprint.strip():
        return None

    row = db.scalar(
        select(CalendarComponentParseCache).where(
            CalendarComponentParseCache.source_id == source_id,
            CalendarComponentParseCache.fingerprint == fingerprint.strip(),
        )
    )
    if row is None:
        return None
    row.hit_count = max(int(row.hit_count or 0), 0) + 1
    row.last_used_at = utcnow()
    db.commit()
    return list(row.records_json) if isinstance(row.records_json, list) else []


def store_cached_calendar_component_records(
    *,
    db: Session,
    source_id: int,
    fingerprint: str | None,
    records: list[dict],
    error_code: str | None = None,
) -> None:
    if not bool(get_settings().calendar_component_parse_cache_enabled):
        return
    if not isinstance(fingerprint, str) or not fingerprint.strip():
        return
    _upsert_calendar_parse_cache_row(
        db=db,
        source_id=source_id,
        fingerprint=fingerprint.strip(),
        status=CalendarComponentParseCacheStatus.PARSED if records else CalendarComponentParseCacheStatus.EMPTY,
        records=records,
        error_code=error_code,
    )


def store_non_retryable_calendar_component_skip(
    *,
    db: Session,
    source_id: int,
    fingerprint: str | None,
    error_code: str,
) -> None:
    if not bool(get_settings().calendar_component_parse_cache_enabled):
        return
    if not isinstance(fingerprint, str) or not fingerprint.strip():
        return
    _upsert_calendar_parse_cache_row(
        db=db,
        source_id=source_id,
        fingerprint=fingerprint.strip(),
        status=CalendarComponentParseCacheStatus.NON_RETRYABLE_SKIP,
        records=[],
        error_code=error_code,
    )


def _upsert_calendar_parse_cache_row(
    *,
    db: Session,
    source_id: int,
    fingerprint: str,
    status: CalendarComponentParseCacheStatus,
    records: list[dict],
    error_code: str | None,
) -> None:
    row = db.scalar(
        select(CalendarComponentParseCache).where(
            CalendarComponentParseCache.source_id == source_id,
            CalendarComponentParseCache.fingerprint == fingerprint,
        )
    )
    now = utcnow()
    normalized_records = [row for row in records if isinstance(row, dict)]
    if row is None:
        row = CalendarComponentParseCache(
            source_id=source_id,
            fingerprint=fingerprint,
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


__all__ = [
    "load_cached_calendar_component_records",
    "store_cached_calendar_component_records",
    "store_non_retryable_calendar_component_skip",
]
