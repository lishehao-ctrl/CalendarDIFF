from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.db.models.input import IngestTriggerType, InputSource, SourceKind, SyncRequest, SyncRequestStatus
from app.db.models.shared import IntegrationOutbox, OutboxStatus, User
from app.modules.core_ingest.worker import run_core_apply_tick


def test_core_apply_worker_marks_sync_request_failed_on_apply_exception(db_session) -> None:
    now = datetime.now(timezone.utc)
    user = User(
        email="worker-owner@example.com",
        notify_email="worker-owner@example.com",
        onboarding_completed_at=now,
    )
    db_session.add(user)
    db_session.flush()

    source = InputSource(
        user_id=user.id,
        source_kind=SourceKind.CALENDAR,
        provider="ics",
        source_key="worker-failure-source",
        display_name="Worker Failure Source",
        is_active=True,
        poll_interval_seconds=900,
        next_poll_at=now,
    )
    db_session.add(source)
    db_session.flush()

    request_id = "worker-failure-req-1"
    sync_request = SyncRequest(
        request_id=request_id,
        source_id=source.id,
        trigger_type=IngestTriggerType.MANUAL,
        status=SyncRequestStatus.RUNNING,
        idempotency_key=f"idemp:{request_id}",
        metadata_json={"kind": "test"},
    )
    db_session.add(sync_request)
    db_session.add(
        IntegrationOutbox(
            event_id="worker-failure-event-1",
            event_type="ingest.result.ready",
            aggregate_type="ingest_result",
            aggregate_id=request_id,
            payload_json={"request_id": request_id, "source_id": source.id},
            status=OutboxStatus.PENDING,
            available_at=now,
            attempt=0,
        )
    )
    db_session.commit()

    processed = run_core_apply_tick(db_session)
    assert processed == 1

    outbox_row = db_session.scalar(select(IntegrationOutbox).where(IntegrationOutbox.event_id == "worker-failure-event-1"))
    assert outbox_row is not None
    assert outbox_row.status == OutboxStatus.FAILED
    assert outbox_row.last_error is not None

    refreshed_sync = db_session.scalar(select(SyncRequest).where(SyncRequest.request_id == request_id))
    assert refreshed_sync is not None
    assert refreshed_sync.status == SyncRequestStatus.FAILED
    assert refreshed_sync.error_code == "apply_failed"
    assert refreshed_sync.error_message is not None

    refreshed_source = db_session.get(InputSource, source.id)
    assert refreshed_source is not None
    assert refreshed_source.last_error_code == "apply_failed"
    assert refreshed_source.last_error_message is not None
    assert refreshed_source.cursor is None
