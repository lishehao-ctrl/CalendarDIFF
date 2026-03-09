from __future__ import annotations

from sqlalchemy.orm import Session

from app.modules.review_changes.change_event_codec import event_json_equivalent, safe_delta_seconds
from app.modules.review_changes.canonical_edit_builder import build_candidate_after, edit_payload_from_event_json
from app.modules.review_changes.canonical_edit_snapshot import list_pending_change_ids, load_base_snapshot
from app.modules.review_changes.canonical_edit_target import ensure_canonical_input_for_user, load_user_or_raise, resolve_target_event_uid


def build_canonical_edit_preview(
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
    del reason
    user = load_user_or_raise(db, user_id=user_id)
    canonical_input = ensure_canonical_input_for_user(db=db, user_id=user_id)
    resolved_event_uid = resolve_target_event_uid(
        db,
        user_id=user_id,
        change_id=change_id,
        event_uid=event_uid,
    )
    base_snapshot, existing_event = load_base_snapshot(
        db=db,
        canonical_input_id=canonical_input.id,
        event_uid=resolved_event_uid,
    )
    candidate_after = build_candidate_after(
        event_uid=resolved_event_uid,
        base_snapshot=base_snapshot,
        due_at=due_at,
        title=title,
        course_label=course_label,
        timezone_name=user.timezone_name,
    )
    will_reject_pending_change_ids = list_pending_change_ids(
        db=db,
        canonical_input_id=canonical_input.id,
        event_uid=resolved_event_uid,
    )
    idempotent = existing_event is not None and event_json_equivalent(base_snapshot, candidate_after)
    delta_seconds = safe_delta_seconds(before_json=base_snapshot, after_json=candidate_after)
    return {
        "event_uid": resolved_event_uid,
        "base": edit_payload_from_event_json(base_snapshot),
        "candidate_after": edit_payload_from_event_json(candidate_after),
        "delta_seconds": delta_seconds,
        "will_reject_pending_change_ids": will_reject_pending_change_ids,
        "idempotent": idempotent,
    }


__all__ = ["build_canonical_edit_preview"]
