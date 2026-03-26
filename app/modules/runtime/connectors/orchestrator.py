from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Select, and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.contracts.events import new_event
from app.db.models.runtime import IngestJob, IngestJobStatus
from app.db.models.input import IngestTriggerType, InputSource, SyncRequest, SyncRequestStage, SyncRequestStatus
from app.db.models.shared import IntegrationInbox, IntegrationOutbox, OutboxStatus
from app.modules.common.source_auto_sync_schedule import next_source_auto_sync_at
from app.modules.common.source_monitoring_window import parse_source_monitoring_window, source_timezone_name
from app.modules.runtime.kernel import build_sync_progress_payload, set_sync_runtime_state

ORCHESTRATOR_SYNC_REQUEST_CONSUMER = "orchestrator.sync_requested"
OUTBOX_BATCH_SIZE = 200


def run_orchestrator_tick(db: Session, *, worker_id: str) -> int:
    settings = get_settings()
    created = _enqueue_due_scheduler_requests(db, worker_id=worker_id) if bool(settings.ingest_service_enable_scheduler) else 0
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
        term_window = parse_source_monitoring_window(source, required=False)
        if term_window is not None and term_window.is_expired(now=now, timezone_name=source_timezone_name(source)):
            source.is_active = False
            source.next_poll_at = None
            continue
        next_scheduled_at = next_source_auto_sync_at(now=now, timezone_name=source_timezone_name(source))
        slot = next_scheduled_at.isoformat()
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
                stage=SyncRequestStage.CONNECTOR_FETCH,
                idempotency_key=idempotency_key,
                trace_id=f"scheduler:{worker_id}",
                metadata_json={"kind": "scheduler"},
            )
            set_sync_runtime_state(
                sync_request,
                status=SyncRequestStatus.PENDING,
                stage=SyncRequestStage.CONNECTOR_FETCH,
                substage="queued",
                progress=build_sync_progress_payload(
                    phase="pending",
                    label="Waiting for source turn",
                    detail="This sync is waiting to be enqueued for source processing.",
                ),
                when=now,
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
        source.next_poll_at = next_scheduled_at
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
            set_sync_runtime_state(
                sync_request,
                status=SyncRequestStatus.QUEUED,
                stage=SyncRequestStage.CONNECTOR_FETCH,
                substage="queued",
                progress=build_sync_progress_payload(
                    phase="queued",
                    label="Queued to run",
                    detail="The worker has accepted this sync and will start it soon.",
                ),
                when=now,
            )
        row.status = OutboxStatus.PROCESSED
        row.processed_at = now
        db.commit()
        processed += 1
    return processed
