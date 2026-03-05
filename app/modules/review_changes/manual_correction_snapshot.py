from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Change, Event, ReviewStatus
from app.modules.review_changes.change_event_codec import event_row_to_json, parse_after_json
from app.modules.review_changes.manual_correction_errors import ManualCorrectionNotFoundError


def load_base_snapshot(
    *,
    db: Session,
    canonical_input_id: int,
    event_uid: str,
    existing_event: Event | None = None,
) -> tuple[dict, Event | None]:
    event_row = existing_event
    if event_row is None:
        event_row = db.scalar(
            select(Event).where(
                Event.input_id == canonical_input_id,
                Event.uid == event_uid,
            )
        )
    if event_row is not None:
        return event_row_to_json(event_row), event_row

    pending_row = db.scalar(
        select(Change)
        .where(
            Change.input_id == canonical_input_id,
            Change.event_uid == event_uid,
            Change.review_status == ReviewStatus.PENDING,
            Change.after_json.is_not(None),
        )
        .order_by(Change.id.desc())
        .limit(1)
    )
    if pending_row is not None and isinstance(pending_row.after_json, dict):
        parsed = parse_after_json(event_uid, pending_row.after_json)
        if parsed is not None:
            return {
                "uid": event_uid,
                "title": parsed["title"],
                "course_label": parsed["course_label"],
                "start_at_utc": parsed["start_at_utc"].isoformat(),
                "end_at_utc": parsed["end_at_utc"].isoformat(),
            }, None
    raise ManualCorrectionNotFoundError("target event not found in canonical or pending proposals")


def list_pending_change_ids(*, db: Session, canonical_input_id: int, event_uid: str) -> list[int]:
    rows = db.scalars(
        select(Change.id)
        .where(
            Change.input_id == canonical_input_id,
            Change.event_uid == event_uid,
            Change.review_status == ReviewStatus.PENDING,
        )
        .order_by(Change.id.asc())
    ).all()
    return [int(row_id) for row_id in rows if isinstance(row_id, int)]


__all__ = [
    "list_pending_change_ids",
    "load_base_snapshot",
]
