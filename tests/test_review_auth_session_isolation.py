from __future__ import annotations

from datetime import datetime, timezone

from app.db.models.input import InputSource, SourceKind
from app.db.models.review import Change, ChangeOrigin, ChangeType, ReviewStatus
from app.db.models.shared import User


def test_review_summary_is_scoped_to_authenticated_user(client, db_session, authenticate_client) -> None:
    user_a = User(email="a@example.com", password_hash="hash", onboarding_completed_at=datetime.now(timezone.utc))
    user_b = User(email="b@example.com", password_hash="hash", onboarding_completed_at=datetime.now(timezone.utc))
    db_session.add_all([user_a, user_b])
    db_session.flush()

    source_a = InputSource(
        user_id=user_a.id,
        source_kind=SourceKind.EMAIL,
        provider="gmail",
        source_key="gmail-a",
        display_name="Gmail A",
        is_active=True,
        poll_interval_seconds=900,
    )
    source_b = InputSource(
        user_id=user_b.id,
        source_kind=SourceKind.EMAIL,
        provider="gmail",
        source_key="gmail-b",
        display_name="Gmail B",
        is_active=True,
        poll_interval_seconds=900,
    )
    db_session.add_all([source_a, source_b])
    db_session.flush()

    db_session.add(
        Change(
            user_id=user_a.id,
            entity_uid="entity-a",
            change_origin=ChangeOrigin.INGEST_PROPOSAL,
            change_type=ChangeType.CREATED,
            detected_at=datetime.now(timezone.utc),
            after_semantic_json={
                "uid": "entity-a",
                "course_dept": "CSE",
                "course_number": 100,
                "family_name": "Homework",
                "event_name": "Homework 1",
                "ordinal": 1,
                "due_date": "2026-03-15",
                "time_precision": "date_only",
            },
            review_status=ReviewStatus.PENDING,
        )
    )
    db_session.commit()

    authenticate_client(client, user=user_a)
    response_a = client.get("/changes/summary", headers={"X-API-Key": "test-api-key"})
    assert response_a.status_code == 200
    assert response_a.json()["changes_pending"] == 1

    client.cookies.clear()
    authenticate_client(client, user=user_b)
    response_b = client.get("/changes/summary", headers={"X-API-Key": "test-api-key"})
    assert response_b.status_code == 200
    assert response_b.json()["changes_pending"] == 0
