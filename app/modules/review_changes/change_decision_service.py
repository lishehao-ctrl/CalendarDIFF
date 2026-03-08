from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.events import new_event
from app.db.models.review import Change, ChangeType, Event, Input, ReviewStatus
from app.db.models.shared import IntegrationOutbox, OutboxStatus
from app.modules.review_changes.change_event_codec import (
    event_json_equivalent,
    event_row_to_json,
    parse_after_json,
    parse_iso_datetime,
    safe_delta_seconds,
)
from app.modules.review_links.common import dedupe_ids_preserve_order, normalize_review_note


class ReviewChangeNotFoundError(RuntimeError):
    pass


def mark_review_change_viewed(
    db: Session,
    *,
    user_id: int,
    change_id: int,
    viewed: bool,
    note: str | None,
) -> Change:
    row = db.scalar(
        select(Change)
        .join(Input, Input.id == Change.input_id)
        .where(Change.id == change_id, Input.user_id == user_id)
        .with_for_update()
    )
    if row is None:
        raise ReviewChangeNotFoundError("Review change not found")

    if viewed:
        row.viewed_at = datetime.now(timezone.utc)
        row.viewed_note = note
    else:
        row.viewed_at = None
        row.viewed_note = None

    db.commit()
    db.refresh(row)
    return row


def decide_review_change(
    db: Session,
    *,
    user_id: int,
    change_id: int,
    decision: str,
    note: str | None,
) -> tuple[Change, bool]:
    row = db.scalar(
        select(Change)
        .join(Input, Input.id == Change.input_id)
        .where(Change.id == change_id, Input.user_id == user_id)
        .with_for_update()
    )
    if row is None:
        raise ReviewChangeNotFoundError("Review change not found")

    if row.review_status != ReviewStatus.PENDING:
        return row, True

    now = datetime.now(timezone.utc)
    if decision == "approve":
        apply_change_to_canonical_event(db=db, change=row)
        row.review_status = ReviewStatus.APPROVED
    else:
        row.review_status = ReviewStatus.REJECTED

    row.reviewed_at = now
    row.review_note = note
    row.reviewed_by_user_id = user_id

    event = new_event(
        event_type=f"review.decision.{decision}",
        aggregate_type="change",
        aggregate_id=str(row.id),
        payload={
            "change_id": row.id,
            "event_uid": row.event_uid,
            "review_status": row.review_status.value,
            "reviewed_by_user_id": user_id,
            "reviewed_at": now.isoformat(),
        },
    )
    db.add(
        IntegrationOutbox(
            event_id=event.event_id,
            event_type=event.event_type,
            aggregate_type=event.aggregate_type,
            aggregate_id=event.aggregate_id,
            payload_json=event.payload,
            status=OutboxStatus.PENDING,
            available_at=event.available_at,
        )
    )

    db.commit()
    db.refresh(row)
    return row, False


def batch_decide_review_changes(
    db: Session,
    *,
    user_id: int,
    decision: str,
    ids: list[int],
    note: str | None,
) -> dict:
    normalized_note = normalize_review_note(note)
    deduped_ids = dedupe_ids_preserve_order(ids)
    results: list[dict] = []
    succeeded = 0

    for change_id in deduped_ids:
        try:
            row, idempotent = decide_review_change(
                db=db,
                user_id=user_id,
                change_id=change_id,
                decision=decision,
                note=normalized_note,
            )
            results.append(
                {
                    "id": change_id,
                    "ok": True,
                    "review_status": row.review_status.value,
                    "idempotent": idempotent,
                    "reviewed_at": row.reviewed_at,
                    "review_note": row.review_note,
                    "error_code": None,
                    "error_detail": None,
                }
            )
            succeeded += 1
        except ReviewChangeNotFoundError:
            results.append(
                {
                    "id": change_id,
                    "ok": False,
                    "review_status": None,
                    "idempotent": False,
                    "reviewed_at": None,
                    "review_note": None,
                    "error_code": "not_found",
                    "error_detail": "Review change not found",
                }
            )

    return {
        "decision": decision,
        "total_requested": len(deduped_ids),
        "succeeded": succeeded,
        "failed": len(deduped_ids) - succeeded,
        "results": results,
    }


def apply_change_to_canonical_event(*, db: Session, change: Change) -> None:
    existing = db.scalar(
        select(Event).where(
            Event.input_id == change.input_id,
            Event.uid == change.event_uid,
        )
    )

    if change.change_type == ChangeType.REMOVED:
        if existing is not None:
            db.delete(existing)
        return

    after_json = change.after_json if isinstance(change.after_json, dict) else None
    if after_json is None:
        return

    parsed = parse_after_json(change.event_uid, after_json)
    if parsed is None:
        return

    if existing is None:
        db.add(
            Event(
                input_id=change.input_id,
                uid=change.event_uid,
                course_label=parsed["course_label"],
                title=parsed["title"],
                start_at_utc=parsed["start_at_utc"],
                end_at_utc=parsed["end_at_utc"],
            )
        )
        return

    existing.course_label = parsed["course_label"]
    existing.title = parsed["title"]
    existing.start_at_utc = parsed["start_at_utc"]
    existing.end_at_utc = parsed["end_at_utc"]


__all__ = [
    "ReviewChangeNotFoundError",
    "apply_change_to_canonical_event",
    "batch_decide_review_changes",
    "decide_review_change",
    "event_json_equivalent",
    "event_row_to_json",
    "mark_review_change_viewed",
    "parse_after_json",
    "parse_iso_datetime",
    "safe_delta_seconds",
]
