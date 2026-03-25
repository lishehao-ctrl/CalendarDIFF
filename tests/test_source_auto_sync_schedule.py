from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db.models.input import (
    IngestTriggerType,
    InputSource,
    InputSourceConfig,
    InputSourceCursor,
    SourceKind,
    SyncRequest,
    SyncRequestStatus,
)
from app.db.models.runtime import ConnectorResultStatus, IngestResult
from app.db.models.shared import User
from app.modules.common.source_auto_sync_schedule import next_source_auto_sync_at
import app.modules.runtime.connectors.orchestrator as orchestrator
import app.modules.runtime.apply.apply as apply_module
from app.modules.runtime.apply.apply import apply_ingest_result_idempotent


def test_next_source_auto_sync_at_uses_morning_and_evening_slots() -> None:
    assert next_source_auto_sync_at(
        now=datetime(2026, 3, 20, 14, 30, tzinfo=timezone.utc),
        timezone_name="America/Los_Angeles",
    ) == datetime(2026, 3, 20, 15, 0, tzinfo=timezone.utc)

    assert next_source_auto_sync_at(
        now=datetime(2026, 3, 20, 19, 30, tzinfo=timezone.utc),
        timezone_name="America/Los_Angeles",
    ) == datetime(2026, 3, 21, 4, 0, tzinfo=timezone.utc)

    assert next_source_auto_sync_at(
        now=datetime(2026, 3, 21, 5, 30, tzinfo=timezone.utc),
        timezone_name="America/Los_Angeles",
    ) == datetime(2026, 3, 21, 15, 0, tzinfo=timezone.utc)


def test_run_orchestrator_tick_reschedules_next_auto_sync_to_fixed_slot(db_session, monkeypatch) -> None:
    fixed_now = datetime(2026, 3, 20, 19, 30, tzinfo=timezone.utc)

    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fixed_now.replace(tzinfo=None)
            return fixed_now.astimezone(tz)

    monkeypatch.setattr(orchestrator, "datetime", _FrozenDateTime)

    user = User(
        email="scheduler-owner@example.com",
        timezone_name="America/Los_Angeles",
        onboarding_completed_at=fixed_now,
    )
    db_session.add(user)
    db_session.flush()

    source = InputSource(
        user_id=user.id,
        source_kind=SourceKind.EMAIL,
        provider="gmail",
        source_key="gmail-fixed-schedule-source",
        display_name="Gmail Fixed Schedule Source",
        is_active=True,
        poll_interval_seconds=900,
        last_polled_at=fixed_now - timedelta(hours=10),
        next_poll_at=fixed_now - timedelta(minutes=1),
    )
    db_session.add(source)
    db_session.flush()
    db_session.add(InputSourceConfig(source_id=source.id, schema_version=1, config_json={"label_id": "INBOX"}))
    db_session.add(InputSourceCursor(source_id=source.id, version=1, cursor_json={}))
    db_session.commit()

    processed = orchestrator.run_orchestrator_tick(db_session, worker_id="test-scheduler")
    assert processed >= 1

    refreshed_source = db_session.get(InputSource, source.id)
    assert refreshed_source is not None
    assert refreshed_source.next_poll_at == datetime(2026, 3, 21, 4, 0, tzinfo=timezone.utc)

    request = db_session.scalar(
        select(SyncRequest)
        .where(SyncRequest.source_id == source.id)
        .order_by(SyncRequest.created_at.desc())
    )
    assert request is not None
    assert request.trigger_type == IngestTriggerType.SCHEDULER
    assert request.status in {SyncRequestStatus.PENDING, SyncRequestStatus.QUEUED}


def test_apply_ingest_result_reschedules_source_to_next_fixed_slot(db_session) -> None:
    applied_at = datetime(2026, 3, 20, 19, 30, tzinfo=timezone.utc)
    user = User(
        email="apply-owner@example.com",
        timezone_name="America/Los_Angeles",
        onboarding_completed_at=applied_at,
    )
    db_session.add(user)
    db_session.flush()

    source = InputSource(
        user_id=user.id,
        source_kind=SourceKind.EMAIL,
        provider="gmail",
        source_key="gmail-apply-fixed-schedule-source",
        display_name="Gmail Apply Fixed Schedule Source",
        is_active=True,
        poll_interval_seconds=900,
        next_poll_at=applied_at,
    )
    db_session.add(source)
    db_session.flush()
    db_session.add(InputSourceConfig(source_id=source.id, schema_version=1, config_json={"label_id": "INBOX"}))
    db_session.add(InputSourceCursor(source_id=source.id, version=1, cursor_json={"history_id": "100"}))
    db_session.add(
        SyncRequest(
            request_id="fixed-schedule-apply-req",
            source_id=source.id,
            trigger_type=IngestTriggerType.MANUAL,
            status=SyncRequestStatus.RUNNING,
            idempotency_key="idemp:fixed-schedule-apply-req",
            metadata_json={"kind": "test"},
        )
    )
    db_session.add(
        IngestResult(
            request_id="fixed-schedule-apply-req",
            source_id=source.id,
            provider=source.provider,
            status=ConnectorResultStatus.NO_CHANGE,
            cursor_patch={"history_id": "200"},
            records=[],
            fetched_at=applied_at,
            error_code=None,
            error_message=None,
        )
    )
    db_session.commit()

    class _FrozenApplyDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return applied_at.replace(tzinfo=None)
            return applied_at.astimezone(tz)

    original_datetime = apply_module.datetime
    apply_module.datetime = _FrozenApplyDateTime
    try:
        result = apply_ingest_result_idempotent(db_session, request_id="fixed-schedule-apply-req")
    finally:
        apply_module.datetime = original_datetime
    assert result["applied"] is True

    refreshed_source = db_session.get(InputSource, source.id)
    assert refreshed_source is not None
    assert refreshed_source.next_poll_at == datetime(2026, 3, 21, 4, 0, tzinfo=timezone.utc)
