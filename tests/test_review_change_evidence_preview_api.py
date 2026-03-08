from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.security import encrypt_secret
from app.db.models.ingestion import ConnectorResultStatus, IngestResult
from app.db.models.input import IngestTriggerType, InputSource, InputSourceConfig, InputSourceCursor, InputSourceSecret, SourceKind, SyncRequest, SyncRequestStatus
from app.db.models.review import Change, ChangeType, Input, InputType, ReviewStatus, SourceEventObservation
from app.db.models.shared import User
from app.modules.core_ingest.apply_service import apply_ingest_result_idempotent
from app.modules.core_ingest.evidence_snapshots import materialize_change_snapshot
from tests.support.payload_builders import build_calendar_payload, build_course_parse, build_event_parts, build_gmail_payload, build_link_signals


def _create_calendar_source(db_session) -> tuple[User, InputSource]:
    now = datetime.now(timezone.utc)
    user = User(
        email="evidence-owner@example.com",
        notify_email="evidence-owner@example.com",
        onboarding_completed_at=now,
    )
    db_session.add(user)
    db_session.flush()

    source = InputSource(
        user_id=user.id,
        source_kind=SourceKind.CALENDAR,
        provider="ics",
        source_key="canvas_ics",
        display_name="Canvas ICS",
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
            encrypted_payload=encrypt_secret(json.dumps({"url": "https://example.com/evidence.ics"})),
        )
    )
    db_session.add(InputSourceCursor(source_id=source.id, version=1, cursor_json={}))
    db_session.commit()
    db_session.refresh(user)
    db_session.refresh(source)
    return user, source


def _create_gmail_source(db_session) -> tuple[User, InputSource]:
    now = datetime.now(timezone.utc)
    user = User(
        email="gmail-evidence-owner@example.com",
        notify_email="gmail-evidence-owner@example.com",
        onboarding_completed_at=now,
    )
    db_session.add(user)
    db_session.flush()

    source = InputSource(
        user_id=user.id,
        source_kind=SourceKind.EMAIL,
        provider="gmail",
        source_key="gmail-evidence-source",
        display_name="Gmail Inbox",
        is_active=True,
        poll_interval_seconds=900,
        next_poll_at=now,
    )
    db_session.add(source)
    db_session.flush()
    db_session.add(InputSourceConfig(source_id=source.id, schema_version=1, config_json={"label_id": "INBOX"}))
    db_session.add(
        InputSourceSecret(
            source_id=source.id,
            encrypted_payload=encrypt_secret(
                json.dumps({"access_token": "gmail-token", "account_email": "student@example.edu"})
            ),
        )
    )
    db_session.add(InputSourceCursor(source_id=source.id, version=1, cursor_json={"history_id": "100"}))
    db_session.commit()
    db_session.refresh(user)
    db_session.refresh(source)
    return user, source


def _component_b64(*, uid: str, title: str, start_at: datetime, end_at: datetime) -> str:
    def _fmt(value: datetime) -> str:
        return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    component_text = "\r\n".join(
        [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTART:{_fmt(start_at)}",
            f"DTEND:{_fmt(end_at)}",
            f"SUMMARY:{title}",
            "END:VEVENT",
        ]
    )
    return base64.b64encode(component_text.encode("utf-8")).decode("ascii")


def _seed_result(db_session, *, source: InputSource, request_id: str, payload: dict) -> None:
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
            records=[{"record_type": "calendar.event.extracted", "payload": payload}],
            fetched_at=datetime.now(timezone.utc),
            error_code=None,
            error_message=None,
        )
    )
    db_session.commit()


def test_review_change_after_preview_reads_saved_ics_evidence(client, db_session, auth_headers) -> None:
    user, source = _create_calendar_source(db_session)
    start_at = datetime(2026, 3, 10, 18, 0, tzinfo=timezone.utc)
    payload = build_calendar_payload(
        external_event_id="evt-preview-after",
        title="Quiz 1",
        start_at=start_at,
        end_at=start_at + timedelta(hours=1),
        course_parse=build_course_parse(dept="CSE", number=100, quarter="WI", year2=26, confidence=0.92, evidence="CSE 100 WI26"),
        event_parts=build_event_parts(type="quiz", index=1, confidence=0.91, evidence="Quiz 1"),
        link_signals=build_link_signals(),
    )
    payload["raw_ics_component_b64"] = _component_b64(
        uid="evt-preview-after",
        title="Quiz 1",
        start_at=start_at,
        end_at=start_at + timedelta(hours=1),
    )
    _seed_result(db_session, source=source, request_id="evidence-after-1", payload=payload)

    apply_ingest_result_idempotent(db_session, request_id="evidence-after-1")

    headers = auth_headers(client, user=user)
    changes_response = client.get("/review/changes?review_status=pending", headers=headers)
    assert changes_response.status_code == 200
    change_id = changes_response.json()[0]["id"]

    change_row = db_session.scalar(select(Change).where(Change.id == change_id))
    assert change_row is not None
    assert change_row.after_snapshot_id is not None

    preview_response = client.get(f"/review/changes/{change_id}/evidence/after/preview", headers=headers)
    assert preview_response.status_code == 200
    preview_payload = preview_response.json()
    assert preview_payload["preview_text"] is not None
    assert preview_payload["event_count"] == 1
    assert preview_payload["events"][0]["summary"] == "Quiz 1"
    assert preview_payload["events"][0]["uid"] == "evt-preview-after"
    assert "BEGIN:VCALENDAR" in preview_payload["preview_text"]
    assert "SUMMARY:Quiz 1" in preview_payload["preview_text"]
    assert "DTSTART:20260310T180000Z" in preview_payload["preview_text"]


def test_review_change_due_changed_preview_compares_before_and_after_ics(client, db_session, auth_headers) -> None:
    user, source = _create_calendar_source(db_session)
    start_before = datetime(2026, 3, 12, 20, 0, tzinfo=timezone.utc)
    start_after = datetime(2026, 3, 13, 1, 30, tzinfo=timezone.utc)

    first_payload = build_calendar_payload(
        external_event_id="evt-preview-due-changed",
        title="Homework 3",
        start_at=start_before,
        end_at=start_before + timedelta(hours=1),
        course_parse=build_course_parse(dept="CSE", number=120, quarter="WI", year2=26, confidence=0.93, evidence="CSE 120 WI26"),
        event_parts=build_event_parts(type="deadline", index=3, confidence=0.9, evidence="Homework 3"),
        link_signals=build_link_signals(),
    )
    first_payload["raw_ics_component_b64"] = _component_b64(
        uid="evt-preview-due-changed",
        title="Homework 3",
        start_at=start_before,
        end_at=start_before + timedelta(hours=1),
    )
    _seed_result(db_session, source=source, request_id="evidence-before-1", payload=first_payload)
    apply_ingest_result_idempotent(db_session, request_id="evidence-before-1")

    headers = auth_headers(client, user=user)
    initial_changes = client.get("/review/changes?review_status=pending", headers=headers)
    assert initial_changes.status_code == 200
    initial_change_id = initial_changes.json()[0]["id"]
    approve_response = client.post(
        f"/review/changes/{initial_change_id}/decisions",
        headers=headers,
        json={"decision": "approve", "note": "approve initial evidence"},
    )
    assert approve_response.status_code == 200

    second_payload = build_calendar_payload(
        external_event_id="evt-preview-due-changed",
        title="Homework 3",
        start_at=start_after,
        end_at=start_after + timedelta(hours=1),
        course_parse=build_course_parse(dept="CSE", number=120, quarter="WI", year2=26, confidence=0.93, evidence="CSE 120 WI26"),
        event_parts=build_event_parts(type="deadline", index=3, confidence=0.9, evidence="Homework 3"),
        link_signals=build_link_signals(),
    )
    second_payload["raw_ics_component_b64"] = _component_b64(
        uid="evt-preview-due-changed",
        title="Homework 3",
        start_at=start_after,
        end_at=start_after + timedelta(hours=1),
    )
    _seed_result(db_session, source=source, request_id="evidence-before-2", payload=second_payload)
    apply_ingest_result_idempotent(db_session, request_id="evidence-before-2")

    changes_response = client.get("/review/changes?review_status=pending", headers=headers)
    assert changes_response.status_code == 200
    payload = changes_response.json()[0]
    assert payload["change_type"] == "due_changed"
    change_id = payload["id"]

    change_row = db_session.scalar(select(Change).where(Change.id == change_id, Change.review_status == ReviewStatus.PENDING))
    assert change_row is not None
    assert change_row.before_snapshot_id is not None
    assert change_row.after_snapshot_id is not None

    before_preview = client.get(f"/review/changes/{change_id}/evidence/before/preview", headers=headers)
    after_preview = client.get(f"/review/changes/{change_id}/evidence/after/preview", headers=headers)
    assert before_preview.status_code == 200
    assert after_preview.status_code == 200
    assert "DTSTART:20260312T200000Z" in before_preview.json()["preview_text"]
    assert "DTSTART:20260313T013000Z" in after_preview.json()["preview_text"]


def test_review_change_after_preview_builds_gmail_structured_summary(client, db_session, auth_headers) -> None:
    user, source = _create_gmail_source(db_session)
    due_at = datetime(2026, 3, 18, 20, 0, tzinfo=timezone.utc)
    canonical_input = Input(
        user_id=user.id,
        type=InputType.ICS,
        identity_key=f"canonical:user:{user.id}",
        is_active=True,
    )
    db_session.add(canonical_input)
    db_session.flush()

    after_json = {
        "uid": "merge:gmail-preview-1",
        "title": "Homework 2 due",
        "course_label": "CSE 100 WI26",
        "start_at_utc": due_at.isoformat(),
        "end_at_utc": (due_at + timedelta(hours=1)).isoformat(),
    }
    observation_payload = build_gmail_payload(
        message_id="gmail-preview-1",
        title="Homework 2 due",
        due_at=due_at,
        from_header="Professor Example <prof@example.edu>",
        thread_id="thread-123",
        internal_date="2026-03-08T14:00:00+00:00",
        time_anchor_confidence=0.91,
        course_parse=build_course_parse(dept="CSE", number=100, quarter="WI", year2=26, confidence=0.91, evidence="CSE 100 WI26"),
        event_parts=build_event_parts(type="deadline", index=2, confidence=0.9, evidence="Homework 2"),
        link_signals=build_link_signals(),
    )
    db_session.add(
        SourceEventObservation(
            user_id=user.id,
            source_id=source.id,
            source_kind=source.source_kind,
            provider=source.provider,
            external_event_id="gmail-preview-1",
            merge_key="merge:gmail-preview-1",
            event_payload=observation_payload,
            event_hash="0" * 64,
            observed_at=datetime.now(timezone.utc),
            is_active=True,
            last_request_id="gmail-preview-request",
        )
    )
    after_snapshot_id = materialize_change_snapshot(
        db=db_session,
        input_id=canonical_input.id,
        event_payload=observation_payload,
        fallback_json=after_json,
        retrieved_at=datetime.now(timezone.utc),
    )
    change = Change(
        input_id=canonical_input.id,
        event_uid="merge:gmail-preview-1",
        change_type=ChangeType.CREATED,
        detected_at=datetime.now(timezone.utc),
        before_json=None,
        after_json=after_json,
        delta_seconds=None,
        review_status=ReviewStatus.PENDING,
        proposal_merge_key="merge:gmail-preview-1",
        proposal_sources_json=[
            {
                "source_id": source.id,
                "source_kind": "email",
                "provider": "gmail",
                "external_event_id": "gmail-preview-1",
                "confidence": 0.91,
            }
        ],
        before_snapshot_id=None,
        after_snapshot_id=after_snapshot_id,
        evidence_keys=None,
    )
    db_session.add(change)
    db_session.commit()

    headers = auth_headers(client, user=user)
    preview_response = client.get(f"/review/changes/{change.id}/evidence/after/preview", headers=headers)
    assert preview_response.status_code == 200
    payload = preview_response.json()
    assert payload["provider"] == "gmail"
    assert payload["structured_kind"] == "gmail_event"
    assert payload["event_count"] == 1
    assert len(payload["structured_items"]) == 1
    item = payload["structured_items"][0]
    assert item["title"] == "Homework 2 due"
    assert item["course_label"] == "CSE 100 WI26"
    assert item["sender"] == "Professor Example <prof@example.edu>"
    assert item["thread_id"] == "thread-123"
    assert item["internal_date"] == "2026-03-08T14:00:00+00:00"
    assert item["snippet"] == "Homework 2 due"
    assert "BEGIN:VCALENDAR" in payload["preview_text"]
