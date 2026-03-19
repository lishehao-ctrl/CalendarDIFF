from __future__ import annotations

from datetime import datetime, timezone

from app.db.models.shared import User


def _create_user(db_session) -> User:
    user = User(
        notify_email="review-links-removed@example.com",
        password_hash="hash",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def test_legacy_review_links_endpoints_return_404(input_client, db_session, authenticate_client) -> None:
    user = _create_user(db_session)
    authenticate_client(input_client, user=user)
    headers = {"X-API-Key": "test-api-key"}

    responses = [
        input_client.get("/review/links", headers=headers),
        input_client.post(
            "/review/links/relink",
            headers=headers,
            json={
                "source_id": 1,
                "external_event_id": "evt-1",
                "entity_uid": "ent-1",
                "clear_block": True,
            },
        ),
        input_client.delete("/review/links/1", headers=headers),
        input_client.get("/review/link-candidates", headers=headers),
        input_client.post("/review/link-candidates/batch/decisions", headers=headers, json={"ids": [1], "decision": "approve"}),
        input_client.post("/review/link-candidates/1/decisions", headers=headers, json={"decision": "approve"}),
        input_client.get("/review/link-candidates/blocks", headers=headers),
        input_client.delete("/review/link-candidates/blocks/1", headers=headers),
    ]

    assert all(response.status_code == 404 for response in responses)
