from __future__ import annotations

from datetime import datetime, timezone

from app.db.models.input import InputSource, SourceKind
from app.db.models.review import Change, ChangeOrigin, ChangeType, ReviewStatus
from app.db.models.shared import User


def _create_user_with_source(db_session, *, email: str) -> tuple[User, InputSource]:
    user = User(
        email=email,
        notify_email=email,
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.flush()
    source = InputSource(
        user_id=user.id,
        source_kind=SourceKind.EMAIL,
        provider="gmail",
        source_key=f"src-{user.id}",
        display_name="Inbox",
        is_active=True,
        poll_interval_seconds=900,
    )
    db_session.add(source)
    db_session.commit()
    db_session.refresh(user)
    db_session.refresh(source)
    return user, source


def test_review_items_summary_counts_pending_only_for_current_user(client, db_session, auth_headers) -> None:
    user, _source = _create_user_with_source(db_session, email="owner@example.com")
    other_user, _other_source = _create_user_with_source(db_session, email="other@example.com")

    now = datetime.now(timezone.utc)
    db_session.add_all(
        [
            Change(
                user_id=user.id,
                entity_uid="ent-owner-pending",
                change_origin=ChangeOrigin.INGEST_PROPOSAL,
                change_type=ChangeType.CREATED,
                detected_at=now,
                after_semantic_json={
                    "uid": "ent-owner-pending",
                    "course_dept": "CSE",
                    "course_number": 100,
                    "family_name": "Homework",
                    "event_name": "Homework 1",
                    "ordinal": 1,
                    "due_date": "2026-03-15",
                    "due_time": "23:59:00",
                    "time_precision": "datetime",
                },
                review_status=ReviewStatus.PENDING,
            ),
            Change(
                user_id=user.id,
                entity_uid="ent-owner-approved",
                change_origin=ChangeOrigin.MANUAL_CANONICAL_EDIT,
                change_type=ChangeType.DUE_CHANGED,
                detected_at=now,
                after_semantic_json={
                    "uid": "ent-owner-approved",
                    "course_dept": "CSE",
                    "course_number": 100,
                    "family_name": "Homework",
                    "event_name": "Homework 2",
                    "ordinal": 2,
                    "due_date": "2026-03-20",
                    "due_time": "23:59:00",
                    "time_precision": "datetime",
                },
                review_status=ReviewStatus.APPROVED,
                reviewed_at=now,
            ),
            Change(
                user_id=other_user.id,
                entity_uid="ent-other-pending",
                change_origin=ChangeOrigin.INGEST_PROPOSAL,
                change_type=ChangeType.CREATED,
                detected_at=now,
                after_semantic_json={
                    "uid": "ent-other-pending",
                    "course_dept": "CSE",
                    "course_number": 120,
                    "family_name": "Quiz",
                    "event_name": "Quiz 1",
                    "ordinal": 1,
                    "due_date": "2026-03-16",
                    "due_time": "10:00:00",
                    "time_precision": "datetime",
                },
                review_status=ReviewStatus.PENDING,
            ),
        ]
    )
    db_session.commit()

    response = client.get("/review/summary", headers=auth_headers(client, user=user))
    assert response.status_code == 200
    payload = response.json()
    assert payload["changes_pending"] == 1
    assert "link_candidates_pending" not in payload
    assert isinstance(payload["generated_at"], str)
