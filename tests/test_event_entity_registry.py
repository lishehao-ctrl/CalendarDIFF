from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select

from app.db.models.input import InputSource, SourceKind
from app.db.models.review import ChangeType, EventEntity, EventEntityLifecycle
from app.db.models.shared import User
from app.modules.core_ingest.calendar_apply import apply_calendar_observations
from app.modules.review_changes.approved_entity_state import apply_approved_entity_state
from tests.support.payload_builders import build_calendar_payload


def _create_user(db_session) -> User:
    user = User(email="entity-approved@example.com", notify_email="entity-approved@example.com")
    db_session.add(user)
    db_session.flush()
    return user


def test_apply_approved_entity_state_upserts_and_marks_removed(db_session) -> None:
    user = _create_user(db_session)
    entity_uid = "ent-approved-1"
    payload = {
        "uid": entity_uid,
        "course_dept": "CSE",
        "course_number": 101,
        "course_suffix": "A",
        "course_quarter": "SP",
        "course_year2": 26,
        "family_id": 12,
        "family_name": "Homework",
        "raw_type": "Homework",
        "event_name": "Homework 3",
        "ordinal": 3,
        "due_date": "2026-03-10",
        "due_time": "23:59:00",
        "time_precision": "datetime",
    }

    apply_approved_entity_state(
        db=db_session,
        user_id=user.id,
        entity_uid=entity_uid,
        change_type=ChangeType.CREATED,
        semantic_payload=payload,
    )
    db_session.flush()

    row = db_session.scalar(select(EventEntity).where(EventEntity.user_id == user.id, EventEntity.entity_uid == entity_uid))
    assert row is not None
    assert row.lifecycle == EventEntityLifecycle.ACTIVE
    assert row.course_dept == "CSE"
    assert row.course_number == 101
    assert row.family_id == 12
    assert row.event_name == "Homework 3"

    apply_approved_entity_state(
        db=db_session,
        user_id=user.id,
        entity_uid=entity_uid,
        change_type=ChangeType.REMOVED,
        semantic_payload=None,
    )
    db_session.flush()

    refreshed = db_session.scalar(select(EventEntity).where(EventEntity.user_id == user.id, EventEntity.entity_uid == entity_uid))
    assert refreshed is not None
    assert refreshed.lifecycle == EventEntityLifecycle.REMOVED


def test_ingest_calendar_observation_does_not_precreate_event_entity(db_session) -> None:
    user = _create_user(db_session)
    source = InputSource(
        user_id=user.id,
        source_kind=SourceKind.CALENDAR,
        provider="ics",
        source_key="https://example.com/feed.ics",
        display_name="Calendar",
        is_active=True,
        poll_interval_seconds=300,
    )
    db_session.add(source)
    db_session.flush()

    payload = build_calendar_payload(
        external_event_id="evt-1",
        title="CSE 101 Homework 1",
        start_at=datetime(2026, 3, 10, 8, 0, tzinfo=timezone.utc),
    )
    affected = apply_calendar_observations(
        db=db_session,
        source=source,
        records=[{"record_type": "calendar.event.extracted", "payload": payload}],
        applied_at=datetime(2026, 3, 10, 8, 0, tzinfo=timezone.utc),
        request_id="req-no-precreate",
    )

    assert affected
    entity_count = db_session.scalar(select(func.count(EventEntity.id)).where(EventEntity.user_id == user.id))
    assert int(entity_count or 0) == 0
