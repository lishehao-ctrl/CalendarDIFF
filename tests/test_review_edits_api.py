from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.db.models.input import InputSource, SourceKind
from app.db.models.review import Change, ChangeOrigin, ChangeType, EventEntity, EventEntityLifecycle, ReviewStatus
from app.db.models.shared import User


def _create_user(db_session) -> User:
    user = User(
        email="review-edit@example.com",
        notify_email="review-edit@example.com",
        timezone_name="America/Los_Angeles",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.flush()
    db_session.add(
        InputSource(
            user_id=user.id,
            source_kind=SourceKind.CALENDAR,
            provider="ics",
            source_key=f"edit-{user.id}",
            display_name="Edit Source",
            is_active=True,
            poll_interval_seconds=900,
        )
    )
    db_session.commit()
    db_session.refresh(user)
    return user


def _semantic_payload(*, uid: str, event_name: str, due_date: str, time_precision: str = "date_only") -> dict:
    payload = {
        "uid": uid,
        "course_dept": "CSE",
        "course_number": 8,
        "course_suffix": "A",
        "family_name": "Homework",
        "raw_type": "Homework",
        "event_name": event_name,
        "ordinal": 1,
        "due_date": due_date,
        "time_precision": time_precision,
    }
    if time_precision == "datetime":
        payload["due_time"] = "23:59:00"
    return payload


def test_review_edit_proposal_preview_and_apply_updates_pending_change(client, db_session, auth_headers) -> None:
    user = _create_user(db_session)
    change = Change(
        user_id=user.id,
        entity_uid="proposal-edit-1",
        change_origin=ChangeOrigin.INGEST_PROPOSAL,
        change_type=ChangeType.DUE_CHANGED,
        detected_at=datetime.now(timezone.utc),
        before_semantic_json=_semantic_payload(uid="proposal-edit-1", event_name="HW1", due_date="2026-03-08"),
        after_semantic_json=_semantic_payload(uid="proposal-edit-1", event_name="HW1", due_date="2026-03-08"),
        review_status=ReviewStatus.PENDING,
    )
    db_session.add(change)
    db_session.commit()

    headers = auth_headers(client, user=user)
    preview_response = client.post(
        "/review/edits/preview",
        headers=headers,
        json={
            "mode": "proposal",
            "target": {"change_id": change.id},
            "patch": {"due_date": "2026-03-09", "event_name": "HW1 Updated"},
        },
    )
    assert preview_response.status_code == 200
    preview_payload = preview_response.json()
    assert preview_payload["mode"] == "proposal"
    assert preview_payload["change_id"] == change.id
    assert preview_payload["candidate_after"]["event_display"]["display_label"] == "CSE 8A · Homework 1"
    assert preview_payload["candidate_after"]["due_date"] == "2026-03-09"

    apply_response = client.post(
        "/review/edits",
        headers=headers,
        json={
            "mode": "proposal",
            "target": {"change_id": change.id},
            "patch": {"due_date": "2026-03-09", "event_name": "HW1 Updated"},
        },
    )
    assert apply_response.status_code == 200

    db_session.expire_all()
    refreshed = db_session.get(Change, change.id)
    assert refreshed is not None
    assert refreshed.review_status == ReviewStatus.PENDING
    assert refreshed.after_semantic_json["event_name"] == "HW1 Updated"
    assert refreshed.after_evidence_json is not None


def test_review_edit_canonical_applies_directly_to_entity_state(client, db_session, auth_headers) -> None:
    user = _create_user(db_session)
    db_session.add(
        EventEntity(
            user_id=user.id,
            entity_uid="canonical-edit-1",
            lifecycle=EventEntityLifecycle.ACTIVE,
            course_dept="CSE",
            course_number=8,
            course_suffix="A",
            family_name="Homework",
            raw_type="Homework",
            event_name="HW2",
            ordinal=2,
            due_date=datetime(2026, 3, 10, tzinfo=timezone.utc).date(),
            time_precision="date_only",
        )
    )
    db_session.commit()

    headers = auth_headers(client, user=user)
    response = client.post(
        "/review/edits",
        headers=headers,
        json={
            "mode": "canonical",
            "target": {"entity_uid": "canonical-edit-1"},
            "patch": {"event_name": "HW2 Updated", "due_date": "2026-03-11"},
            "reason": "manual fix",
        },
    )
    assert response.status_code == 200

    db_session.expire_all()
    entity = db_session.scalar(select(EventEntity).where(EventEntity.user_id == user.id, EventEntity.entity_uid == "canonical-edit-1"))
    audit_change = db_session.scalar(
        select(Change).where(Change.user_id == user.id, Change.entity_uid == "canonical-edit-1", Change.change_origin == ChangeOrigin.MANUAL_CANONICAL_EDIT)
    )
    assert entity is not None
    assert entity.event_name == "HW2 Updated"
    assert entity.due_date.isoformat() == "2026-03-11"
    assert audit_change is not None
    assert audit_change.review_status == ReviewStatus.APPROVED
