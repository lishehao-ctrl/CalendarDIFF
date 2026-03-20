from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.review import ChangeType, EventEntity, EventEntityLifecycle
from app.modules.common.semantic_codec import parse_semantic_payload


def apply_approved_entity_state(
    *,
    db: Session,
    user_id: int,
    entity_uid: str,
    change_type: ChangeType,
    semantic_payload: dict | None,
) -> EventEntity | None:
    existing = db.scalar(
        select(EventEntity).where(
            EventEntity.user_id == user_id,
            EventEntity.entity_uid == entity_uid,
        )
    )

    if change_type == ChangeType.REMOVED:
        if existing is None:
            return None
        existing.lifecycle = EventEntityLifecycle.REMOVED
        return existing

    parsed = parse_semantic_payload(entity_uid, semantic_payload if isinstance(semantic_payload, dict) else None)
    if parsed is None:
        return existing
    if not isinstance(parsed.family_id, int):
        raise RuntimeError(f"approved_entity_state_integrity_error: missing family_id for entity_uid={entity_uid}")

    if existing is None:
        existing = EventEntity(
            user_id=user_id,
            entity_uid=entity_uid,
            lifecycle=EventEntityLifecycle.ACTIVE,
        )
        db.add(existing)

    existing.lifecycle = EventEntityLifecycle.ACTIVE
    existing.course_dept = parsed.course_dept
    existing.course_number = parsed.course_number
    existing.course_suffix = parsed.course_suffix
    existing.course_quarter = parsed.course_quarter
    existing.course_year2 = parsed.course_year2
    existing.family_id = parsed.family_id
    existing.raw_type = parsed.raw_type
    existing.event_name = parsed.event_name
    existing.ordinal = parsed.ordinal
    existing.due_date = parsed.due_date
    existing.due_time = parsed.due_time
    existing.time_precision = parsed.time_precision
    return existing


__all__ = ["apply_approved_entity_state"]
