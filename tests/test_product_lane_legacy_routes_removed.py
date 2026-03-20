from __future__ import annotations

from datetime import datetime, timezone

from app.db.models.shared import User


def _create_user(db_session) -> User:
    user = User(
        notify_email="legacy-routes-removed@example.com",
        password_hash="hash",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def test_legacy_product_lane_routes_return_404(input_client, db_session, authenticate_client) -> None:
    user = _create_user(db_session)
    authenticate_client(input_client, user=user)
    headers = {"X-API-Key": "test-api-key"}

    responses = [
        input_client.get("/review/summary", headers=headers),
        input_client.get("/review/changes", headers=headers),
        input_client.post("/review/edits", headers=headers, json={}),
        input_client.get("/review/raw-type-suggestions", headers=headers),
        input_client.get("/review/course-work-item-families", headers=headers),
        input_client.get("/review/course-work-item-raw-types", headers=headers),
        input_client.get("/profile/me", headers=headers),
        input_client.get("/events/manual", headers=headers),
    ]

    assert all(response.status_code == 404 for response in responses)
