from __future__ import annotations

from datetime import date, datetime, time, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.review import EventEntity, EventEntityLifecycle
from app.modules.common.family_labels import require_latest_family_label

_WEEKDAY_TO_INDEX = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def load_directive_candidates(
    *,
    db: Session,
    user_id: int,
    selector: dict,
) -> list[EventEntity]:
    selector_dept = selector.get("course_dept")
    selector_number = selector.get("course_number")
    if not isinstance(selector_dept, str) or not selector_dept.strip() or not isinstance(selector_number, int):
        return []

    query = (
        select(EventEntity)
        .where(
            EventEntity.user_id == user_id,
            EventEntity.lifecycle == EventEntityLifecycle.ACTIVE,
            EventEntity.course_dept == selector_dept.strip().upper(),
            EventEntity.course_number == selector_number,
        )
        .order_by(EventEntity.entity_uid.asc())
    )
    if isinstance(selector.get("course_suffix"), str) and selector.get("course_suffix").strip():
        query = query.where(EventEntity.course_suffix == selector.get("course_suffix").strip().upper())
    if isinstance(selector.get("course_quarter"), str) and selector.get("course_quarter").strip():
        query = query.where(EventEntity.course_quarter == selector.get("course_quarter").strip().upper())
    if isinstance(selector.get("course_year2"), int):
        query = query.where(EventEntity.course_year2 == selector.get("course_year2"))
    return list(db.scalars(query).all())


def entity_matches_directive_selector(
    *,
    entity: EventEntity,
    selector: dict,
    latest_family_labels: dict[int, str],
    applied_at: datetime,
) -> bool:
    raw_type_hint = selector.get("raw_type_hint")
    if isinstance(raw_type_hint, str) and raw_type_hint.strip():
        if not isinstance(entity.raw_type, str) or entity.raw_type.strip().lower() != raw_type_hint.strip().lower():
            return False

    family_hint = selector.get("family_hint")
    if isinstance(family_hint, str) and family_hint.strip():
        family_name = require_latest_family_label(
            family_id=entity.family_id,
            latest_family_labels=latest_family_labels,
            context=f"gmail.directive.family_hint entity_uid={entity.entity_uid}",
        )
        if family_name.strip().lower() != family_hint.strip().lower():
            return False

    scope_mode = selector.get("scope_mode") if isinstance(selector.get("scope_mode"), str) else "all_matching"
    if scope_mode == "ordinal_list":
        if not isinstance(entity.ordinal, int):
            return False
        raw_ordinals = selector.get("ordinal_list")
        if not isinstance(raw_ordinals, list):
            return False
        ordinal_values = {value for value in raw_ordinals if isinstance(value, int)}
        if entity.ordinal not in ordinal_values:
            return False
    elif scope_mode == "ordinal_range":
        if not isinstance(entity.ordinal, int):
            return False
        start = selector.get("ordinal_range_start")
        end = selector.get("ordinal_range_end")
        if not isinstance(start, int) or not isinstance(end, int):
            return False
        if entity.ordinal < start or entity.ordinal > end:
            return False

    current_due_weekday = selector.get("current_due_weekday")
    if isinstance(current_due_weekday, str) and current_due_weekday.strip():
        weekday_index = _WEEKDAY_TO_INDEX.get(current_due_weekday.strip().lower())
        if weekday_index is None:
            return False
        if not isinstance(entity.due_date, date) or entity.due_date.weekday() != weekday_index:
            return False

    if bool(selector.get("applies_to_future_only")):
        due_at = _entity_due_datetime(entity)
        if due_at is None or due_at <= applied_at:
            return False

    return True


def _entity_due_datetime(entity: EventEntity) -> datetime | None:
    if not isinstance(entity.due_date, date):
        return None
    if str(entity.time_precision or "datetime") == "date_only" or not isinstance(entity.due_time, time):
        return datetime(entity.due_date.year, entity.due_date.month, entity.due_date.day, 23, 59, tzinfo=timezone.utc)
    return datetime.combine(entity.due_date, entity.due_time, tzinfo=timezone.utc)


__all__ = ["entity_matches_directive_selector", "load_directive_candidates"]
