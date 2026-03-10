from __future__ import annotations

from datetime import datetime, timezone

from app.db.models.shared import User


def _create_user(db_session) -> User:
    user = User(
        email=None,
        notify_email="family-user@example.com",
        password_hash="hash",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def test_course_work_item_family_crud(input_client, db_session, authenticate_client) -> None:
    user = _create_user(db_session)
    authenticate_client(input_client, user=user)

    list_response = input_client.get("/users/me/course-work-item-families", headers={"X-API-Key": "test-api-key"})
    assert list_response.status_code == 200
    assert list_response.json() == []

    create_response = input_client.post(
        "/users/me/course-work-item-families",
        headers={"X-API-Key": "test-api-key"},
        json={"course_key": "CSE 100 WI26", "canonical_label": "Homework", "aliases": ["hw"]},
    )
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["course_key"] == "CSE 100 WI26"
    assert created["canonical_label"] == "Homework"
    assert created["aliases"] == ["hw"]

    courses_response = input_client.get("/users/me/course-work-item-families/courses", headers={"X-API-Key": "test-api-key"})
    assert courses_response.status_code == 200
    assert courses_response.json()["courses"] == ["CSE 100 WI26"]

    update_response = input_client.patch(
        f"/users/me/course-work-item-families/{created['id']}",
        headers={"X-API-Key": "test-api-key"},
        json={"course_key": "CSE 100 WI26", "canonical_label": "Homework", "aliases": ["hw", "homework"]},
    )
    assert update_response.status_code == 200
    assert update_response.json()["aliases"] == ["hw", "homework"]

    status_response = input_client.get("/users/me/course-work-item-families/status", headers={"X-API-Key": "test-api-key"})
    assert status_response.status_code == 200
    assert status_response.json()["state"] == "idle"

    delete_response = input_client.delete(
        f"/users/me/course-work-item-families/{created['id']}",
        headers={"X-API-Key": "test-api-key"},
    )
    assert delete_response.status_code == 200
    assert delete_response.json() == {"deleted": True}


def test_course_work_item_family_rejects_alias_collision(input_client, db_session, authenticate_client) -> None:
    user = _create_user(db_session)
    authenticate_client(input_client, user=user)

    first = input_client.post(
        "/users/me/course-work-item-families",
        headers={"X-API-Key": "test-api-key"},
        json={"course_key": "CSE 100 WI26", "canonical_label": "Homework", "aliases": ["hw"]},
    )
    assert first.status_code == 201

    second = input_client.post(
        "/users/me/course-work-item-families",
        headers={"X-API-Key": "test-api-key"},
        json={"course_key": "CSE 100 WI26", "canonical_label": "Programming Assignment", "aliases": ["hw"]},
    )
    assert second.status_code == 422
