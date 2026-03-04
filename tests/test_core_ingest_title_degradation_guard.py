from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import encrypt_secret
from app.db.models import (
    Change,
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
    SourceEventObservation,
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


def _create_calendar_source(db_session: Session) -> InputSource:
    now = datetime.now(timezone.utc)
    user = User(
        email="title-guard-owner@example.com",
        notify_email="title-guard-owner@example.com",
        onboarding_completed_at=now,
    )
    db_session.add(user)
    db_session.flush()

    source = InputSource(
        user_id=user.id,
        source_kind=SourceKind.CALENDAR,
        provider="ics",
        source_key="title-guard-calendar",
        display_name="Title Guard Calendar",
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
            encrypted_payload=encrypt_secret(json.dumps({"url": "https://example.com/title-guard.ics"})),
        )
    )
    db_session.add(InputSourceCursor(source_id=source.id, version=1, cursor_json={}))
    db_session.commit()
    db_session.refresh(source)
    return source


def _seed_request_result(db_session: Session, *, source: InputSource, request_id: str, records: list[dict]) -> None:
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


def _canonical_input_id(db_session: Session, *, user_id: int) -> int:
    row = db_session.scalar(
        select(Input).where(
            Input.user_id == user_id,
            Input.type == InputType.ICS,
            Input.identity_key == f"canonical:user:{user_id}",
        )
    )
    assert row is not None
    return row.id


def test_title_degradation_does_not_create_pending(db_session: Session) -> None:
    source = _create_calendar_source(db_session)
    start_at = datetime(2026, 3, 10, 20, 0, tzinfo=timezone.utc)
    end_at = start_at + timedelta(hours=1)

    _seed_request_result(
        db_session,
        source=source,
        request_id="title-guard-round-1",
        records=[
            {
                "record_type": "calendar.event.extracted",
                "payload": build_calendar_payload(
                    external_event_id="cse151a-exam1",
                    title="CSE 151A exam 1",
                    start_at=start_at,
                    end_at=end_at,
                    course_parse=build_course_parse(
                        dept="CSE",
                        number=151,
                        suffix="A",
                        quarter=None,
                        year2=None,
                        confidence=0.92,
                        evidence="CSE 151A",
                    ),
                    event_parts=build_event_parts(
                        type="exam",
                        index=1,
                        confidence=0.92,
                        evidence="exam 1",
                    ),
                    link_signals=build_link_signals(keywords=["exam"], exam_sequence=1),
                ),
            }
        ],
    )
    first_apply = apply_ingest_result_idempotent(db_session, request_id="title-guard-round-1")
    assert first_apply["changes_created"] == 1

    canonical_input_id = _canonical_input_id(db_session, user_id=source.user_id)
    pending = db_session.scalar(
        select(Change)
        .where(Change.input_id == canonical_input_id, Change.review_status == ReviewStatus.PENDING)
        .order_by(Change.id.desc())
        .limit(1)
    )
    assert pending is not None
    decide_review_change(
        db_session,
        user_id=source.user_id,
        change_id=pending.id,
        decision="approve",
        note="seed canonical",
    )

    _seed_request_result(
        db_session,
        source=source,
        request_id="title-guard-round-2",
        records=[
            {
                "record_type": "calendar.event.extracted",
                "payload": build_calendar_payload(
                    external_event_id="cse151a-exam1",
                    title="CSE 151 Exam",
                    start_at=start_at,
                    end_at=end_at,
                    course_parse=build_course_parse(
                        dept="CSE",
                        number=151,
                        suffix=None,
                        quarter=None,
                        year2=None,
                        confidence=0.7,
                        evidence="CSE 151",
                    ),
                    event_parts=build_event_parts(
                        type="exam",
                        index=1,
                        confidence=0.7,
                        evidence="exam 1",
                    ),
                    link_signals=build_link_signals(keywords=["exam"], exam_sequence=1),
                ),
            }
        ],
    )
    second_apply = apply_ingest_result_idempotent(db_session, request_id="title-guard-round-2")
    assert second_apply["changes_created"] == 0

    event_uid = pending.event_uid
    event_row = db_session.scalar(select(Event).where(Event.input_id == canonical_input_id, Event.uid == event_uid))
    assert event_row is not None
    assert event_row.title == "CSE 151A exam 1"

    observation = db_session.scalar(
        select(SourceEventObservation).where(
            SourceEventObservation.source_id == source.id,
            SourceEventObservation.external_event_id == "cse151a-exam1",
        )
    )
    assert observation is not None
    payload = observation.event_payload if isinstance(observation.event_payload, dict) else {}
    source_canonical = payload.get("source_canonical") if isinstance(payload.get("source_canonical"), dict) else {}
    assert source_canonical.get("source_title") == "CSE 151A exam 1"
    enrichment = payload.get("enrichment") if isinstance(payload.get("enrichment"), dict) else {}
    aliases = enrichment.get("title_aliases") if isinstance(enrichment.get("title_aliases"), list) else []
    assert "CSE 151 Exam" in aliases
