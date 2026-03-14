from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.ingestion import CalendarComponentParseStatus, CalendarComponentParseTask
from app.modules.ingestion.ics_delta import external_event_id_from_component_key


@dataclass(frozen=True)
class CalendarComponentIdentity:
    component_key: str
    external_event_id: str
    vevent_uid: str
    recurrence_id: str | None


def split_component_identity(*, component_key: str, external_event_id: str | None = None) -> CalendarComponentIdentity:
    key = component_key.strip()
    uid = key
    recurrence_id: str | None = None
    if "#" in key:
        uid_raw, rid_raw = key.split("#", 1)
        uid = uid_raw.strip() or key
        recurrence_id = rid_raw.strip() or None
    event_id = external_event_id.strip() if isinstance(external_event_id, str) and external_event_id.strip() else external_event_id_from_component_key(key)
    return CalendarComponentIdentity(
        component_key=key,
        external_event_id=event_id,
        vevent_uid=uid,
        recurrence_id=recurrence_id,
    )


def upsert_calendar_component_tasks(
    db: Session,
    *,
    request_id: str,
    source_id: int,
    changed_components: list[dict],
) -> list[CalendarComponentParseTask]:
    touched: list[CalendarComponentParseTask] = []
    for item in changed_components:
        if not isinstance(item, dict):
            continue
        raw_key = item.get("component_key")
        raw_b64 = item.get("component_ical_b64")
        if not isinstance(raw_key, str) or not raw_key.strip():
            continue
        if not isinstance(raw_b64, str) or not raw_b64.strip():
            continue
        identity = split_component_identity(
            component_key=raw_key,
            external_event_id=item.get("external_event_id") if isinstance(item.get("external_event_id"), str) else None,
        )
        existing = db.scalar(
            select(CalendarComponentParseTask).where(
                CalendarComponentParseTask.request_id == request_id,
                CalendarComponentParseTask.component_key == identity.component_key,
            )
        )
        fingerprint = item.get("fingerprint") if isinstance(item.get("fingerprint"), str) and item.get("fingerprint").strip() else None
        if existing is None:
            row = CalendarComponentParseTask(
                request_id=request_id,
                source_id=source_id,
                component_key=identity.component_key,
                external_event_id=identity.external_event_id,
                vevent_uid=identity.vevent_uid,
                recurrence_id=identity.recurrence_id,
                fingerprint=fingerprint,
                component_ical_b64=raw_b64.strip(),
                status=CalendarComponentParseStatus.PENDING,
                attempt=0,
                parsed_record_json=None,
                error_code=None,
                error_message=None,
            )
            db.add(row)
            touched.append(row)
            continue

        existing.external_event_id = identity.external_event_id
        existing.vevent_uid = identity.vevent_uid
        existing.recurrence_id = identity.recurrence_id
        existing.fingerprint = fingerprint
        existing.component_ical_b64 = raw_b64.strip()
        if existing.status not in {
            CalendarComponentParseStatus.RUNNING,
            CalendarComponentParseStatus.SUCCEEDED,
            CalendarComponentParseStatus.UNRESOLVED,
            CalendarComponentParseStatus.FAILED,
        }:
            existing.status = CalendarComponentParseStatus.PENDING
        touched.append(existing)
    return touched


__all__ = [
    "CalendarComponentIdentity",
    "split_component_identity",
    "upsert_calendar_component_tasks",
]
