from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db.models.ingestion import ConnectorResultStatus, IngestResult
from app.db.models.input import IngestTriggerType, InputSource, InputSourceConfig, InputSourceCursor, InputSourceSecret, SourceKind, SyncRequest, SyncRequestStatus
from app.db.models.review import Change, Input, InputType, ReviewStatus
from app.db.models.shared import User
from app.modules.core_ingest.apply_service import apply_ingest_result_idempotent
from tests.support.payload_builders import build_calendar_payload, build_course_parse, build_event_parts, build_gmail_payload, build_link_signals, build_work_item_parse


def _create_sources(db_session) -> tuple[User, InputSource, InputSource]:
    now = datetime.now(timezone.utc)
    user = User(email="wk@example.com", notify_email="wk@example.com", onboarding_completed_at=now)
    db_session.add(user)
    db_session.flush()

    calendar_source = InputSource(
        user_id=user.id,
        source_kind=SourceKind.CALENDAR,
        provider="ics",
        source_key="canvas_ics",
        display_name="Canvas ICS",
        is_active=True,
        poll_interval_seconds=900,
        next_poll_at=now,
    )
    gmail_source = InputSource(
        user_id=user.id,
        source_kind=SourceKind.EMAIL,
        provider="gmail",
        source_key="gmail-kind-source",
        display_name="Gmail Kind Source",
        is_active=True,
        poll_interval_seconds=900,
        next_poll_at=now,
    )
    db_session.add_all([calendar_source, gmail_source])
    db_session.flush()
    db_session.add(InputSourceConfig(source_id=calendar_source.id, schema_version=1, config_json={}))
    db_session.add(InputSourceSecret(source_id=calendar_source.id, encrypted_payload="x"))
    db_session.add(InputSourceCursor(source_id=calendar_source.id, version=1, cursor_json={}))
    db_session.add(InputSourceConfig(source_id=gmail_source.id, schema_version=1, config_json={}))
    db_session.add(InputSourceSecret(source_id=gmail_source.id, encrypted_payload="x"))
    db_session.add(InputSourceCursor(source_id=gmail_source.id, version=1, cursor_json={}))
    db_session.commit()
    db_session.refresh(user)
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


def test_homework_and_hw_merge_under_same_mapping(db_session) -> None:
    user, calendar_source, gmail_source = _create_sources(db_session)
    due = datetime(2026, 3, 10, 23, 59, tzinfo=timezone.utc)
    calendar_records = [{
        "record_type": "calendar.event.extracted",
        "payload": build_calendar_payload(
            external_event_id="cal-hw1",
            title="Homework 1 Due",
            start_at=due,
            end_at=due + timedelta(hours=1),
            course_parse=build_course_parse(dept="CSE", number=8, suffix="A", confidence=0.95, evidence="CSE8A"),
            work_item_parse=build_work_item_parse(raw_kind_label="Homework", ordinal=1, confidence=0.95, evidence="Homework 1"),
            event_parts=build_event_parts(type="deadline", index=1, confidence=0.95, evidence="Homework 1"),
            link_signals=build_link_signals(),
        ),
    }]
    gmail_records = [{
        "record_type": "gmail.message.extracted",
        "payload": build_gmail_payload(
            message_id="gmail-hw1",
            title="HW1 reminder",
            due_at=due,
            course_parse=build_course_parse(dept="CSE", number=8, suffix="A", confidence=0.92, evidence="CSE8A"),
            work_item_parse=build_work_item_parse(raw_kind_label="HW", ordinal=1, confidence=0.9, evidence="HW1"),
            event_parts=build_event_parts(type="deadline", index=1, confidence=0.9, evidence="HW1"),
            link_signals=build_link_signals(),
            time_anchor_confidence=0.9,
        ),
    }]
    _seed_result(db_session, source=calendar_source, request_id="kind-cal-1", records=calendar_records)
    apply_ingest_result_idempotent(db_session, request_id="kind-cal-1")
    _seed_result(db_session, source=gmail_source, request_id="kind-gmail-1", records=gmail_records)
    apply_ingest_result_idempotent(db_session, request_id="kind-gmail-1")

    canonical_input = db_session.scalar(select(Input).where(Input.user_id == user.id, Input.type == InputType.ICS, Input.identity_key == f"canonical:user:{user.id}"))
    assert canonical_input is not None
    pending = db_session.scalars(select(Change).where(Change.input_id == canonical_input.id, Change.review_status == ReviewStatus.PENDING)).all()
    assert len(pending) == 1
    proposal_sources = pending[0].proposal_sources_json or []
    assert {row["source_id"] for row in proposal_sources} == {calendar_source.id, gmail_source.id}


def test_hw_and_pa_do_not_merge_when_mappings_differ(db_session) -> None:
    user, calendar_source, gmail_source = _create_sources(db_session)
    due = datetime(2026, 3, 10, 23, 59, tzinfo=timezone.utc)
    calendar_records = [{
        "record_type": "calendar.event.extracted",
        "payload": build_calendar_payload(
            external_event_id="cal-hw1",
            title="Homework 1 Due",
            start_at=due,
            end_at=due + timedelta(hours=1),
            course_parse=build_course_parse(dept="CSE", number=8, suffix="A", confidence=0.95, evidence="CSE8A"),
            work_item_parse=build_work_item_parse(raw_kind_label="Homework", ordinal=1, confidence=0.95, evidence="Homework 1"),
            event_parts=build_event_parts(type="deadline", index=1, confidence=0.95, evidence="Homework 1"),
            link_signals=build_link_signals(),
        ),
    }]
    gmail_records = [{
        "record_type": "gmail.message.extracted",
        "payload": build_gmail_payload(
            message_id="gmail-pa1",
            title="PA1 reminder",
            due_at=due,
            course_parse=build_course_parse(dept="CSE", number=8, suffix="A", confidence=0.92, evidence="CSE8A"),
            work_item_parse=build_work_item_parse(raw_kind_label="PA", ordinal=1, confidence=0.9, evidence="PA1"),
            event_parts=build_event_parts(type="deadline", index=1, confidence=0.9, evidence="PA1"),
            link_signals=build_link_signals(),
            time_anchor_confidence=0.9,
        ),
    }]
    _seed_result(db_session, source=calendar_source, request_id="kind-cal-2", records=calendar_records)
    apply_ingest_result_idempotent(db_session, request_id="kind-cal-2")
    _seed_result(db_session, source=gmail_source, request_id="kind-gmail-2", records=gmail_records)
    apply_ingest_result_idempotent(db_session, request_id="kind-gmail-2")

    canonical_input = db_session.scalar(select(Input).where(Input.user_id == user.id, Input.type == InputType.ICS, Input.identity_key == f"canonical:user:{user.id}"))
    assert canonical_input is not None
    pending = db_session.scalars(select(Change).where(Change.input_id == canonical_input.id, Change.review_status == ReviewStatus.PENDING)).all()
    assert len(pending) == 2
