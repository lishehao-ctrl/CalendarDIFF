from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.review import Change, ChangeOrigin, ChangeType, EventEntity, EventEntityLifecycle, ReviewStatus
from app.modules.runtime.apply.change_evidence import freeze_semantic_evidence
from app.modules.common.semantic_codec import parse_semantic_payload, semantic_delta_seconds, semantic_payloads_equivalent
from app.modules.changes.approved_entity_state import apply_approved_entity_state
from app.modules.changes.canonical_edit_audit import emit_canonical_edit_audit_event, reject_conflicting_pending_changes
from app.modules.changes.canonical_edit_builder import build_candidate_after, edit_payload_from_event_json
from app.modules.changes.canonical_edit_errors import CanonicalEditValidationError
from app.modules.changes.canonical_edit_snapshot import load_semantic_base_payload
from app.modules.changes.canonical_edit_target import load_user_or_raise, resolve_target_entity_uid


def execute_canonical_edit_apply_txn(
    db: Session,
    *,
    user_id: int,
    change_id: int | None,
    entity_uid: str | None,
    patch: dict,
    reason: str | None,
) -> dict:
    load_user_or_raise(db, user_id=user_id)
    resolved_entity_uid = resolve_target_entity_uid(
        db,
        user_id=user_id,
        change_id=change_id,
        entity_uid=entity_uid,
    )
    existing_entity = db.scalar(
        select(EventEntity)
        .where(
            EventEntity.user_id == user_id,
            EventEntity.entity_uid == resolved_entity_uid,
        )
        .with_for_update()
    )
    approved_payload, existing_entity = load_semantic_base_payload(
        db=db,
        user_id=user_id,
        entity_uid=resolved_entity_uid,
        existing_entity=existing_entity,
    )
    candidate_after = build_candidate_after(
        entity_uid=resolved_entity_uid,
        base_payload=approved_payload,
        patch=patch,
    )
    idempotent = existing_entity is not None and semantic_payloads_equivalent(approved_payload, candidate_after)
    if idempotent:
        if existing_entity is not None and not existing_entity.manual_support:
            existing_entity.manual_support = True
            db.commit()
        return {
            "applied": True,
            "idempotent": True,
            "canonical_edit_change_id": None,
            "entity_uid": resolved_entity_uid,
            "rejected_pending_change_ids": [],
            "event": edit_payload_from_event_json(candidate_after),
        }

    now = datetime.now(timezone.utc)
    parsed_after = parse_semantic_payload(resolved_entity_uid, candidate_after)
    if parsed_after is None:
        raise CanonicalEditValidationError("canonical edit produced invalid event payload")

    creating_entity = (
        existing_entity is None
        or existing_entity.lifecycle != EventEntityLifecycle.ACTIVE
        or existing_entity.event_name is None
        or existing_entity.due_date is None
    )
    if creating_entity:
        change_type = ChangeType.CREATED
        before_semantic_json = None
        delta_seconds = None
    else:
        change_type = ChangeType.DUE_CHANGED
        before_semantic_json = approved_payload
        delta_seconds = semantic_delta_seconds(before_payload=approved_payload, after_payload=candidate_after)

    approved_entity = apply_approved_entity_state(
        db=db,
        user_id=user_id,
        entity_uid=resolved_entity_uid,
        change_type=change_type,
        semantic_payload=candidate_after,
    )
    if approved_entity is not None:
        approved_entity.manual_support = True

    reason_text = (reason or "").strip()
    edit_note = f"canonical_edit:{reason_text}" if reason_text else "canonical_edit"
    before_evidence = freeze_semantic_evidence(provider=None, semantic_payload=before_semantic_json) if before_semantic_json is not None else None
    after_evidence = freeze_semantic_evidence(provider=None, semantic_payload=candidate_after)

    canonical_edit_change = Change(
        user_id=user_id,
        entity_uid=resolved_entity_uid,
        change_origin=ChangeOrigin.MANUAL_CANONICAL_EDIT,
        change_type=change_type,
        detected_at=now,
        before_semantic_json=before_semantic_json,
        after_semantic_json=candidate_after,
        delta_seconds=delta_seconds,
        before_evidence_json=before_evidence.model_dump(mode="json") if before_evidence is not None else None,
        after_evidence_json=after_evidence.model_dump(mode="json") if after_evidence is not None else None,
        viewed_at=None,
        viewed_note=None,
        review_status=ReviewStatus.APPROVED,
        reviewed_at=now,
        review_note=edit_note,
        reviewed_by_user_id=user_id,
    )
    db.add(canonical_edit_change)
    db.flush()
    canonical_edit_change_id = int(canonical_edit_change.id)

    rejected_pending_change_ids = reject_conflicting_pending_changes(
        db=db,
        user_id=user_id,
        entity_uid=resolved_entity_uid,
        reviewed_at=now,
        reviewed_by_user_id=user_id,
        canonical_edit_change_id=canonical_edit_change_id,
    )
    emit_canonical_edit_audit_event(
        db=db,
        change_id=canonical_edit_change_id,
        entity_uid=resolved_entity_uid,
        reviewed_by_user_id=user_id,
        reviewed_at=now,
        rejected_pending_change_ids=rejected_pending_change_ids,
    )
    db.commit()

    return {
        "applied": True,
        "idempotent": False,
        "canonical_edit_change_id": canonical_edit_change_id,
        "entity_uid": resolved_entity_uid,
        "rejected_pending_change_ids": rejected_pending_change_ids,
        "event": edit_payload_from_event_json(candidate_after),
    }


__all__ = ["execute_canonical_edit_apply_txn"]
