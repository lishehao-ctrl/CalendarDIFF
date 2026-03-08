from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.review import Change, ChangeType, Input, ReviewStatus
from app.modules.core_ingest.evidence_snapshots import materialize_change_snapshot
from app.modules.review_changes.change_event_codec import event_json_equivalent, parse_after_json, safe_delta_seconds
from app.modules.review_changes.manual_correction_builder import build_candidate_after, manual_payload_from_event_json
from app.modules.review_changes.manual_correction_errors import ManualCorrectionNotFoundError, ManualCorrectionValidationError
from app.modules.review_changes.manual_correction_service import apply_manual_correction, preview_manual_correction
from app.modules.review_changes.manual_correction_target import load_user_or_raise


class ReviewEditNotFoundError(RuntimeError):
    pass


class ReviewEditValidationError(RuntimeError):
    pass


class ReviewEditInvalidStateError(RuntimeError):
    pass


def preview_review_edit(
    db: Session,
    *,
    user_id: int,
    mode: str,
    change_id: int | None,
    event_uid: str | None,
    due_at: str,
    title: str | None,
    course_label: str | None,
    reason: str | None,
) -> dict:
    if mode == "proposal":
        return _preview_proposal_edit(
            db=db,
            user_id=user_id,
            change_id=change_id,
            due_at=due_at,
            title=title,
            course_label=course_label,
        )
    if mode == "canonical":
        try:
            payload = preview_manual_correction(
                db=db,
                user_id=user_id,
                change_id=change_id,
                event_uid=event_uid,
                due_at=due_at,
                title=title,
                course_label=course_label,
                reason=reason,
            )
        except ManualCorrectionNotFoundError as exc:
            raise ReviewEditNotFoundError(str(exc)) from exc
        except ManualCorrectionValidationError as exc:
            raise ReviewEditValidationError(str(exc)) from exc
        return {
            "mode": "canonical",
            "event_uid": payload["event_uid"],
            "change_id": change_id,
            "proposal_change_type": None,
            "base": payload["base"],
            "candidate_after": payload["candidate_after"],
            "delta_seconds": payload["delta_seconds"],
            "will_reject_pending_change_ids": payload["will_reject_pending_change_ids"],
            "idempotent": payload["idempotent"],
        }
    raise ReviewEditValidationError("mode must be one of: proposal, canonical")


def apply_review_edit(
    db: Session,
    *,
    user_id: int,
    mode: str,
    change_id: int | None,
    event_uid: str | None,
    due_at: str,
    title: str | None,
    course_label: str | None,
    reason: str | None,
) -> dict:
    if mode == "proposal":
        return _apply_proposal_edit(
            db=db,
            user_id=user_id,
            change_id=change_id,
            due_at=due_at,
            title=title,
            course_label=course_label,
        )
    if mode == "canonical":
        try:
            payload = apply_manual_correction(
                db=db,
                user_id=user_id,
                change_id=change_id,
                event_uid=event_uid,
                due_at=due_at,
                title=title,
                course_label=course_label,
                reason=reason,
            )
        except ManualCorrectionNotFoundError as exc:
            raise ReviewEditNotFoundError(str(exc)) from exc
        except ManualCorrectionValidationError as exc:
            raise ReviewEditValidationError(str(exc)) from exc
        return {
            "mode": "canonical",
            "applied": payload["applied"],
            "idempotent": payload["idempotent"],
            "event_uid": payload["event_uid"],
            "edited_change_id": None,
            "correction_change_id": payload["correction_change_id"],
            "rejected_pending_change_ids": payload["rejected_pending_change_ids"],
            "event": payload["event"],
        }
    raise ReviewEditValidationError("mode must be one of: proposal, canonical")


def _preview_proposal_edit(
    db: Session,
    *,
    user_id: int,
    change_id: int | None,
    due_at: str,
    title: str | None,
    course_label: str | None,
) -> dict:
    user = load_user_or_raise(db, user_id=user_id)
    row = _load_pending_proposal_change(db=db, user_id=user_id, change_id=change_id, for_update=False)
    base_snapshot = _current_after_snapshot(row)
    candidate_after = build_candidate_after(
        event_uid=row.event_uid,
        base_snapshot=base_snapshot,
        due_at=due_at,
        title=title,
        course_label=course_label,
        timezone_name=user.timezone_name,
    )
    return {
        "mode": "proposal",
        "event_uid": row.event_uid,
        "change_id": row.id,
        "proposal_change_type": row.change_type.value,
        "base": manual_payload_from_event_json(base_snapshot),
        "candidate_after": manual_payload_from_event_json(candidate_after),
        "delta_seconds": _proposal_delta_seconds(row=row, candidate_after=candidate_after),
        "will_reject_pending_change_ids": [],
        "idempotent": event_json_equivalent(base_snapshot, candidate_after),
    }


def _apply_proposal_edit(
    db: Session,
    *,
    user_id: int,
    change_id: int | None,
    due_at: str,
    title: str | None,
    course_label: str | None,
) -> dict:
    user = load_user_or_raise(db, user_id=user_id)
    row = _load_pending_proposal_change(db=db, user_id=user_id, change_id=change_id, for_update=True)
    base_snapshot = _current_after_snapshot(row)
    candidate_after = build_candidate_after(
        event_uid=row.event_uid,
        base_snapshot=base_snapshot,
        due_at=due_at,
        title=title,
        course_label=course_label,
        timezone_name=user.timezone_name,
    )
    now = datetime.now(timezone.utc)
    snapshot_id = materialize_change_snapshot(
        db=db,
        input_id=row.input_id,
        event_payload=None,
        fallback_json=candidate_after,
        retrieved_at=now,
    )
    idempotent = event_json_equivalent(base_snapshot, candidate_after)
    if not idempotent:
        row.after_json = candidate_after
        row.delta_seconds = _proposal_delta_seconds(row=row, candidate_after=candidate_after)
    if snapshot_id is not None:
        row.after_snapshot_id = snapshot_id
    db.commit()
    db.refresh(row)
    return {
        "mode": "proposal",
        "applied": True,
        "idempotent": idempotent,
        "event_uid": row.event_uid,
        "edited_change_id": row.id,
        "correction_change_id": None,
        "rejected_pending_change_ids": [],
        "event": manual_payload_from_event_json(candidate_after),
    }


def _load_pending_proposal_change(
    *,
    db: Session,
    user_id: int,
    change_id: int | None,
    for_update: bool,
) -> Change:
    if change_id is None:
        raise ReviewEditValidationError("proposal edits require target.change_id")
    stmt = (
        select(Change)
        .join(Input, Input.id == Change.input_id)
        .where(Change.id == change_id, Input.user_id == user_id)
        .limit(1)
    )
    if for_update:
        stmt = stmt.with_for_update()
    row = db.scalar(stmt)
    if row is None:
        raise ReviewEditNotFoundError("target change not found")
    if row.review_status != ReviewStatus.PENDING:
        raise ReviewEditInvalidStateError("proposal edits require a pending change")
    if row.change_type not in {ChangeType.CREATED, ChangeType.DUE_CHANGED}:
        raise ReviewEditInvalidStateError("proposal edits only support created or due_changed changes")
    return row


def _current_after_snapshot(row: Change) -> dict:
    after_json = row.after_json if isinstance(row.after_json, dict) else None
    if after_json is None:
        raise ReviewEditValidationError("pending proposal has no editable after_json")
    parsed = parse_after_json(row.event_uid, after_json)
    if parsed is None:
        raise ReviewEditValidationError("pending proposal after_json is invalid")
    return {
        "uid": row.event_uid,
        "title": parsed["title"],
        "course_label": parsed["course_label"],
        "start_at_utc": parsed["start_at_utc"].isoformat(),
        "end_at_utc": parsed["end_at_utc"].isoformat(),
    }


def _proposal_delta_seconds(*, row: Change, candidate_after: dict) -> int | None:
    before_json = row.before_json if isinstance(row.before_json, dict) else None
    if before_json is None:
        return None
    return safe_delta_seconds(before_json=before_json, after_json=candidate_after)


__all__ = [
    "ReviewEditInvalidStateError",
    "ReviewEditNotFoundError",
    "ReviewEditValidationError",
    "apply_review_edit",
    "preview_review_edit",
]
