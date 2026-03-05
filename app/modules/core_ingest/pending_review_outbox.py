from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.contracts.events import new_event
from app.db.models.review import Change
from app.db.models.shared import IntegrationOutbox, OutboxStatus


def emit_review_pending_created_event(
    *,
    db: Session,
    canonical_input_id: int,
    changes: list[Change],
    detected_at: datetime,
) -> None:
    change_ids = [int(change.id) for change in changes if isinstance(change.id, int)]
    if not change_ids:
        return
    event = new_event(
        event_type="review.pending.created",
        aggregate_type="change_batch",
        aggregate_id=str(change_ids[0]),
        payload={
            "input_id": canonical_input_id,
            "change_ids": change_ids,
            "deliver_after": detected_at.isoformat(),
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


__all__ = ["emit_review_pending_created_event"]
