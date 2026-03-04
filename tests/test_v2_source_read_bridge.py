from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from app.core.security import encrypt_secret
from app.db.models import (
    ConnectorResultStatus,
    IngestResult,
    IngestTriggerType,
    InputSource,
    InputSourceConfig,
    InputSourceCursor,
    InputSourceSecret,
    SourceKind,
    SyncRequest,
    SyncRequestStatus,
    User,
)
from app.modules.core_ingest.service import apply_ingest_result_idempotent
from tests.support.payload_builders import (
    build_calendar_payload,
    build_course_parse,
    build_event_parts,
    build_link_signals,
)


def _create_calendar_source(db_session) -> InputSource:
    now = datetime.now(timezone.utc)
    user = User(
        email="bridge-owner@example.com",
        notify_email="bridge-owner@example.com",
        onboarding_completed_at=now,
    )
    db_session.add(user)
    db_session.flush()

    source = InputSource(
        user_id=user.id,
        source_kind=SourceKind.CALENDAR,
        provider="ics",
        source_key="bridge-calendar-source",
        display_name="Bridge Calendar Source",
        is_active=True,
        poll_interval_seconds=900,
        last_polled_at=None,
        next_poll_at=now,
    )
    db_session.add(source)
    db_session.flush()

    db_session.add(InputSourceConfig(source_id=source.id, schema_version=1, config_json={}))
    db_session.add(
        InputSourceSecret(
            source_id=source.id,
            encrypted_payload=encrypt_secret(json.dumps({"url": "https://example.com/bridge.ics"})),
        )
    )
    db_session.add(InputSourceCursor(source_id=source.id, version=1, cursor_json={}))
    db_session.commit()
    db_session.refresh(source)
    return source


def _seed_calendar_ingest_result(db_session, *, source: InputSource, request_id: str) -> None:
    start = datetime(2026, 3, 2, 10, 0, tzinfo=timezone.utc)
    record = {
        "record_type": "calendar.event.extracted",
        "payload": build_calendar_payload(
            external_event_id="bridge-evt-1",
            title="Bridge Homework",
            start_at=start,
            end_at=start + timedelta(hours=1),
            course_parse=build_course_parse(
                dept="CSE",
                number=120,
                quarter="WI",
                year2=26,
                confidence=0.88,
                evidence="CSE 120",
            ),
            event_parts=build_event_parts(type="deadline", index=1, confidence=0.8, evidence="Bridge Homework"),
            link_signals=build_link_signals(),
        ),
    }
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
            status=ConnectorResultStatus.CHANGED,
            cursor_patch={},
            records=[record],
            fetched_at=datetime.now(timezone.utc),
            error_code=None,
            error_message=None,
        )
    )
    db_session.commit()


def test_v2_feed_and_timeline_read_source_id_via_review_pool(client, db_session) -> None:
    source = _create_calendar_source(db_session)
    _seed_calendar_ingest_result(db_session, source=source, request_id="bridge-read-req-1")
    apply_ingest_result_idempotent(db_session, request_id="bridge-read-req-1")

    headers = {"X-API-Key": "test-api-key"}

    pending_response = client.get("/v2/review-items/changes?review_status=pending", headers=headers)
    assert pending_response.status_code == 200
    pending_rows = pending_response.json()
    assert len(pending_rows) == 1
    assert pending_rows[0]["source_id"] == source.id
    change_id = pending_rows[0]["id"]

    decision_response = client.post(
        f"/v2/review-items/changes/{change_id}/decisions",
        headers=headers,
        json={"decision": "approve", "note": "bridge-approve"},
    )
    assert decision_response.status_code == 200
    assert decision_response.json()["review_status"] == "approved"

    feed_response = client.get(
        f"/v2/review-items/changes?review_status=approved&source_id={source.id}",
        headers=headers,
    )
    assert feed_response.status_code == 200
    feed_rows = feed_response.json()
    assert len(feed_rows) == 1
    assert feed_rows[0]["source_id"] == source.id

    timeline_response = client.get(f"/v2/timeline-events?source_id={source.id}", headers=headers)
    assert timeline_response.status_code == 200
    timeline_rows = timeline_response.json()
    assert len(timeline_rows) == 1
    assert timeline_rows[0]["source_id"] == source.id
