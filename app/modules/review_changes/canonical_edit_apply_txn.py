from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

<<<<<<< ours
from app.db.models.review import Change, ChangeType, Event, ReviewStatus
from app.modules.review_changes.change_event_codec import event_json_equivalent, parse_after_json, safe_delta_seconds
from app.modules.review_changes.canonical_edit_audit import emit_canonical_edit_audit_event, reject_conflicting_pending_changes
from app.modules.review_changes.canonical_edit_builder import build_candidate_after, edit_payload_from_event_json
from app.modules.review_changes.canonical_edit_errors import CanonicalEditValidationError
from app.modules.review_changes.canonical_edit_snapshot import load_base_snapshot
from app.modules.review_changes.canonical_edit_target import ensure_canonical_input_for_user, load_user_or_raise, resolve_target_event_uid
=======
from app.db.models.review import Change, ChangeOrigin, ChangeType, EventEntity, EventEntityLifecycle, ReviewStatus
from app.modules.core_ingest.review_evidence import freeze_semantic_evidence
from app.modules.common.semantic_codec import parse_semantic_payload, semantic_delta_seconds, semantic_payloads_equivalent
from app.modules.review_changes.approved_entity_state import apply_approved_entity_state
from app.modules.review_changes.canonical_edit_audit import emit_canonical_edit_audit_event, reject_conflicting_pending_changes
from app.modules.review_changes.canonical_edit_builder import build_candidate_after, edit_payload_from_event_json
from app.modules.review_changes.canonical_edit_errors import CanonicalEditValidationError
from app.modules.review_changes.canonical_edit_snapshot import load_semantic_base_payload
from app.modules.review_changes.canonical_edit_target import load_user_or_raise, resolve_target_entity_uid
>>>>>>> theirs


def execute_canonical_edit_apply_txn(
    db: Session,
    *,
    user_id: int,
    change_id: int | None,
<<<<<<< ours
    event_uid: str | None,
    due_at: str,
    title: str | None,
    course_label: str | None,
    reason: str | None,
) -> dict:
    user = load_user_or_raise(db, user_id=user_id)
    canonical_input = ensure_canonical_input_for_user(db=db, user_id=user_id)
    resolved_event_uid = resolve_target_event_uid(
        db,
        user_id=user_id,
        change_id=change_id,
        event_uid=event_uid,
    )
    existing_event = db.scalar(
        select(Event)
        .where(
            Event.input_id == canonical_input.id,
            Event.uid == resolved_event_uid,
        )
        .with_for_update()
    )
    base_snapshot, base_existing_event = load_base_snapshot(
        db=db,
        canonical_input_id=canonical_input.id,
        event_uid=resolved_event_uid,
        existing_event=existing_event,
    )
    candidate_after = build_candidate_after(
        event_uid=resolved_event_uid,
        base_snapshot=base_snapshot,
        due_at=due_at,
        title=title,
        course_label=course_label,
        timezone_name=user.timezone_name,
    )
    idempotent = base_existing_event is not None and event_json_equivalent(base_snapshot, candidate_after)
=======
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
>>>>>>> theirs
    if idempotent:
        return {
            "applied": True,
            "idempotent": True,
            "canonical_edit_change_id": None,
<<<<<<< ours
            "event_uid": resolved_event_uid,
=======
            "entity_uid": resolved_entity_uid,
>>>>>>> theirs
            "rejected_pending_change_ids": [],
            "event": edit_payload_from_event_json(candidate_after),
        }

    now = datetime.now(timezone.utc)
<<<<<<< ours
    parsed_after = parse_after_json(resolved_event_uid, candidate_after)
    if parsed_after is None:
        raise CanonicalEditValidationError("canonical edit produced invalid event payload")

    if existing_event is None:
        db.add(
            Event(
                input_id=canonical_input.id,
                uid=resolved_event_uid,
                course_label=parsed_after["course_label"],
                title=parsed_after["title"],
                start_at_utc=parsed_after["start_at_utc"],
                end_at_utc=parsed_after["end_at_utc"],
            )
        )
        change_type = ChangeType.CREATED
        before_json = None
        delta_seconds = None
    else:
        existing_event.course_label = parsed_after["course_label"]
        existing_event.title = parsed_after["title"]
        existing_event.start_at_utc = parsed_after["start_at_utc"]
        existing_event.end_at_utc = parsed_after["end_at_utc"]
        change_type = ChangeType.DUE_CHANGED
        before_json = base_snapshot
        delta_seconds = safe_delta_seconds(before_json=base_snapshot, after_json=candidate_after)
=======
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

    apply_approved_entity_state(
        db=db,
        user_id=user_id,
        entity_uid=resolved_entity_uid,
        change_type=change_type,
        semantic_payload=candidate_after,
    )
>>>>>>> theirs

    reason_text = (reason or "").strip()
    edit_note = f"canonical_edit:{reason_text}" if reason_text else "canonical_edit"
    canonical_edit_change = Change(
<<<<<<< ours
        input_id=canonical_input.id,
        event_uid=resolved_event_uid,
        change_type=change_type,
        detected_at=now,
        before_json=before_json,
        after_json=candidate_after,
        delta_seconds=delta_seconds,
=======
        user_id=user_id,
        entity_uid=resolved_entity_uid,
        change_origin=ChangeOrigin.MANUAL_CANONICAL_EDIT,
        change_type=change_type,
        detected_at=now,
        before_semantic_json=before_semantic_json,
        after_semantic_json=candidate_after,
        delta_seconds=delta_seconds,
        before_evidence_json=(
            freeze_semantic_evidence(provider=None, semantic_payload=before_semantic_json).model_dump(mode="json")
            if before_semantic_json is not None
            else None
        ),
        after_evidence_json=(
            freeze_semantic_evidence(provider=None, semantic_payload=candidate_after).model_dump(mode="json")
            if candidate_after is not None
            else None
        ),
>>>>>>> theirs
        viewed_at=None,
        viewed_note=None,
        review_status=ReviewStatus.APPROVED,
        reviewed_at=now,
        review_note=edit_note,
        reviewed_by_user_id=user_id,
<<<<<<< ours
        proposal_merge_key=resolved_event_uid,
        proposal_sources_json=[],
        before_snapshot_id=None,
        after_snapshot_id=None,
        evidence_keys=None,
=======
>>>>>>> theirs
    )
    db.add(canonical_edit_change)
    db.flush()
    canonical_edit_change_id = int(canonical_edit_change.id)
    rejected_pending_change_ids = reject_conflicting_pending_changes(
        db=db,
<<<<<<< ours
        canonical_input_id=canonical_input.id,
        event_uid=resolved_event_uid,
=======
        user_id=user_id,
        entity_uid=resolved_entity_uid,
>>>>>>> theirs
        reviewed_at=now,
        reviewed_by_user_id=user_id,
        canonical_edit_change_id=canonical_edit_change_id,
    )
    emit_canonical_edit_audit_event(
        db=db,
        change_id=canonical_edit_change_id,
<<<<<<< ours
        event_uid=resolved_event_uid,
=======
        entity_uid=resolved_entity_uid,
>>>>>>> theirs
        reviewed_by_user_id=user_id,
        reviewed_at=now,
        rejected_pending_change_ids=rejected_pending_change_ids,
    )
    db.commit()
    return {
        "applied": True,
        "idempotent": False,
        "canonical_edit_change_id": canonical_edit_change_id,
<<<<<<< ours
        "event_uid": resolved_event_uid,
=======
        "entity_uid": resolved_entity_uid,
>>>>>>> theirs
        "rejected_pending_change_ids": rejected_pending_change_ids,
        "event": edit_payload_from_event_json(candidate_after),
    }


__all__ = ["execute_canonical_edit_apply_txn"]
