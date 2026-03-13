from __future__ import annotations

from datetime import datetime, timezone

from app.db.models.input import InputSource, SourceKind
from app.db.models.review import Change, ChangeOrigin, ChangeSourceRef, ChangeType, ReviewStatus, SourceEventObservation
from app.db.models.shared import User


def _create_user_and_source(db_session) -> tuple[User, InputSource]:
    user = User(
        email="summary-owner@example.com",
        notify_email="summary-owner@example.com",
        onboarding_completed_at=datetime.now(timezone.utc),
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
    )
    db_session.add(source)
    db_session.commit()
    db_session.refresh(user)
    db_session.refresh(source)
    return user, source


def test_review_changes_created_exposes_primary_source_summary(client, db_session, auth_headers) -> None:
    user, source = _create_user_and_source(db_session)
    observed_at = datetime(2026, 3, 7, 8, 15, tzinfo=timezone.utc)
    db_session.add(
        SourceEventObservation(
            user_id=user.id,
            source_id=source.id,
            source_kind=source.source_kind,
            provider=source.provider,
            external_event_id="created-calendar-1",
            entity_uid="ent-created-1",
            event_payload={"semantic_event": {"uid": "ent-created-1", "course_dept": "CSE", "course_number": 100, "family_name": "Quiz", "event_name": "Quiz 1", "due_date": "2026-03-10", "time_precision": "date_only"}},
            event_hash="1" * 64,
            observed_at=observed_at,
            is_active=True,
        )
    )
    db_session.add(
        Change(
            user_id=user.id,
            entity_uid="ent-created-1",
            change_origin=ChangeOrigin.INGEST_PROPOSAL,
            change_type=ChangeType.CREATED,
            detected_at=datetime.now(timezone.utc),
            after_semantic_json={
                "uid": "ent-created-1",
                "course_dept": "CSE",
                "course_number": 100,
                "family_name": "Quiz",
                "event_name": "Quiz 1",
                "due_date": "2026-03-10",
                "time_precision": "date_only",
            },
            source_refs=[
                ChangeSourceRef(
                    position=0,
                    source_id=source.id,
                    source_kind=SourceKind.CALENDAR,
                    provider="ics",
                    external_event_id="created-calendar-1",
                    confidence=0.94,
                )
            ],
            after_evidence_json={"provider": "ics"},
            review_status=ReviewStatus.PENDING,
        )
    )
    db_session.commit()

    response = client.get("/review/changes?review_status=pending&limit=1", headers=auth_headers(client, user=user))
    assert response.status_code == 200
    payload = response.json()[0]
    assert payload["primary_source"]["source_id"] == source.id
    assert payload["change_summary"]["old"]["source_label"] is None
    assert payload["change_summary"]["new"]["source_label"] == "Canvas ICS"
    assert payload["change_summary"]["new"]["source_kind"] == "calendar"
    assert payload["change_summary"]["new"]["source_observed_at"] == "2026-03-07T08:15:00Z"
