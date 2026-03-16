from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select

from app.db.models.review import Change, ChangeOrigin, ChangeType, EventEntity, EventEntityLifecycle, ReviewStatus
from app.db.models.shared import CourseWorkItemLabelFamily, User
from app.modules.common.course_identity import normalize_label_token, normalized_course_identity_key


def _create_user(db_session) -> User:
    user = User(
        email="manual-events@example.com",
        notify_email="manual-events@example.com",
        password_hash="hash",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _create_family(
    db_session,
    *,
    user_id: int,
    dept: str = "CSE",
    number: int = 120,
    suffix: str | None = None,
    quarter: str | None = "WI",
    year2: int | None = 26,
    canonical_label: str = "Homework",
) -> CourseWorkItemLabelFamily:
    family = CourseWorkItemLabelFamily(
        user_id=user_id,
        course_dept=dept,
        course_number=number,
        course_suffix=suffix,
        course_quarter=quarter,
        course_year2=year2,
        normalized_course_identity=normalized_course_identity_key(
            course_dept=dept,
            course_number=number,
            course_suffix=suffix,
            course_quarter=quarter,
            course_year2=year2,
        ),
        canonical_label=canonical_label,
        normalized_canonical_label=normalize_label_token(canonical_label),
    )
    db_session.add(family)
    db_session.commit()
    db_session.refresh(family)
    return family


def test_manual_events_create_and_list(input_client, db_session, authenticate_client) -> None:
    user = _create_user(db_session)
    family = _create_family(db_session, user_id=user.id, canonical_label="Homework")
    authenticate_client(input_client, user=user)

    create_response = input_client.post(
        "/users/me/manual-events",
        headers={"X-API-Key": "test-api-key"},
        json={
            "family_id": family.id,
            "event_name": "HW 3",
            "raw_type": "hw",
            "ordinal": 3,
            "due_date": "2026-03-18",
            "time_precision": "date_only",
            "reason": "manual add",
        },
    )
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["applied"] is True
    assert created["idempotent"] is False
    assert created["lifecycle"] == "active"
    assert created["event"]["manual_support"] is True
    assert created["event"]["family_name"] == "Homework"
    assert created["event"]["course_display"] == "CSE 120 WI26"

    list_response = input_client.get("/users/me/manual-events", headers={"X-API-Key": "test-api-key"})
    assert list_response.status_code == 200
    rows = list_response.json()
    assert len(rows) == 1
    assert rows[0]["entity_uid"] == created["entity_uid"]
    assert rows[0]["event"]["event_display"]["display_label"] == "CSE 120 WI26 · Homework 3"

    entity = db_session.scalar(select(EventEntity).where(EventEntity.user_id == user.id, EventEntity.entity_uid == created["entity_uid"]))
    audit_change = db_session.scalar(
        select(Change).where(
            Change.user_id == user.id,
            Change.entity_uid == created["entity_uid"],
            Change.change_origin == ChangeOrigin.MANUAL_CANONICAL_EDIT,
            Change.change_type == ChangeType.CREATED,
        )
    )
    assert entity is not None
    assert entity.lifecycle == EventEntityLifecycle.ACTIVE
    assert entity.manual_support is True
    assert audit_change is not None
    assert audit_change.review_status == ReviewStatus.APPROVED


def test_manual_events_patch_updates_entity_and_sets_manual_support(input_client, db_session, authenticate_client) -> None:
    user = _create_user(db_session)
    family = _create_family(db_session, user_id=user.id, canonical_label="Homework")
    authenticate_client(input_client, user=user)
    entity = EventEntity(
        user_id=user.id,
        entity_uid="manual-edit-1",
        lifecycle=EventEntityLifecycle.ACTIVE,
        course_dept="CSE",
        course_number=120,
        course_quarter="WI",
        course_year2=26,
        family_id=family.id,
        manual_support=False,
        raw_type="Homework",
        event_name="HW 2",
        ordinal=2,
        due_date=date(2026, 3, 10),
        due_time=None,
        time_precision="date_only",
    )
    db_session.add(entity)
    db_session.commit()

    patch_response = input_client.patch(
        "/users/me/manual-events/manual-edit-1",
        headers={"X-API-Key": "test-api-key"},
        json={
            "family_id": family.id,
            "event_name": "HW 2 revised",
            "raw_type": "essay",
            "ordinal": 2,
            "due_date": "2026-03-12",
            "time_precision": "date_only",
            "reason": "manual fix",
        },
    )
    assert patch_response.status_code == 200
    payload = patch_response.json()
    assert payload["applied"] is True
    assert payload["idempotent"] is False
    assert payload["event"]["raw_type"] == "essay"
    assert payload["event"]["event_name"] == "HW 2 revised"

    db_session.expire_all()
    refreshed = db_session.scalar(select(EventEntity).where(EventEntity.user_id == user.id, EventEntity.entity_uid == "manual-edit-1"))
    audit_change = db_session.scalar(
        select(Change).where(
            Change.user_id == user.id,
            Change.entity_uid == "manual-edit-1",
            Change.change_origin == ChangeOrigin.MANUAL_CANONICAL_EDIT,
            Change.change_type == ChangeType.DUE_CHANGED,
        )
    )
    assert refreshed is not None
    assert refreshed.manual_support is True
    assert refreshed.event_name == "HW 2 revised"
    assert refreshed.due_date.isoformat() == "2026-03-12"
    assert audit_change is not None
    assert audit_change.review_status == ReviewStatus.APPROVED


def test_manual_events_delete_marks_removed_and_rejects_pending_changes(input_client, db_session, authenticate_client) -> None:
    user = _create_user(db_session)
    family = _create_family(db_session, user_id=user.id, canonical_label="Quiz")
    authenticate_client(input_client, user=user)
    entity = EventEntity(
        user_id=user.id,
        entity_uid="manual-delete-1",
        lifecycle=EventEntityLifecycle.ACTIVE,
        course_dept="CSE",
        course_number=142,
        course_quarter="WI",
        course_year2=26,
        family_id=family.id,
        manual_support=False,
        raw_type="Quiz",
        event_name="Quiz 1",
        ordinal=1,
        due_date=date(2026, 3, 14),
        due_time=None,
        time_precision="date_only",
    )
    db_session.add(entity)
    db_session.flush()
    db_session.add(
        Change(
            user_id=user.id,
            entity_uid=entity.entity_uid,
            change_origin=ChangeOrigin.INGEST_PROPOSAL,
            change_type=ChangeType.DUE_CHANGED,
            detected_at=datetime.now(timezone.utc),
            before_semantic_json=None,
            after_semantic_json={
                "uid": entity.entity_uid,
                "course_dept": "CSE",
                "course_number": 142,
                "course_quarter": "WI",
                "course_year2": 26,
                "family_id": family.id,
                "family_name": "Quiz",
                "raw_type": "Quiz",
                "event_name": "Quiz 1",
                "ordinal": 1,
                "due_date": "2026-03-15",
                "time_precision": "date_only",
            },
            review_status=ReviewStatus.PENDING,
        )
    )
    db_session.commit()

    delete_response = input_client.delete(
        "/users/me/manual-events/manual-delete-1?reason=cleanup",
        headers={"X-API-Key": "test-api-key"},
    )
    assert delete_response.status_code == 200
    payload = delete_response.json()
    assert payload["applied"] is True
    assert payload["idempotent"] is False
    assert payload["lifecycle"] == "removed"

    db_session.expire_all()
    refreshed = db_session.scalar(select(EventEntity).where(EventEntity.user_id == user.id, EventEntity.entity_uid == "manual-delete-1"))
    pending_change = db_session.scalar(
        select(Change).where(
            Change.user_id == user.id,
            Change.entity_uid == "manual-delete-1",
            Change.change_origin == ChangeOrigin.INGEST_PROPOSAL,
        )
    )
    delete_audit = db_session.scalar(
        select(Change).where(
            Change.user_id == user.id,
            Change.entity_uid == "manual-delete-1",
            Change.change_origin == ChangeOrigin.MANUAL_CANONICAL_EDIT,
            Change.change_type == ChangeType.REMOVED,
        )
    )
    assert refreshed is not None
    assert refreshed.lifecycle == EventEntityLifecycle.REMOVED
    assert refreshed.manual_support is True
    assert pending_change is not None
    assert pending_change.review_status == ReviewStatus.REJECTED
    assert delete_audit is not None
    assert delete_audit.review_status == ReviewStatus.APPROVED
