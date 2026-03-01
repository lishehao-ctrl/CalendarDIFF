from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.security import require_api_key
from app.db.models import InputType
from app.db.session import get_db
from app.modules.common.deps import get_onboarded_user_or_409, require_onboarded_user_or_409
from app.modules.events.schemas import EventListItemResponse
from app.modules.events.service import list_events_for_user


router = APIRouter(
    prefix="/v2/timeline-events",
    tags=["timeline-events"],
    dependencies=[Depends(require_api_key), Depends(require_onboarded_user_or_409)],
)


@router.get("", response_model=list[EventListItemResponse])
def list_events(
    source_id: int | None = Query(default=None, ge=1),
    source_kind: Literal["calendar", "email"] | None = Query(default=None),
    q: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> list[EventListItemResponse]:
    mapped_type = _parse_source_kind(source_kind)
    rows = list_events_for_user(
        db,
        user_id=user.id,
        source_id=source_id,
        source_kind=mapped_type,
        query=q,
        limit=limit,
        offset=offset,
    )
    return [
        EventListItemResponse(
            id=row.id,
            source_id=row.source_id,
            uid=row.uid,
            course_label=row.course_label,
            title=row.title,
            start_at_utc=row.start_at_utc,
            end_at_utc=row.end_at_utc,
            updated_at=row.updated_at,
            source_label=row.source_label,
            source_kind="calendar" if row.source_kind == InputType.ICS else "email",
        )
        for row in rows
    ]


def _parse_source_kind(raw: str | None) -> InputType | None:
    if raw is None:
        return None
    return InputType.ICS if raw == "calendar" else InputType.EMAIL
