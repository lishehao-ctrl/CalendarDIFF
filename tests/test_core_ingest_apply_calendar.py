from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.core.security import encrypt_secret
from app.db.models import (
    Change,
    ChangeType,
    ConnectorResultStatus,
    Event,
    IngestResult,
    IngestTriggerType,
    Input,
    InputSource,
    InputSourceConfig,
    InputSourceCursor,
    InputSourceSecret,
    InputType,
    ReviewStatus,
    SourceKind,
    SyncRequest,
    SyncRequestStatus,
    User,
)
from app.modules.core_ingest.service import apply_ingest_result_idempotent
from app.modules.review_changes.service import decide_review_change
from tests.support.payload_builders import (
    build_calendar_payload,
    build_course_parse,
    build_event_parts,
    build_link_signals,
)


def _create_calendar_source(db_session) -> InputSource:
    now = datetime.now(timezone.utc)
    user = User(
        email="calendar-owner@example.com",
        notify_email="calendar-owner@example.com",
        onboarding_completed_at=now,
    )
    db_session.add(user)
    db_session.flush()

    source = InputSource(
        user_id=user.id,
        source_kind=SourceKind.CALENDAR,
        provider="ics",
        source_key="calendar-review-source",
        display_name="Calendar Review Source",
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
            encrypted_payload=encrypt_secret(json.dumps({"url": "https://example.com/calendar.ics"})),
        )
    )
    db_session.add(InputSourceCursor(source_id=source.id, version=1, cursor_json={}))
    db_session.commit()
    db_session.refresh(source)
    return source


def _create_request_and_result(
    db_session,
    *,
    source: InputSource,
    request_id: str,
    records: list[dict],
    status: ConnectorResultStatus = ConnectorResultStatus.CHANGED,
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
            cursor_patch={},
            records=records,
            fetched_at=datetime.now(timezone.utc),
            error_code=None,
            error_message=None,
        )
    )
    db_session.commit()


def _calendar_record(*, uid: str, start_at: datetime, end_at: datetime) -> dict:
    return {
        "record_type": "calendar.event.extracted",
        "payload": build_calendar_payload(
            external_event_id=uid,
            title="Homework",
            start_at=start_at,
            end_at=end_at,
            course_parse=build_course_parse(
                dept="CSE",
                number=100,
                suffix=None,
                quarter="WI",
                year2=26,
                confidence=0.91,
                evidence="CSE 100 WI26",
            ),
            event_parts=build_event_parts(type="deadline", index=1, confidence=0.8, evidence="Homework"),
            link_signals=build_link_signals(),
        ),
    }


def _canonical_input_id(db_session, *, user_id: int) -> int:
    row = db_session.scalar(
        select(Input).where(
            Input.user_id == user_id,
            Input.type == InputType.ICS,
            Input.identity_key == f"canonical:user:{user_id}",
        )
    )
    assert row is not None
    return row.id


def test_apply_calendar_records_create_pending_proposal_then_approve(db_session) -> None:
    source = _create_calendar_source(db_session)
    t0 = datetime(2026, 3, 1, 20, 0, tzinfo=timezone.utc)
    uid = "evt-1"

    _create_request_and_result(
        db_session,
        source=source,
        request_id="calendar-req-1",
        records=[_calendar_record(uid=uid, start_at=t0, end_at=t0 + timedelta(hours=1))],
    )

    first_apply = apply_ingest_result_idempotent(db_session, request_id="calendar-req-1")
    assert first_apply["changes_created"] == 1
    assert first_apply["idempotent_replay"] is False
    assert (
        db_session.scalar(
            select(func.count(Input.id)).where(
                Input.user_id == source.user_id,
                Input.identity_key.like("source:%"),
            )
        )
        == 0
    )

    canonical_input_id = _canonical_input_id(db_session, user_id=source.user_id)
    pending = db_session.scalar(
        select(Change)
        .where(Change.input_id == canonical_input_id)
        .order_by(Change.id.desc())
        .limit(1)
    )
    assert pending is not None
    assert pending.review_status == ReviewStatus.PENDING
    assert pending.change_type == ChangeType.CREATED
    assert db_session.scalar(select(func.count(Event.id)).where(Event.input_id == canonical_input_id)) == 0

    decided, idempotent = decide_review_change(
        db_session,
        user_id=source.user_id,
        change_id=pending.id,
        decision="approve",
        note="apply from test",
    )
    assert idempotent is False
    assert decided.review_status == ReviewStatus.APPROVED
    assert db_session.scalar(select(func.count(Event.id)).where(Event.input_id == canonical_input_id)) == 1

    replay = apply_ingest_result_idempotent(db_session, request_id="calendar-req-1")
    assert replay["idempotent_replay"] is True


def test_apply_calendar_due_change_and_remove_go_through_pending_review(db_session) -> None:
    source = _create_calendar_source(db_session)
    t0 = datetime(2026, 3, 1, 20, 0, tzinfo=timezone.utc)
    uid = "evt-remove-1"

    _create_request_and_result(
        db_session,
        source=source,
        request_id="calendar-rv-1",
        records=[_calendar_record(uid=uid, start_at=t0, end_at=t0 + timedelta(hours=1))],
    )
    apply_ingest_result_idempotent(db_session, request_id="calendar-rv-1")

    canonical_input_id = _canonical_input_id(db_session, user_id=source.user_id)
    create_change = db_session.scalar(
        select(Change)
        .where(Change.input_id == canonical_input_id, Change.review_status == ReviewStatus.PENDING)
        .order_by(Change.id.desc())
        .limit(1)
    )
    assert create_change is not None
    decide_review_change(
        db_session,
        user_id=source.user_id,
        change_id=create_change.id,
        decision="approve",
        note="seed canonical event",
    )

    _create_request_and_result(
        db_session,
        source=source,
        request_id="calendar-rv-2",
        records=[
            _calendar_record(
                uid=uid,
                start_at=t0 + timedelta(hours=2),
                end_at=t0 + timedelta(hours=3),
            )
        ],
    )
    second_apply = apply_ingest_result_idempotent(db_session, request_id="calendar-rv-2")
    assert second_apply["changes_created"] == 1

    due_change = db_session.scalar(
        select(Change)
        .where(Change.input_id == canonical_input_id, Change.review_status == ReviewStatus.PENDING)
        .order_by(Change.id.desc())
        .limit(1)
    )
    assert due_change is not None
    assert due_change.change_type == ChangeType.DUE_CHANGED

    decide_review_change(
        db_session,
        user_id=source.user_id,
        change_id=due_change.id,
        decision="approve",
        note="approve due change",
    )

    _create_request_and_result(
        db_session,
        source=source,
        request_id="calendar-rv-3",
        records=[],
    )
    third_apply = apply_ingest_result_idempotent(db_session, request_id="calendar-rv-3")
    assert third_apply["changes_created"] == 1

    remove_change = db_session.scalar(
        select(Change)
        .where(Change.input_id == canonical_input_id, Change.review_status == ReviewStatus.PENDING)
        .order_by(Change.id.desc())
        .limit(1)
    )
    assert remove_change is not None
    assert remove_change.change_type == ChangeType.REMOVED

    decide_review_change(
        db_session,
        user_id=source.user_id,
        change_id=remove_change.id,
        decision="approve",
        note="approve removal",
    )
    assert db_session.scalar(select(func.count(Event.id)).where(Event.input_id == canonical_input_id)) == 0
