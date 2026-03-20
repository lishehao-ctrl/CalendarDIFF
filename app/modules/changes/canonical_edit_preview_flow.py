from __future__ import annotations

from sqlalchemy.orm import Session

from app.modules.common.semantic_codec import semantic_delta_seconds, semantic_payloads_equivalent
from app.modules.changes.canonical_edit_builder import build_candidate_after, edit_payload_from_event_json
from app.modules.changes.canonical_edit_snapshot import list_pending_change_ids, load_semantic_base_payload
from app.modules.changes.canonical_edit_target import load_user_or_raise, resolve_target_entity_uid


def build_canonical_edit_preview(
    db: Session,
    *,
    user_id: int,
    change_id: int | None,
    entity_uid: str | None,
    patch: dict,
    reason: str | None,
) -> dict:
    del reason
    load_user_or_raise(db, user_id=user_id)
    resolved_entity_uid = resolve_target_entity_uid(
        db,
        user_id=user_id,
        change_id=change_id,
        entity_uid=entity_uid,
    )
    base_payload, existing_entity = load_semantic_base_payload(
        db=db,
        user_id=user_id,
        entity_uid=resolved_entity_uid,
    )
    candidate_after = build_candidate_after(
        entity_uid=resolved_entity_uid,
        base_payload=base_payload,
        patch=patch,
    )
    will_reject_pending_change_ids = list_pending_change_ids(
        db=db,
        user_id=user_id,
        entity_uid=resolved_entity_uid,
    )
    idempotent = existing_entity is not None and semantic_payloads_equivalent(base_payload, candidate_after)
    delta_seconds = semantic_delta_seconds(before_payload=base_payload, after_payload=candidate_after)
    return {
        "entity_uid": resolved_entity_uid,
        "base": edit_payload_from_event_json(base_payload),
        "candidate_after": edit_payload_from_event_json(candidate_after),
        "delta_seconds": delta_seconds,
        "will_reject_pending_change_ids": will_reject_pending_change_ids,
        "idempotent": idempotent,
    }


__all__ = ["build_canonical_edit_preview"]
