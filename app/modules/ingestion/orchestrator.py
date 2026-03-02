from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import Select, and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.contracts.events import new_event
from app.db.models import (
    IngestJob,
    IngestJobStatus,
    IngestTriggerType,
    InputSource,
    IntegrationInbox,
    IntegrationOutbox,
    OutboxStatus,
    SyncRequest,
    SyncRequestStatus,
)

ORCHESTRATOR_SYNC_REQUEST_CONSUMER = "orchestrator.sync_requested.v1"
OUTBOX_BATCH_SIZE = 200


def run_orchestrator_tick(db: Session, *, worker_id: str) -> int:
    created = _enqueue_due_scheduler_requests(db, worker_id=worker_id)
    consumed = _consume_sync_requested_events(db, worker_id=worker_id)
    return created + consumed


def _enqueue_due_scheduler_requests(db: Session, *, worker_id: str) -> int:
    now = datetime.now(timezone.utc)
    due_stmt: Select[tuple[InputSource]] = (
        select(InputSource)
        .where(
            InputSource.is_active.is_(True),
            and_(
                InputSource.next_poll_at.is_not(None),
                InputSource.next_poll_at <= now,
            ),
        )
        .order_by(InputSource.next_poll_at.asc(), InputSource.id.asc())
        .with_for_update(skip_locked=True)
        .limit(OUTBOX_BATCH_SIZE)
    )
    due_sources = db.scalars(due_stmt).all()
    created = 0
    for source in due_sources:
        interval = max(int(source.poll_interval_seconds), 30)
        slot = int(now.timestamp()) // interval
        idempotency_key = f"scheduler:{source.id}:{slot}"
        existing = db.scalar(
            select(SyncRequest.id).where(
                SyncRequest.source_id == source.id,
                SyncRequest.idempotency_key == idempotency_key,
            )
        )
        if existing is None:
            request_id = uuid4().hex
            sync_request = SyncRequest(
                request_id=request_id,
                source_id=source.id,
                trigger_type=IngestTriggerType.SCHEDULER,
                status=SyncRequestStatus.PENDING,
                idempotency_key=idempotency_key,
                trace_id=f"scheduler:{worker_id}",
                metadata_json={"kind": "scheduler"},
            )
            db.add(sync_request)
            event = new_event(
                event_type="sync.requested",
                aggregate_type="sync_request",
                aggregate_id=request_id,
                payload={
                    "request_id": request_id,
                    "source_id": source.id,
                    "provider": source.provider,
                    "trigger_type": IngestTriggerType.SCHEDULER.value,
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
            created += 1
        source.last_polled_at = now
        source.next_poll_at = now + timedelta(seconds=interval)
    db.commit()
    return created


def _consume_sync_requested_events(db: Session, *, worker_id: str) -> int:
    del worker_id
    now = datetime.now(timezone.utc)
    stmt = (
        select(IntegrationOutbox)
        .where(
            IntegrationOutbox.status == OutboxStatus.PENDING,
            IntegrationOutbox.event_type == "sync.requested",
            IntegrationOutbox.available_at <= now,
        )
        .order_by(IntegrationOutbox.id.asc())
        .with_for_update(skip_locked=True)
        .limit(OUTBOX_BATCH_SIZE)
    )
    rows = db.scalars(stmt).all()
    processed = 0
    for row in rows:
        payload = row.payload_json if isinstance(row.payload_json, dict) else {}
        request_id = str(payload.get("request_id") or "")
        source_id_raw = payload.get("source_id")
        if not request_id or not isinstance(source_id_raw, int):
            row.status = OutboxStatus.FAILED
            row.last_error = "sync.requested event payload missing request_id/source_id"
            row.attempt += 1
            continue

        try:
            db.add(
                IntegrationInbox(
                    consumer_name=ORCHESTRATOR_SYNC_REQUEST_CONSUMER,
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

        existing_job = db.scalar(select(IngestJob.id).where(IngestJob.request_id == request_id))
        if existing_job is None:
            db.add(
                IngestJob(
                    request_id=request_id,
                    source_id=source_id_raw,
                    status=IngestJobStatus.PENDING,
                    attempt=0,
                    next_retry_at=now,
                    payload_json=payload,
                )
            )
        sync_request = db.scalar(select(SyncRequest).where(SyncRequest.request_id == request_id))
        if sync_request is not None and sync_request.status == SyncRequestStatus.PENDING:
            sync_request.status = SyncRequestStatus.QUEUED
        row.status = OutboxStatus.PROCESSED
        row.processed_at = now
        db.commit()
        processed += 1
    return processed
