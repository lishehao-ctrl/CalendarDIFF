from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import Event, Input, InputType


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
    stmt = (
        select(Event, Input)
        .join(Input, Event.input_id == Input.id)
        .where(Input.user_id == user_id)
    )

    if source_id is not None:
        stmt = stmt.where(Event.input_id == source_id)
    if source_kind is not None:
        stmt = stmt.where(Input.type == source_kind)

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
        stmt.order_by(Event.updated_at.desc(), Event.id.desc()).offset(offset).limit(limit)
    ).all()
    return [
        EventListItem(
            id=event.id,
            source_id=event.input_id,
            uid=event.uid,
            course_label=event.course_label,
            title=event.title,
            start_at_utc=event.start_at_utc,
            end_at_utc=event.end_at_utc,
            updated_at=event.updated_at,
            source_label=input_row.display_label,
            source_kind=input_row.type,
        )
        for event, input_row in rows
    ]
