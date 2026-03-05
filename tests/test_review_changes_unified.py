from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from app.core.security import encrypt_secret
from app.db.models.ingestion import ConnectorResultStatus, IngestResult
from app.db.models.input import IngestTriggerType, InputSource, InputSourceConfig, InputSourceCursor, InputSourceSecret, SourceKind, SyncRequest, SyncRequestStatus
from app.db.models.shared import User
from app.modules.core_ingest.apply_service import apply_ingest_result_idempotent
from tests.support.payload_builders import (
    build_calendar_payload,
    build_course_parse,
    build_event_parts,
    build_gmail_payload,
    build_link_signals,
)


def _create_sources(db_session) -> tuple[User, InputSource, InputSource]:
    now = datetime.now(timezone.utc)
    user = User(
        email="merge-owner@example.com",
        notify_email="merge-owner@example.com",
        onboarding_completed_at=now,
    )
    db_session.add(user)
    db_session.flush()

    calendar_source = InputSource(
        user_id=user.id,
        source_kind=SourceKind.CALENDAR,
        provider="ics",
        source_key="merge-calendar-source",
        display_name="Merge Calendar Source",
        is_active=True,
        poll_interval_seconds=900,
        next_poll_at=now,
    )
    gmail_source = InputSource(
        user_id=user.id,
        source_kind=SourceKind.EMAIL,
        provider="gmail",
        source_key="merge-gmail-source",
        display_name="Merge Gmail Source",
        is_active=True,
        poll_interval_seconds=900,
        next_poll_at=now,
    )
    db_session.add(calendar_source)
    db_session.add(gmail_source)
    db_session.flush()

    db_session.add(InputSourceConfig(source_id=calendar_source.id, schema_version=1, config_json={}))
    db_session.add(
        InputSourceSecret(
            source_id=calendar_source.id,
            encrypted_payload=encrypt_secret(json.dumps({"url": "https://example.com/merge.ics"})),
        )
    )
    db_session.add(InputSourceCursor(source_id=calendar_source.id, version=1, cursor_json={}))

    db_session.add(InputSourceConfig(source_id=gmail_source.id, schema_version=1, config_json={"label_id": "INBOX"}))
    db_session.add(
        InputSourceSecret(
            source_id=gmail_source.id,
            encrypted_payload=encrypt_secret(
                json.dumps({"access_token": "token", "account_email": "merge@example.edu"})
            ),
        )
    )
    db_session.add(InputSourceCursor(source_id=gmail_source.id, version=1, cursor_json={"history_id": "111"}))

    db_session.commit()
    db_session.refresh(calendar_source)
    db_session.refresh(gmail_source)
    return user, calendar_source, gmail_source


def _seed_result(db_session, *, source: InputSource, request_id: str, records: list[dict]) -> None:
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
            records=records,
            fetched_at=datetime.now(timezone.utc),
            error_code=None,
            error_message=None,
        )
    )
    db_session.commit()


def test_cross_source_merge_produces_single_pending_review_item(client, db_session) -> None:
    user, calendar_source, gmail_source = _create_sources(db_session)
    due = datetime(2026, 3, 4, 7, 59, tzinfo=timezone.utc)

    calendar_records = [
        {
            "record_type": "calendar.event.extracted",
            "payload": build_calendar_payload(
                external_event_id="calendar-hw1",
                title="HW1 Due",
                start_at=due,
                end_at=due + timedelta(hours=1),
                course_parse=build_course_parse(
                    dept="CSE",
                    number=100,
                    confidence=0.92,
                    evidence="CSE 100",
                ),
                event_parts=build_event_parts(type="deadline", index=1, confidence=0.9, evidence="HW1"),
                link_signals=build_link_signals(),
            ),
        }
    ]
    gmail_records = [
        {
            "record_type": "gmail.message.extracted",
            "payload": build_gmail_payload(
                message_id="gmail-hw1",
                title="HW1 Due",
                due_at=due,
                time_anchor_confidence=0.87,
                course_parse=build_course_parse(
                    dept="CSE",
                    number=100,
                    confidence=0.87,
                    evidence="cSe_100",
                ),
                event_parts=build_event_parts(type="deadline", index=1, confidence=0.87, evidence="HW1"),
                link_signals=build_link_signals(),
            ),
        }
    ]

    _seed_result(db_session, source=calendar_source, request_id="merge-cal-1", records=calendar_records)
    first_apply = apply_ingest_result_idempotent(db_session, request_id="merge-cal-1")
    assert first_apply["changes_created"] == 1

    _seed_result(db_session, source=gmail_source, request_id="merge-gmail-1", records=gmail_records)
    second_apply = apply_ingest_result_idempotent(db_session, request_id="merge-gmail-1")
    assert second_apply["changes_created"] == 0

    headers = {"X-API-Key": "test-api-key"}
    review_response = client.get("/review/changes?review_status=pending", headers=headers)
    assert review_response.status_code == 200
    review_rows = review_response.json()
    assert len(review_rows) == 1

    proposal_sources = review_rows[0]["proposal_sources"]
    source_ids = {row["source_id"] for row in proposal_sources}
    assert source_ids == {calendar_source.id, gmail_source.id}

    change_id = review_rows[0]["id"]
    approve_response = client.post(
        f"/review/changes/{change_id}/decisions",
        headers=headers,
        json={"decision": "approve", "note": "merge approve"},
    )
    assert approve_response.status_code == 200
    assert approve_response.json()["review_status"] == "approved"
    assert approve_response.json()["idempotent"] is False

    approve_again = client.post(
        f"/review/changes/{change_id}/decisions",
        headers=headers,
        json={"decision": "approve", "note": "noop"},
    )
    assert approve_again.status_code == 200
    assert approve_again.json()["idempotent"] is True

    feed_response = client.get(
        f"/review/changes?review_status=approved&source_id={calendar_source.id}",
        headers=headers,
    )
    assert feed_response.status_code == 200
    assert len(feed_response.json()) == 1

    feed_response_gmail = client.get(
        f"/review/changes?review_status=approved&source_id={gmail_source.id}",
        headers=headers,
    )
    assert feed_response_gmail.status_code == 200
    assert len(feed_response_gmail.json()) == 1

    rejected_view = client.get("/review/changes?review_status=pending", headers=headers)
    assert rejected_view.status_code == 200
    assert rejected_view.json() == []

    removed_email_queue = client.get("/review-items/emails", headers=headers)
    assert removed_email_queue.status_code == 404

    removed_email_patch = client.patch(
        "/review-items/emails/removed-id",
        headers=headers,
        json={"route": "archive"},
    )
    assert removed_email_patch.status_code == 404

    removed_email_view = client.post(
        "/review-items/emails/removed-id/views",
        headers=headers,
    )
    assert removed_email_view.status_code == 404

    removed_timeline = client.get("/timeline-events", headers=headers)
    assert removed_timeline.status_code == 404


def test_cross_source_merge_across_dates_keeps_same_topic_uid(client, db_session) -> None:
    user, calendar_source, gmail_source = _create_sources(db_session)
    due_round1 = datetime(2026, 3, 10, 23, 59, tzinfo=timezone.utc)
    due_round2 = datetime(2026, 3, 12, 20, 30, tzinfo=timezone.utc)

    round1_calendar_records = [
        {
            "record_type": "calendar.event.extracted",
            "payload": build_calendar_payload(
                external_event_id="calendar-hw1",
                title="CSE8A HW1 Deadline",
                start_at=due_round1,
                end_at=due_round1 + timedelta(hours=1),
                course_parse=build_course_parse(
                    dept="CSE",
                    number=8,
                    suffix="A",
                    confidence=0.95,
                    evidence="CSE8A",
                ),
                event_parts=build_event_parts(type="deadline", index=1, confidence=0.95, evidence="HW1"),
                link_signals=build_link_signals(),
            ),
        }
    ]
    round1_gmail_records = [
        {
            "record_type": "gmail.message.extracted",
            "payload": build_gmail_payload(
                message_id="gmail-hw1-round1",
                title="CSE8A HW1 Deadline",
                due_at=due_round1,
                time_anchor_confidence=0.9,
                course_parse=build_course_parse(
                    dept="CSE",
                    number=8,
                    suffix="A",
                    confidence=0.9,
                    evidence="cSe_8A",
                ),
                event_parts=build_event_parts(type="deadline", index=1, confidence=0.9, evidence="HW1"),
                link_signals=build_link_signals(),
            ),
        }
    ]

    _seed_result(db_session, source=calendar_source, request_id="merge-round1-cal", records=round1_calendar_records)
    apply_ingest_result_idempotent(db_session, request_id="merge-round1-cal")
    _seed_result(db_session, source=gmail_source, request_id="merge-round1-gmail", records=round1_gmail_records)
    apply_ingest_result_idempotent(db_session, request_id="merge-round1-gmail")

    headers = {"X-API-Key": "test-api-key"}
    pending_round1 = client.get("/review/changes?review_status=pending", headers=headers)
    assert pending_round1.status_code == 200
    round1_rows = pending_round1.json()
    assert len(round1_rows) == 1
    round1_change = round1_rows[0]
    round1_uid = round1_change["event_uid"]
    assert isinstance(round1_uid, str) and round1_uid
    source_ids = {row["source_id"] for row in round1_change["proposal_sources"]}
    assert source_ids == {calendar_source.id, gmail_source.id}

    approve_round1 = client.post(
        f"/review/changes/{round1_change['id']}/decisions",
        headers=headers,
        json={"decision": "approve", "note": "approve round1"},
    )
    assert approve_round1.status_code == 200
    assert approve_round1.json()["review_status"] == "approved"

    round2_calendar_records = [
        {
            "record_type": "calendar.event.extracted",
            "payload": build_calendar_payload(
                external_event_id="calendar-hw1",
                title="[Update] CSE 8A HW1 deadline moved",
                start_at=due_round2,
                end_at=due_round2 + timedelta(hours=1),
                course_parse=build_course_parse(
                    dept="CSE",
                    number=8,
                    suffix="A",
                    confidence=0.93,
                    evidence="CSE-8A",
                ),
                event_parts=build_event_parts(type="deadline", index=1, confidence=0.93, evidence="HW1"),
                link_signals=build_link_signals(),
            ),
        }
    ]
    round2_gmail_records = [
        {
            "record_type": "gmail.message.extracted",
            "payload": build_gmail_payload(
                message_id="gmail-hw1-round2",
                title="Fwd: cSe_8A hw-1 DEADLINE reminder",
                due_at=due_round2,
                time_anchor_confidence=0.88,
                course_parse=build_course_parse(
                    dept="CSE",
                    number=8,
                    suffix="A",
                    confidence=0.88,
                    evidence="CSE 8A",
                ),
                event_parts=build_event_parts(type="deadline", index=1, confidence=0.88, evidence="HW1"),
                link_signals=build_link_signals(),
            ),
        }
    ]

    _seed_result(db_session, source=calendar_source, request_id="merge-round2-cal", records=round2_calendar_records)
    apply_ingest_result_idempotent(db_session, request_id="merge-round2-cal")
    _seed_result(db_session, source=gmail_source, request_id="merge-round2-gmail", records=round2_gmail_records)
    apply_ingest_result_idempotent(db_session, request_id="merge-round2-gmail")

    pending_round2 = client.get("/review/changes?review_status=pending", headers=headers)
    assert pending_round2.status_code == 200
    round2_rows = pending_round2.json()
    assert len(round2_rows) == 1
    round2_change = round2_rows[0]
    assert round2_change["event_uid"] == round1_uid
    assert round2_change["change_type"] == "due_changed"
    assert round2_change["before_json"]["start_at_utc"] != round2_change["after_json"]["start_at_utc"]
