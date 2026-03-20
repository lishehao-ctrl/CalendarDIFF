from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.contracts.events import new_event
from app.db.models.input import IngestTriggerType, InputSource, SyncRequest, SyncRequestStage, SyncRequestStatus
from app.db.models.shared import IntegrationOutbox, OutboxStatus
from app.modules.runtime.kernel import build_sync_progress_payload, set_sync_runtime_state


def enqueue_sync_request(
    db: Session,
    *,
    source: InputSource,
    trigger_type: IngestTriggerType,
    idempotency_key: str,
    metadata: dict | None = None,
    trace_id: str | None = None,
) -> SyncRequest:
    row = enqueue_sync_request_in_txn(
        db,
        source=source,
        trigger_type=trigger_type,
        idempotency_key=idempotency_key,
        metadata=metadata,
        trace_id=trace_id,
    )
    db.commit()
    db.refresh(row)
    return row


def enqueue_sync_request_in_txn(
    db: Session,
    *,
    source: InputSource,
    trigger_type: IngestTriggerType,
    idempotency_key: str,
    metadata: dict | None = None,
    trace_id: str | None = None,
) -> SyncRequest:
    request_id = uuid4().hex
    row = SyncRequest(
        request_id=request_id,
        source_id=source.id,
        trigger_type=trigger_type,
        status=SyncRequestStatus.PENDING,
        stage=SyncRequestStage.CONNECTOR_FETCH,
        idempotency_key=idempotency_key[:255],
        trace_id=trace_id,
        metadata_json=metadata or {},
    )
    set_sync_runtime_state(
        row,
        status=SyncRequestStatus.PENDING,
        stage=SyncRequestStage.CONNECTOR_FETCH,
        substage="queued",
        progress=build_sync_progress_payload(
            phase="pending",
            label="Waiting for source turn",
            detail="This sync is waiting to be enqueued for source processing.",
        ),
    )
    db.add(row)
    db.flush()
    _append_outbox_event(
        db,
        event_type="sync.requested",
        aggregate_type="sync_request",
        aggregate_id=request_id,
        payload={
            "request_id": request_id,
            "source_id": source.id,
            "trigger_type": trigger_type.value,
            "provider": source.provider,
        },
    )
    return row


def enqueue_sync_request_idempotent(
    db: Session,
    *,
    source: InputSource,
    trigger_type: IngestTriggerType,
    idempotency_key: str,
    metadata: dict | None = None,
    trace_id: str | None = None,
) -> SyncRequest:
    try:
        return enqueue_sync_request(
            db,
            source=source,
            trigger_type=trigger_type,
            idempotency_key=idempotency_key,
            metadata=metadata,
            trace_id=trace_id,
        )
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(SyncRequest).where(
                SyncRequest.source_id == source.id,
                SyncRequest.idempotency_key == idempotency_key[:255],
            )
        )
        if existing is None:
            raise
        return existing


def enqueue_sync_request_idempotent_in_txn(
    db: Session,
    *,
    source: InputSource,
    trigger_type: IngestTriggerType,
    idempotency_key: str,
    metadata: dict | None = None,
    trace_id: str | None = None,
) -> SyncRequest:
    existing = db.scalar(
        select(SyncRequest).where(
            SyncRequest.source_id == source.id,
            SyncRequest.idempotency_key == idempotency_key[:255],
        )
    )
    if existing is not None:
        return existing
    return enqueue_sync_request_in_txn(
        db,
        source=source,
        trigger_type=trigger_type,
        idempotency_key=idempotency_key,
        metadata=metadata,
        trace_id=trace_id,
    )


def get_sync_request_status(db: Session, *, request_id: str) -> SyncRequest | None:
    return db.scalar(select(SyncRequest).where(SyncRequest.request_id == request_id))


def _append_outbox_event(
    db: Session,
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    payload: dict,
) -> None:
    event = new_event(
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        payload=payload,
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
    "enqueue_sync_request",
    "enqueue_sync_request_idempotent",
    "enqueue_sync_request_idempotent_in_txn",
    "enqueue_sync_request_in_txn",
    "get_sync_request_status",
]
