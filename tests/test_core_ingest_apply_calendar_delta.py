from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import encrypt_secret
from app.db.models.ingestion import ConnectorResultStatus, IngestResult
from app.db.models.input import IngestTriggerType, InputSource, InputSourceConfig, InputSourceCursor, InputSourceSecret, SourceKind, SyncRequest, SyncRequestStatus
from app.db.models.review import SourceEventObservation
from app.db.models.shared import User
from app.modules.core_ingest.apply import apply_ingest_result_idempotent
from tests.support.payload_builders import (
    build_calendar_payload,
    build_course_parse,
    build_event_parts,
    build_link_signals,
)


def _create_calendar_source(db_session: Session) -> InputSource:
    now = datetime.now(timezone.utc)
    user = User(
        email="calendar-delta-owner@example.com",
        notify_email="calendar-delta-owner@example.com",
        onboarding_completed_at=now,
    )
    db_session.add(user)
    db_session.flush()

    source = InputSource(
        user_id=user.id,
        source_kind=SourceKind.CALENDAR,
        provider="ics",
        source_key="calendar-delta-source",
        display_name="Calendar Delta Source",
        is_active=True,
        poll_interval_seconds=900,
        next_poll_at=now,
    )
    db_session.add(source)
    db_session.flush()

    db_session.add(InputSourceConfig(source_id=source.id, schema_version=1, config_json={}))
    db_session.add(
        InputSourceSecret(
            source_id=source.id,
            encrypted_payload=encrypt_secret(json.dumps({"url": "https://example.com/calendar-delta.ics"})),
        )
    )
    db_session.add(InputSourceCursor(source_id=source.id, version=1, cursor_json={}))
    db_session.commit()
    db_session.refresh(source)
    return source


def _create_request_and_result(
    db_session: Session,
    *,
    source: InputSource,
    request_id: str,
    records: list[dict],
    status: ConnectorResultStatus = ConnectorResultStatus.CHANGED,
    cursor_patch: dict | None = None,
) -> None:
    db_session.add(
        SyncRequest(
            request_id=request_id,
            source_id=source.id,
            trigger_type=IngestTriggerType.MANUAL,
            status=SyncRequestStatus.RUNNING,
            idempotency_key=f"idemp:{request_id}",
            metadata_json={"kind": "test"},
        )
    )
    db_session.add(
        IngestResult(
            request_id=request_id,
            source_id=source.id,
            provider=source.provider,
            status=status,
            cursor_patch=cursor_patch or {},
            records=records,
            fetched_at=datetime.now(timezone.utc),
            error_code=None,
            error_message=None,
        )
    )
    db_session.commit()


def _calendar_record(
    *,
    uid: str,
    title: str,
    start_at: datetime,
    end_at: datetime,
    component_key: str | None = None,
) -> dict:
    payload = build_calendar_payload(
        external_event_id=uid,
        title=title,
        start_at=start_at,
        end_at=end_at,
        course_parse=build_course_parse(
            dept="CSE",
            number=100,
            quarter="WI",
            year2=26,
            confidence=0.91,
            evidence="CSE 100",
        ),
        event_parts=build_event_parts(type="deadline", index=1, confidence=0.8, evidence=title),
        link_signals=build_link_signals(),
    )
    if component_key is not None:
        payload["component_key"] = component_key
    return {
        "record_type": "calendar.event.extracted",
        "payload": payload,
    }


def test_calendar_delta_mode_skips_full_snapshot_deactivate(db_session: Session) -> None:
    source = _create_calendar_source(db_session)
    t0 = datetime(2026, 3, 1, 20, 0, tzinfo=timezone.utc)
    _create_request_and_result(
        db_session,
        source=source,
        request_id="calendar-delta-1",
        records=[
            _calendar_record(uid="evt-1", title="HW1", start_at=t0, end_at=t0 + timedelta(hours=1)),
            _calendar_record(uid="evt-2", title="HW2", start_at=t0 + timedelta(days=1), end_at=t0 + timedelta(days=1, hours=1)),
        ],
    )
    apply_ingest_result_idempotent(db_session, request_id="calendar-delta-1")

    _create_request_and_result(
        db_session,
        source=source,
        request_id="calendar-delta-2",
        records=[
            _calendar_record(
                uid="evt-1",
                title="HW1",
                start_at=t0 + timedelta(hours=2),
                end_at=t0 + timedelta(hours=3),
                component_key="evt-1#",
            )
        ],
    )
    apply_ingest_result_idempotent(db_session, request_id="calendar-delta-2")

    evt1 = db_session.scalar(
        select(SourceEventObservation).where(
            SourceEventObservation.source_id == source.id,
            SourceEventObservation.external_event_id == "evt-1",
        )
    )
    evt2 = db_session.scalar(
        select(SourceEventObservation).where(
            SourceEventObservation.source_id == source.id,
            SourceEventObservation.external_event_id == "evt-2",
        )
    )
    assert evt1 is not None and evt1.is_active is True
    assert evt2 is not None and evt2.is_active is True


def test_calendar_removed_record_deactivates_target_observation(db_session: Session) -> None:
    source = _create_calendar_source(db_session)
    t0 = datetime(2026, 3, 1, 20, 0, tzinfo=timezone.utc)
    _create_request_and_result(
        db_session,
        source=source,
        request_id="calendar-delta-remove-1",
        records=[_calendar_record(uid="evt-remove", title="Homework 1", start_at=t0, end_at=t0 + timedelta(hours=1))],
    )
    apply_ingest_result_idempotent(db_session, request_id="calendar-delta-remove-1")

    _create_request_and_result(
        db_session,
        source=source,
        request_id="calendar-delta-remove-2",
        records=[
            {
                "record_type": "calendar.event.removed",
                "payload": {
                    "component_key": "evt-remove#",
                    "external_event_id": "evt-remove",
                },
            }
        ],
    )
    apply_ingest_result_idempotent(db_session, request_id="calendar-delta-remove-2")

    row = db_session.scalar(
        select(SourceEventObservation).where(
            SourceEventObservation.source_id == source.id,
            SourceEventObservation.external_event_id == "evt-remove",
        )
    )
    assert row is not None
    assert row.is_active is False


def test_calendar_zero_duration_event_is_normalized_and_cursor_advances_on_apply(db_session: Session) -> None:
    source = _create_calendar_source(db_session)
    t0 = datetime(2026, 2, 18, 6, 0, tzinfo=timezone.utc)
    _create_request_and_result(
        db_session,
        source=source,
        request_id="calendar-zero-duration-1",
        cursor_patch={"etag": "etag-zero-duration"},
        records=[_calendar_record(uid="evt-zero", title="Canvas HW", start_at=t0, end_at=t0)],
    )

    result = apply_ingest_result_idempotent(db_session, request_id="calendar-zero-duration-1")
    assert result["applied"] is True

    observation = db_session.scalar(
        select(SourceEventObservation).where(
            SourceEventObservation.source_id == source.id,
            SourceEventObservation.external_event_id == "evt-zero",
        )
    )
    assert observation is not None
    payload = observation.event_payload if isinstance(observation.event_payload, dict) else {}
    source_facts = payload.get("source_facts") if isinstance(payload.get("source_facts"), dict) else {}
    assert str(source_facts.get("source_dtstart_utc") or "").startswith("2026-02-18T06:00:00")
    assert str(source_facts.get("source_dtend_utc") or "").startswith("2026-02-18T06:00:00")

    refreshed_source = db_session.get(InputSource, source.id)
    assert refreshed_source is not None
    assert refreshed_source.cursor is not None
    assert refreshed_source.cursor.cursor_json.get("etag") == "etag-zero-duration"
