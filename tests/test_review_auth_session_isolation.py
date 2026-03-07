from __future__ import annotations

from datetime import datetime, timezone

from app.db.models.input import InputSource, SourceKind
from app.db.models.review import EventLinkCandidate, EventLinkCandidateReason, EventLinkCandidateStatus
from app.db.models.shared import User


def test_review_summary_is_scoped_to_authenticated_user(client, db_session, authenticate_client) -> None:
    user_a = User(notify_email="a@example.com", password_hash="hash", onboarding_completed_at=datetime.now(timezone.utc))
    user_b = User(notify_email="b@example.com", password_hash="hash", onboarding_completed_at=datetime.now(timezone.utc))
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
        EventLinkCandidate(
            user_id=user_a.id,
            source_id=source_a.id,
            external_event_id="gmail-a-1",
            proposed_entity_uid="entity-a",
            score=0.8,
            score_breakdown_json={"total": 0.8},
            reason_code=EventLinkCandidateReason.SCORE_BAND,
            status=EventLinkCandidateStatus.PENDING,
        )
    )
    db_session.commit()

    authenticate_client(client, user=user_a)
    response_a = client.get("/review/summary", headers={"X-API-Key": "test-api-key"})
    assert response_a.status_code == 200
    assert response_a.json()["link_candidates_pending"] == 1

    client.cookies.clear()
    authenticate_client(client, user=user_b)
    response_b = client.get("/review/summary", headers={"X-API-Key": "test-api-key"})
    assert response_b.status_code == 200
    assert response_b.json()["link_candidates_pending"] == 0
