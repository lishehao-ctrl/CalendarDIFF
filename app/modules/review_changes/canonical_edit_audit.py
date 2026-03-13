from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.events import new_event
from app.db.models.review import Change, ReviewStatus
from app.db.models.shared import IntegrationOutbox, OutboxStatus


def reject_conflicting_pending_changes(
    *,
    db: Session,
    user_id: int,
    entity_uid: str,
    reviewed_at: datetime,
    reviewed_by_user_id: int,
    canonical_edit_change_id: int,
) -> list[int]:
    pending_rows = db.scalars(
        select(Change)
        .where(
            Change.user_id == user_id,
            Change.entity_uid == entity_uid,
            Change.review_status == ReviewStatus.PENDING,
        )
        .with_for_update()
    ).all()
    rejected_ids: list[int] = []
    for row in pending_rows:
        if row.id == canonical_edit_change_id:
            continue
        row.review_status = ReviewStatus.REJECTED
        row.reviewed_at = reviewed_at
        row.review_note = f"superseded_by_canonical_edit:{canonical_edit_change_id}"
        row.reviewed_by_user_id = reviewed_by_user_id
        rejected_ids.append(int(row.id))
    rejected_ids.sort()
    return rejected_ids


def emit_canonical_edit_audit_event(
    *,
    db: Session,
    change_id: int,
    entity_uid: str,
    reviewed_by_user_id: int,
    reviewed_at: datetime,
    rejected_pending_change_ids: list[int],
) -> None:
    event = new_event(
        event_type="review.decision.approved",
        aggregate_type="change",
        aggregate_id=str(change_id),
        payload={
            "change_id": change_id,
            "entity_uid": entity_uid,
            "review_status": ReviewStatus.APPROVED.value,
            "reviewed_by_user_id": reviewed_by_user_id,
            "reviewed_at": reviewed_at.isoformat(),
            "decision_origin": "canonical_edit",
            "canonical_edit_change_id": change_id,
            "rejected_pending_change_ids": list(rejected_pending_change_ids),
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


__all__ = [
    "emit_canonical_edit_audit_event",
    "reject_conflicting_pending_changes",
]
