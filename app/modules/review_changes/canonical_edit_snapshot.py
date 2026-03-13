from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.review import Change, EventEntity, ReviewStatus
from app.modules.common.family_labels import load_latest_family_labels, require_latest_family_label
from app.modules.common.semantic_codec import approved_entity_to_semantic_payload, parse_semantic_payload
from app.modules.review_changes.canonical_edit_errors import CanonicalEditNotFoundError


def load_semantic_base_payload(
    *,
    db: Session,
    user_id: int,
    entity_uid: str,
    existing_entity: EventEntity | None = None,
) -> tuple[dict, EventEntity | None]:
    entity_row = existing_entity
    if entity_row is None:
        entity_row = db.scalar(
            select(EventEntity).where(
                EventEntity.user_id == user_id,
                EventEntity.entity_uid == entity_uid,
            )
        )
    if entity_row is not None and entity_row.event_name and entity_row.due_date is not None:
        latest_family_labels = load_latest_family_labels(db, user_id=user_id, family_ids=[entity_row.family_id])
        current_family_name = require_latest_family_label(
            family_id=entity_row.family_id,
            latest_family_labels=latest_family_labels,
            context=f"review_changes.canonical_edit_snapshot approved entity_uid={entity_uid}",
        )
        return approved_entity_to_semantic_payload(entity_row, family_name_override=current_family_name), entity_row

    pending_row = db.scalar(
        select(Change)
        .where(
            Change.user_id == user_id,
            Change.entity_uid == entity_uid,
            Change.review_status == ReviewStatus.PENDING,
            Change.after_semantic_json.is_not(None),
        )
        .order_by(Change.id.desc())
        .limit(1)
    )
    if pending_row is not None and isinstance(pending_row.after_semantic_json, dict):
        parsed = parse_semantic_payload(entity_uid, pending_row.after_semantic_json)
        if parsed is not None:
            latest_family_labels = load_latest_family_labels(db, user_id=user_id, family_ids=[parsed.family_id])
            return {
                "uid": entity_uid,
                "course_dept": parsed.course_dept,
                "course_number": parsed.course_number,
                "course_suffix": parsed.course_suffix,
                "course_quarter": parsed.course_quarter,
                "course_year2": parsed.course_year2,
                "family_id": parsed.family_id,
                "family_name": require_latest_family_label(
                    family_id=parsed.family_id,
                    latest_family_labels=latest_family_labels,
                    context=f"review_changes.canonical_edit_snapshot pending entity_uid={entity_uid}",
                ),
                "raw_type": parsed.raw_type,
                "event_name": parsed.event_name,
                "ordinal": parsed.ordinal,
                "due_date": parsed.due_date.isoformat() if parsed.due_date is not None else None,
                "due_time": parsed.due_time.isoformat() if parsed.due_time is not None else None,
                "time_precision": parsed.time_precision or "datetime",
            }, entity_row
    raise CanonicalEditNotFoundError("target event not found in approved entity state or pending proposals")


def list_pending_change_ids(*, db: Session, user_id: int, entity_uid: str) -> list[int]:
    rows = db.scalars(
        select(Change.id)
        .where(
            Change.user_id == user_id,
            Change.entity_uid == entity_uid,
            Change.review_status == ReviewStatus.PENDING,
        )
        .order_by(Change.id.asc())
    ).all()
    return [int(row_id) for row_id in rows if isinstance(row_id, int)]


__all__ = [
    "list_pending_change_ids",
    "load_semantic_base_payload",
]
