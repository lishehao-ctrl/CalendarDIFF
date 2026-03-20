from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


AUTO_SYNC_LOCAL_TIMES: tuple[time, ...] = (
    time(hour=8, minute=0),
    time(hour=21, minute=0),
)


def next_source_auto_sync_at(*, now: datetime, timezone_name: str | None) -> datetime:
    zone = _resolve_timezone(timezone_name)
    current = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    local_now = current.astimezone(zone)
    local_day = local_now.date()
    for slot in AUTO_SYNC_LOCAL_TIMES:
        candidate_local = datetime.combine(local_day, slot, tzinfo=zone)
        if candidate_local > local_now:
            return candidate_local.astimezone(timezone.utc)
    next_day = local_day + timedelta(days=1)
    return datetime.combine(next_day, AUTO_SYNC_LOCAL_TIMES[0], tzinfo=zone).astimezone(timezone.utc)


def _resolve_timezone(timezone_name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo((timezone_name or "").strip() or "UTC")
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


__all__ = ["AUTO_SYNC_LOCAL_TIMES", "next_source_auto_sync_at"]
