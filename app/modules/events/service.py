from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import Event, Input, InputType


@dataclass(frozen=True)
class EventListItem:
    id: int
    input_id: int
    uid: str
    course_label: str
    title: str
    start_at_utc: datetime
    end_at_utc: datetime
    updated_at: datetime
    input_label: str
    input_type: InputType


def list_events_for_user(
    db: Session,
    *,
    user_id: int,
    input_id: int | None,
    input_type: InputType | None,
    query: str | None,
    limit: int,
    offset: int,
) -> list[EventListItem]:
    stmt = (
        select(Event, Input)
        .join(Input, Event.input_id == Input.id)
        .where(Input.user_id == user_id)
    )

    if input_id is not None:
        stmt = stmt.where(Event.input_id == input_id)
    if input_type is not None:
        stmt = stmt.where(Input.type == input_type)

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
            input_id=event.input_id,
            uid=event.uid,
            course_label=event.course_label,
            title=event.title,
            start_at_utc=event.start_at_utc,
            end_at_utc=event.end_at_utc,
            updated_at=event.updated_at,
            input_label=input_row.display_label,
            input_type=input_row.type,
        )
        for event, input_row in rows
    ]
