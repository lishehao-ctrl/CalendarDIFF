from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.db.models.input import InputSource, SourceKind
from app.db.models.review import Change, ChangeOrigin, ChangeType, EventEntity, EventEntityLifecycle, ReviewStatus
from app.db.models.shared import User


def _create_onboarded_user(db_session) -> User:
    user = User(
        email="batch@example.com",
        notify_email="batch@example.com",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.flush()
    db_session.add(
        InputSource(
            user_id=user.id,
            source_kind=SourceKind.CALENDAR,
            provider="ics",
            source_key=f"batch-{user.id}",
            display_name="Calendar",
            is_active=True,
            poll_interval_seconds=900,
        )
    )
    db_session.commit()
    db_session.refresh(user)
    return user


def _seed_pending_change(db_session, *, user_id: int, entity_uid: str, event_name: str, due_date: str) -> Change:
    row = Change(
        user_id=user_id,
        entity_uid=entity_uid,
        change_origin=ChangeOrigin.INGEST_PROPOSAL,
        change_type=ChangeType.CREATED,
        detected_at=datetime.now(timezone.utc),
        after_semantic_json={
            "uid": entity_uid,
            "course_dept": "CSE",
            "course_number": 100,
            "course_quarter": "WI",
            "course_year2": 26,
            "family_name": "Homework",
            "raw_type": "Homework",
            "event_name": event_name,
            "ordinal": 1,
            "due_date": due_date,
            "due_time": "23:59:00",
            "time_precision": "datetime",
        },
        review_status=ReviewStatus.PENDING,
    )
    db_session.add(row)
    db_session.flush()
    return row


def test_review_changes_batch_approve_updates_event_entities(client, db_session, auth_headers) -> None:
    user = _create_onboarded_user(db_session)
    change_one = _seed_pending_change(db_session, user_id=user.id, entity_uid="ent-1", event_name="Homework 1", due_date="2026-03-10")
    change_two = _seed_pending_change(db_session, user_id=user.id, entity_uid="ent-2", event_name="Homework 2", due_date="2026-03-12")
    db_session.commit()

    response = client.post(
        "/review/changes/batch/decisions",
        headers=auth_headers(client, user=user),
        json={"ids": [change_one.id, change_two.id], "decision": "approve", "note": "batch approve"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["decision"] == "approve"
    assert payload["succeeded"] == 2
    assert payload["failed"] == 0

    db_session.expire_all()
    changes = db_session.scalars(select(Change).where(Change.id.in_([change_one.id, change_two.id]))).all()
    assert all(row.review_status == ReviewStatus.APPROVED for row in changes)
    entities = db_session.scalars(select(EventEntity).where(EventEntity.user_id == user.id).order_by(EventEntity.entity_uid.asc())).all()
    assert [row.entity_uid for row in entities] == ["ent-1", "ent-2"]
    assert all(row.lifecycle == EventEntityLifecycle.ACTIVE for row in entities)


def test_review_changes_batch_reject_keeps_approved_state_untouched(client, db_session, auth_headers) -> None:
    user = _create_onboarded_user(db_session)
    db_session.add(
        EventEntity(
            user_id=user.id,
            entity_uid="ent-existing",
            lifecycle=EventEntityLifecycle.ACTIVE,
            course_dept="CSE",
            course_number=100,
            course_quarter="WI",
            course_year2=26,
            family_name="Homework",
            raw_type="Homework",
            event_name="Homework Existing",
            ordinal=1,
            due_date=datetime(2026, 3, 10, tzinfo=timezone.utc).date(),
            time_precision="date_only",
        )
    )
    pending = Change(
        user_id=user.id,
        entity_uid="ent-existing",
        change_origin=ChangeOrigin.INGEST_PROPOSAL,
        change_type=ChangeType.DUE_CHANGED,
        detected_at=datetime.now(timezone.utc),
        before_semantic_json={
            "uid": "ent-existing",
            "course_dept": "CSE",
            "course_number": 100,
            "family_name": "Homework",
            "event_name": "Homework Existing",
            "ordinal": 1,
            "due_date": "2026-03-10",
            "time_precision": "date_only",
        },
        after_semantic_json={
            "uid": "ent-existing",
            "course_dept": "CSE",
            "course_number": 100,
            "family_name": "Homework",
            "event_name": "Homework Existing",
            "ordinal": 1,
            "due_date": "2026-03-11",
            "time_precision": "date_only",
        },
        review_status=ReviewStatus.PENDING,
    )
    db_session.add(pending)
    db_session.commit()

    response = client.post(
        "/review/changes/batch/decisions",
        headers=auth_headers(client, user=user),
        json={"ids": [pending.id], "decision": "reject", "note": "batch reject"},
    )
    assert response.status_code == 200

    db_session.expire_all()
    entity = db_session.scalar(select(EventEntity).where(EventEntity.user_id == user.id, EventEntity.entity_uid == "ent-existing"))
    refreshed = db_session.get(Change, pending.id)
    assert entity is not None and entity.due_date.isoformat() == "2026-03-10"
    assert refreshed is not None and refreshed.review_status == ReviewStatus.REJECTED
