from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import EventEntity, SourceEventObservation


def normalize_review_note(note: str | None, *, max_len: int = 512) -> str | None:
    if not isinstance(note, str):
        return None
    normalized = note.strip()
    if not normalized:
        return None
    return normalized[:max_len]


def dedupe_ids_preserve_order(ids: list[int]) -> list[int]:
    seen: set[int] = set()
    out: list[int] = []
    for raw in ids:
        normalized = int(raw)
        if normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


def load_entity_preview(*, db: Session, user_id: int, entity_uid: str | None) -> dict | None:
    if not isinstance(entity_uid, str) or not entity_uid.strip():
        return None
    row = db.scalar(
        select(EventEntity).where(
            EventEntity.user_id == user_id,
            EventEntity.entity_uid == entity_uid,
        )
    )
    if row is None:
        return {"entity_uid": entity_uid, "course_best_display": None, "course_best_strength": None}

    course_best = row.course_best_json if isinstance(row.course_best_json, dict) else {}
    display_name = course_best.get("display_name") if isinstance(course_best.get("display_name"), str) else None
    return {
        "entity_uid": row.entity_uid,
        "course_best_display": display_name,
        "course_best_strength": int(row.course_best_strength or 0),
    }


def load_observation_snapshot(
    *,
    db: Session,
    user_id: int,
    source_id: int,
    external_event_id: str,
) -> dict | None:
    row = db.scalar(
        select(SourceEventObservation).where(
            SourceEventObservation.user_id == user_id,
            SourceEventObservation.source_id == source_id,
            SourceEventObservation.external_event_id == external_event_id,
        )
    )
    if row is None:
        return None

    payload = row.event_payload if isinstance(row.event_payload, dict) else {}
    source_canonical = payload.get("source_canonical") if isinstance(payload.get("source_canonical"), dict) else {}
    return {
        "merge_key": row.merge_key,
        "source_kind": row.source_kind.value,
        "source_title": source_canonical.get("source_title"),
        "source_dtstart_utc": source_canonical.get("source_dtstart_utc"),
        "source_dtend_utc": source_canonical.get("source_dtend_utc"),
        "is_active": row.is_active,
    }
