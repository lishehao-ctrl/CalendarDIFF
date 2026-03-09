from __future__ import annotations

from datetime import datetime, timezone

from app.db.models.shared import User


def _create_user(db_session) -> User:
    user = User(
        email=None,
        notify_email="kind-mapping-user@example.com",
        password_hash="hash",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def test_work_item_kind_mapping_defaults_and_crud(input_client, db_session, authenticate_client) -> None:
    user = _create_user(db_session)
    authenticate_client(input_client, user=user)

    list_response = input_client.get("/users/me/work-item-kind-mappings", headers={"X-API-Key": "test-api-key"})
    assert list_response.status_code == 200
    payload = list_response.json()
    assert any(row["name"] == "Homework" for row in payload)

    create_response = input_client.post(
        "/users/me/work-item-kind-mappings",
        headers={"X-API-Key": "test-api-key"},
        json={"name": "Lab Paper", "aliases": ["lab paper"]},
    )
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["name"] == "Lab Paper"
    assert created["aliases"] == ["lab paper"]

    update_response = input_client.patch(
        f"/users/me/work-item-kind-mappings/{created['id']}",
        headers={"X-API-Key": "test-api-key"},
        json={"name": "Lab Paper", "aliases": ["lab paper", "paper lab"]},
    )
    assert update_response.status_code == 200
    assert update_response.json()["aliases"] == ["lab paper", "paper lab"]

    status_response = input_client.get("/users/me/work-item-kind-mappings/status", headers={"X-API-Key": "test-api-key"})
    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert status_payload["state"] == "idle"
    assert status_payload["last_error"] is None

    delete_response = input_client.delete(
        f"/users/me/work-item-kind-mappings/{created['id']}",
        headers={"X-API-Key": "test-api-key"},
    )
    assert delete_response.status_code == 200
    assert delete_response.json() == {"deleted": True}


def test_work_item_kind_mapping_rejects_alias_collision(input_client, db_session, authenticate_client) -> None:
    user = _create_user(db_session)
    authenticate_client(input_client, user=user)

    response = input_client.post(
        "/users/me/work-item-kind-mappings",
        headers={"X-API-Key": "test-api-key"},
        json={"name": "Homework", "aliases": ["hw"]},
    )
    assert response.status_code == 422
