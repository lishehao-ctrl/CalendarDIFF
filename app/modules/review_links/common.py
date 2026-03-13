from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.review import EventEntity, SourceEventObservation
from app.modules.common.event_display import event_display_dict
from app.modules.common.family_labels import load_latest_family_labels, resolve_family_label
from app.modules.common.payload_schemas import SourceFacts
from app.modules.common.semantic_codec import approved_entity_to_semantic_payload


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
    entity_row = db.scalar(
        select(EventEntity).where(
            EventEntity.user_id == user_id,
            EventEntity.entity_uid == entity_uid,
        )
    )
    if entity_row is not None:
        latest_family_labels = load_latest_family_labels(db, user_id=user_id, family_ids=[entity_row.family_id])
        event_display = event_display_dict(
            approved_entity_to_semantic_payload(
                entity_row,
                family_name_override=resolve_family_label(
                    family_id=entity_row.family_id,
                    snapshot_family_name=entity_row.family_name,
                    latest_family_labels=latest_family_labels,
                ),
            ),
            strict=False,
        )
        if event_display is not None:
            return {"entity_uid": entity_uid, "event_display": event_display}

    observation = db.scalar(
        select(SourceEventObservation)
        .where(
            SourceEventObservation.user_id == user_id,
            SourceEventObservation.entity_uid == entity_uid,
            SourceEventObservation.is_active.is_(True),
        )
        .order_by(SourceEventObservation.observed_at.desc(), SourceEventObservation.id.desc())
        .limit(1)
    )
    if observation is not None:
        payload = observation.event_payload if isinstance(observation.event_payload, dict) else {}
        semantic_event = payload.get("semantic_event") if isinstance(payload.get("semantic_event"), dict) else None
        return {"entity_uid": entity_uid, "event_display": event_display_dict(semantic_event, strict=False) if semantic_event is not None else None}
    return {"entity_uid": entity_uid, "event_display": None}


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
    source_facts_raw = payload.get("source_facts")
    try:
        source_facts = SourceFacts.model_validate(source_facts_raw if isinstance(source_facts_raw, dict) else {})
    except Exception:
        source_facts = None
    return {
        "entity_uid": row.entity_uid,
        "source_kind": row.source_kind.value,
        "source_title": source_facts.source_title if source_facts is not None else None,
        "source_dtstart_utc": source_facts.source_dtstart_utc if source_facts is not None else None,
        "source_dtend_utc": source_facts.source_dtend_utc if source_facts is not None else None,
        "is_active": row.is_active,
    }


def build_batch_result_success(
    *,
    item_id: int,
    status: str,
    idempotent: bool,
    extras: dict | None = None,
) -> dict:
    payload = {
        "id": item_id,
        "ok": True,
        "status": status,
        "idempotent": idempotent,
    }
    if isinstance(extras, dict):
        payload.update(extras)
    return payload


def build_batch_result_error(
    *,
    item_id: int,
    error_code: str,
    error_detail: str,
    extras: dict | None = None,
) -> dict:
    payload = {
        "id": item_id,
        "ok": False,
        "status": None,
        "idempotent": False,
        "error_code": error_code,
        "error_detail": error_detail,
    }
    if isinstance(extras, dict):
        payload.update(extras)
    return payload
