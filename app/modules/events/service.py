from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import Change, Event, Input, InputType, ReviewStatus


@dataclass(frozen=True)
class EventListItem:
    id: int
    source_id: int
    uid: str
    course_label: str
    title: str
    start_at_utc: datetime
    end_at_utc: datetime
    updated_at: datetime
    source_label: str
    source_kind: InputType


def list_events_for_user(
    db: Session,
    *,
    user_id: int,
    source_id: int | None,
    source_kind: InputType | None,
    query: str | None,
    limit: int,
    offset: int,
) -> list[EventListItem]:
    canonical_identity_key = f"canonical:user:{user_id}"
    stmt = (
        select(Event, Input)
        .join(Input, Event.input_id == Input.id)
        .where(
            Input.user_id == user_id,
            Input.identity_key == canonical_identity_key,
        )
    )

    normalized_query = (query or "").strip()
    if normalized_query:
        like_value = f"%{normalized_query}%"
        stmt = stmt.where(
            or_(
                Event.title.ilike(like_value),
                Event.course_label.ilike(like_value),
            )
        )

    rows = db.execute(
        stmt.order_by(Event.updated_at.desc(), Event.id.desc()).offset(0).limit(limit + offset + 512)
    ).all()
    if not rows:
        return []

    canonical_input_id = rows[0][0].input_id
    change_rows = db.execute(
        select(Change.event_uid, Change.proposal_sources_json)
        .where(
            Change.input_id == canonical_input_id,
            Change.review_status == ReviewStatus.APPROVED,
        )
        .order_by(Change.detected_at.desc(), Change.id.desc())
    ).all()
    source_meta_by_uid: dict[str, dict] = {}
    for event_uid, sources_json in change_rows:
        if event_uid in source_meta_by_uid:
            continue
        source_id_value: int | None = None
        source_kind_value: str | None = None
        all_source_ids: set[int] = set()
        if isinstance(sources_json, list):
            for item in sources_json:
                if not isinstance(item, dict):
                    continue
                source_id_raw = item.get("source_id")
                source_kind_raw = item.get("source_kind")
                if isinstance(source_id_raw, int):
                    all_source_ids.add(source_id_raw)
                if source_id_value is None and isinstance(source_id_raw, int):
                    source_id_value = source_id_raw
                if source_kind_value is None and isinstance(source_kind_raw, str) and source_kind_raw.strip():
                    source_kind_value = source_kind_raw.strip().lower()
        source_meta_by_uid[event_uid] = {
            "primary_source_id": source_id_value,
            "source_kind": source_kind_value,
            "all_source_ids": all_source_ids,
        }

    result: list[EventListItem] = []
    for event, input_row in rows:
        meta = source_meta_by_uid.get(event.uid, {})
        resolved_source_id = meta.get("primary_source_id")
        resolved_source_kind = meta.get("source_kind")
        all_source_ids = meta.get("all_source_ids", set())
        if source_id is not None and source_id not in all_source_ids and resolved_source_id != source_id:
            continue
        row_source_kind = InputType.EMAIL if resolved_source_kind == "email" else InputType.ICS
        if source_kind is not None and row_source_kind != source_kind:
            continue
        result.append(
            EventListItem(
                id=event.id,
                source_id=resolved_source_id or event.input_id,
                uid=event.uid,
                course_label=event.course_label,
                title=event.title,
                start_at_utc=event.start_at_utc,
                end_at_utc=event.end_at_utc,
                updated_at=event.updated_at,
                source_label=input_row.display_label,
                source_kind=row_source_kind,
            )
        )

    return result[offset : offset + limit]
