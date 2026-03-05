from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models.review import Change, Input
from app.db.models.shared import IntegrationInbox, IntegrationOutbox, OutboxStatus
from app.modules.notify.service import enqueue_notifications_for_changes

NOTIFICATION_PENDING_CONSUMER = "notification.review_pending_created.v1"
NOTIFICATION_CONSUMER_BATCH_SIZE = 200


def run_notification_enqueue_tick(db: Session) -> int:
    now = datetime.now(timezone.utc)
    rows = db.scalars(
        select(IntegrationOutbox)
        .where(
            IntegrationOutbox.status == OutboxStatus.PENDING,
            IntegrationOutbox.event_type == "review.pending.created",
            IntegrationOutbox.available_at <= now,
        )
        .order_by(IntegrationOutbox.id.asc())
        .with_for_update(skip_locked=True)
        .limit(NOTIFICATION_CONSUMER_BATCH_SIZE)
    ).all()
    processed = 0

    for row in rows:
        payload = row.payload_json if isinstance(row.payload_json, dict) else {}
        try:
            db.add(
                IntegrationInbox(
                    consumer_name=NOTIFICATION_PENDING_CONSUMER,
                    event_id=row.event_id,
                    payload_json=payload,
                )
            )
            db.flush()
        except IntegrityError:
            db.rollback()
            row_in_db = db.get(IntegrationOutbox, row.id)
            if row_in_db is not None:
                row_in_db.status = OutboxStatus.PROCESSED
                row_in_db.processed_at = now
                db.commit()
            processed += 1
            continue

        input_id_raw = payload.get("input_id")
        change_ids_raw = payload.get("change_ids")
        deliver_after_raw = payload.get("deliver_after")

        if not isinstance(input_id_raw, int) or not isinstance(change_ids_raw, list):
            row.status = OutboxStatus.FAILED
            row.attempt += 1
            row.last_error = "invalid review.pending.created payload"
            db.commit()
            processed += 1
            continue

        change_ids = [int(value) for value in change_ids_raw if isinstance(value, int)]
        if not change_ids:
            row.status = OutboxStatus.PROCESSED
            row.processed_at = now
            db.commit()
            processed += 1
            continue

        input_row = db.get(Input, input_id_raw)
        if input_row is None:
            row.status = OutboxStatus.FAILED
            row.attempt += 1
            row.last_error = f"input not found: {input_id_raw}"
            db.commit()
            processed += 1
            continue

        changes = db.scalars(select(Change).where(Change.id.in_(change_ids))).all()

        deliver_after = now
        if isinstance(deliver_after_raw, str):
            try:
                normalized = deliver_after_raw[:-1] + "+00:00" if deliver_after_raw.endswith("Z") else deliver_after_raw
                parsed = datetime.fromisoformat(normalized)
                deliver_after = parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
                deliver_after = deliver_after.astimezone(timezone.utc)
            except Exception:
                deliver_after = now

        enqueue_notifications_for_changes(
            db,
            input=input_row,
            changes=changes,
            deliver_after=deliver_after,
            enqueue_reason="digest_queue",
        )

        row.status = OutboxStatus.PROCESSED
        row.processed_at = now
        db.commit()
        processed += 1

    return processed
