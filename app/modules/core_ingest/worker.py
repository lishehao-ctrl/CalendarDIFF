from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import IntegrationInbox, IntegrationOutbox, OutboxStatus, SyncRequest, SyncRequestStatus
from app.modules.core_ingest.apply_service import apply_ingest_result_idempotent

CORE_APPLY_CONSUMER = "core.ingest.apply.v1"
CORE_APPLY_BATCH_SIZE = 200
MAX_SYNC_REQUEST_ERROR_LEN = 512


def run_core_apply_tick(db: Session) -> int:
    now = datetime.now(timezone.utc)
    rows = db.scalars(
        select(IntegrationOutbox)
        .where(
            IntegrationOutbox.status == OutboxStatus.PENDING,
            IntegrationOutbox.event_type == "ingest.result.ready",
            IntegrationOutbox.available_at <= now,
        )
        .order_by(IntegrationOutbox.id.asc())
        .with_for_update(skip_locked=True)
        .limit(CORE_APPLY_BATCH_SIZE)
    ).all()
    processed = 0
    for row in rows:
        payload = row.payload_json if isinstance(row.payload_json, dict) else {}
        request_id = str(payload.get("request_id") or "")
        if not request_id:
            row.status = OutboxStatus.FAILED
            row.last_error = "missing request_id in ingest.result.ready payload"
            row.attempt += 1
            continue
        try:
            db.add(
                IntegrationInbox(
                    consumer_name=CORE_APPLY_CONSUMER,
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

        try:
            apply_ingest_result_idempotent(db, request_id=request_id)
            row.status = OutboxStatus.PROCESSED
            row.processed_at = now
            db.commit()
        except Exception as exc:  # pragma: no cover - defensive worker guard
            db.rollback()
            row_in_db = db.get(IntegrationOutbox, row.id)
            if row_in_db is not None:
                row_in_db.status = OutboxStatus.FAILED
                row_in_db.attempt += 1
                row_in_db.last_error = str(exc)[:512]
                sync_request = db.scalar(select(SyncRequest).where(SyncRequest.request_id == request_id))
                if sync_request is not None:
                    sync_request.status = SyncRequestStatus.FAILED
                    sync_request.error_code = "apply_failed"
                    sync_request.error_message = str(exc)[:MAX_SYNC_REQUEST_ERROR_LEN]
                db.commit()
        processed += 1
    return processed
