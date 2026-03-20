from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.events import new_event
from app.db.models.review import Change, ChangeType, ReviewStatus
from app.db.models.shared import IntegrationOutbox, OutboxStatus
from app.modules.common.semantic_codec import (
    parse_semantic_payload,
    parse_iso_datetime,
    semantic_delta_seconds,
    semantic_payloads_equivalent,
)
from app.modules.changes.common import dedupe_ids_preserve_order, normalize_review_note
from app.modules.changes.approved_entity_state import apply_approved_entity_state


class ChangeNotFoundError(RuntimeError):
    pass


def mark_change_viewed(
    db: Session,
    *,
    user_id: int,
    change_id: int,
    viewed: bool,
    note: str | None,
) -> Change:
    row = db.scalar(
        select(Change).where(Change.id == change_id, Change.user_id == user_id).with_for_update()
    )
    if row is None:
        raise ChangeNotFoundError("Review change not found")

    if viewed:
        row.viewed_at = datetime.now(timezone.utc)
        row.viewed_note = note
    else:
        row.viewed_at = None
        row.viewed_note = None

    db.commit()
    db.refresh(row)
    return row


def decide_change(
    db: Session,
    *,
    user_id: int,
    change_id: int,
    decision: str,
    note: str | None,
) -> tuple[Change, bool]:
    row = db.scalar(
        select(Change).where(Change.id == change_id, Change.user_id == user_id).with_for_update()
    )
    if row is None:
        raise ChangeNotFoundError("Review change not found")

    if row.review_status != ReviewStatus.PENDING:
        return row, True

    now = datetime.now(timezone.utc)
    if decision == "approve":
        apply_change_to_approved_entity_state(db=db, change=row)
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
            "entity_uid": row.entity_uid,
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


def batch_decide_changes(
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
            row, idempotent = decide_change(
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
        except ChangeNotFoundError:
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


def apply_change_to_approved_entity_state(*, db: Session, change: Change) -> None:
    approved_payload = change.after_semantic_json if isinstance(change.after_semantic_json, dict) else None
    apply_approved_entity_state(
        db=db,
        user_id=change.user_id,
        entity_uid=change.entity_uid,
        change_type=change.change_type,
        semantic_payload=approved_payload,
    )


__all__ = [
    "ChangeNotFoundError",
    "apply_change_to_approved_entity_state",
    "batch_decide_changes",
    "decide_change",
    "mark_change_viewed",
    "parse_semantic_payload",
    "parse_iso_datetime",
    "semantic_delta_seconds",
    "semantic_payloads_equivalent",
]
