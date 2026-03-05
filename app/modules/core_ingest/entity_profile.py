from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import EventEntity


def get_or_create_event_entity(*, db: Session, user_id: int, entity_uid: str) -> EventEntity:
    row = db.scalar(
        select(EventEntity).where(
            EventEntity.user_id == user_id,
            EventEntity.entity_uid == entity_uid,
        )
    )
    if row is not None:
        return row
    row = EventEntity(
        user_id=user_id,
        entity_uid=entity_uid,
        course_best_json=None,
        course_best_strength=0,
        course_aliases_json=[],
        title_aliases_json=[],
        metadata_json={},
    )
    db.add(row)
    db.flush()
    return row


def update_event_entity_course_profile(
    *,
    entity: EventEntity,
    source_kind: str,
    course_parse: dict,
    source_title: str | None,
) -> str:
    current_best = entity.course_best_json if isinstance(entity.course_best_json, dict) else None
    best_strength = int(entity.course_best_strength or 0)
    new_strength = compute_course_strength(course_parse=course_parse, source_kind=source_kind, title_text=source_title)
    new_display = course_display_name(course_parse=course_parse)

    if new_display and new_strength > best_strength:
        previous_display = entity_best_display_name(current_best)
        if previous_display:
            entity.course_aliases_json = append_alias(entity.course_aliases_json, previous_display, limit=24)
        entity.course_best_json = {
            "course_parse": course_parse,
            "display_name": new_display,
        }
        entity.course_best_strength = new_strength
    elif new_display:
        entity.course_aliases_json = append_alias(entity.course_aliases_json, new_display, limit=24)

    if source_title:
        entity.title_aliases_json = append_alias(entity.title_aliases_json, source_title, limit=24)

    best_display = entity_best_display_name(entity.course_best_json if isinstance(entity.course_best_json, dict) else None)
    return best_display or new_display or "Unknown"


def compute_course_strength(*, course_parse: dict, source_kind: str, title_text: str | None) -> int:
    del source_kind
    del title_text
    score = 0
    if course_parse.get("dept") is not None:
        score += 1
    if course_parse.get("number") is not None:
        score += 1
    if course_parse.get("suffix") is not None:
        score += 1
    if course_parse.get("quarter") is not None:
        score += 1
    if course_parse.get("year2") is not None:
        score += 1
    return score


def course_display_name(*, course_parse: dict) -> str | None:
    dept = _coerce_text(course_parse.get("dept"))
    number = course_parse.get("number")
    if dept is None or not isinstance(number, int):
        return None
    suffix = _coerce_text(course_parse.get("suffix"))
    quarter = _coerce_text(course_parse.get("quarter"))
    year2 = course_parse.get("year2")
    base = f"{dept.upper()} {number}{suffix.upper() if suffix else ''}".strip()
    if quarter and isinstance(year2, int):
        return f"{base} {quarter.upper()}{year2:02d}"[:64]
    return base[:64]


def entity_best_display_name(course_best_json: dict | None) -> str | None:
    if not isinstance(course_best_json, dict):
        return None
    value = course_best_json.get("display_name")
    return value.strip()[:64] if isinstance(value, str) and value.strip() else None


def append_alias(raw: object, candidate: str, *, limit: int) -> list[str]:
    cleaned = candidate.strip()
    if not cleaned:
        return [item for item in raw if isinstance(item, str)] if isinstance(raw, list) else []
    out: list[str] = []
    seen: set[str] = set()
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, str):
                continue
            normalized = item.strip()
            if not normalized:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(normalized[:128])
            if len(out) >= limit:
                break
    key = cleaned.lower()
    if key not in seen:
        out.append(cleaned[:128])
    return out[-limit:]


def is_unknown_course_label(value: str | None) -> bool:
    if not isinstance(value, str):
        return True
    cleaned = value.strip().lower()
    return cleaned in {"", "unknown", "n/a", "none"}


def _coerce_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None

__all__ = [
    "append_alias",
    "compute_course_strength",
    "course_display_name",
    "entity_best_display_name",
    "get_or_create_event_entity",
    "is_unknown_course_label",
    "update_event_entity_course_profile",
]
