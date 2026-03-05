from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.review import Change, ChangeType, Event, ReviewStatus
from app.modules.review_changes.change_event_codec import event_json_equivalent, parse_after_json, safe_delta_seconds
from app.modules.review_changes.manual_correction_audit import emit_manual_correction_audit_event, reject_conflicting_pending_changes
from app.modules.review_changes.manual_correction_builder import build_candidate_after, manual_payload_from_event_json
from app.modules.review_changes.manual_correction_errors import ManualCorrectionValidationError
from app.modules.review_changes.manual_correction_snapshot import load_base_snapshot
from app.modules.review_changes.manual_correction_target import ensure_canonical_input_for_user, load_user_or_raise, resolve_target_event_uid


def execute_manual_correction_apply_txn(
    db: Session,
    *,
    user_id: int,
    change_id: int | None,
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
    if idempotent:
        return {
            "applied": True,
            "idempotent": True,
            "correction_change_id": None,
            "event_uid": resolved_event_uid,
            "rejected_pending_change_ids": [],
            "event": manual_payload_from_event_json(candidate_after),
        }

    now = datetime.now(timezone.utc)
    parsed_after = parse_after_json(resolved_event_uid, candidate_after)
    if parsed_after is None:
        raise ManualCorrectionValidationError("manual correction produced invalid event payload")

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

    reason_text = (reason or "").strip()
    manual_note = f"manual_correction:{reason_text}" if reason_text else "manual_correction"
    correction_change = Change(
        input_id=canonical_input.id,
        event_uid=resolved_event_uid,
        change_type=change_type,
        detected_at=now,
        before_json=before_json,
        after_json=candidate_after,
        delta_seconds=delta_seconds,
        viewed_at=None,
        viewed_note=None,
        review_status=ReviewStatus.APPROVED,
        reviewed_at=now,
        review_note=manual_note,
        reviewed_by_user_id=user_id,
        proposal_merge_key=resolved_event_uid,
        proposal_sources_json=[],
        before_snapshot_id=None,
        after_snapshot_id=None,
        evidence_keys=None,
    )
    db.add(correction_change)
    db.flush()
    correction_change_id = int(correction_change.id)
    rejected_pending_change_ids = reject_conflicting_pending_changes(
        db=db,
        canonical_input_id=canonical_input.id,
        event_uid=resolved_event_uid,
        reviewed_at=now,
        reviewed_by_user_id=user_id,
        correction_change_id=correction_change_id,
    )
    emit_manual_correction_audit_event(
        db=db,
        change_id=correction_change_id,
        event_uid=resolved_event_uid,
        reviewed_by_user_id=user_id,
        reviewed_at=now,
        rejected_pending_change_ids=rejected_pending_change_ids,
    )
    db.commit()
    return {
        "applied": True,
        "idempotent": False,
        "correction_change_id": correction_change_id,
        "event_uid": resolved_event_uid,
        "rejected_pending_change_ids": rejected_pending_change_ids,
        "event": manual_payload_from_event_json(candidate_after),
    }


__all__ = ["execute_manual_correction_apply_txn"]
