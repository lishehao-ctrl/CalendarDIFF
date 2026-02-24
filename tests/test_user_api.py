from __future__ import annotations

from app.db.models import User


def test_user_get_404_until_initialized_and_post_is_idempotent(client) -> None:
    headers = {"X-API-Key": "test-api-key"}

    get_before = client.get("/v1/user", headers=headers)
    assert get_before.status_code == 404
    assert get_before.json()["detail"]["code"] == "user_not_initialized"

    create_response = client.post(
        "/v1/user",
        headers=headers,
        json={"notify_email": "student-a@example.com"},
    )
    assert create_response.status_code == 201
    assert create_response.json()["notify_email"] == "student-a@example.com"

    get_after = client.get("/v1/user", headers=headers)
    assert get_after.status_code == 200
    assert get_after.json()["notify_email"] == "student-a@example.com"

    create_again = client.post(
        "/v1/user",
        headers=headers,
        json={"notify_email": "ignored@example.com"},
    )
    assert create_again.status_code == 200
    assert create_again.json()["notify_email"] == "student-a@example.com"


def test_user_post_validates_email_and_patch_cannot_clear_notify(client) -> None:
    headers = {"X-API-Key": "test-api-key"}

    invalid_create = client.post(
        "/v1/user",
        headers=headers,
        json={"notify_email": "not-an-email"},
    )
    assert invalid_create.status_code == 422

    create_response = client.post(
        "/v1/user",
        headers=headers,
        json={"notify_email": "student-a@example.com"},
    )
    assert create_response.status_code == 201

    clear_notify = client.patch(
        "/v1/user",
        headers=headers,
        json={"notify_email": None},
    )
    assert clear_notify.status_code == 422


def test_legacy_user_without_notify_email_is_uninitialized(client, db_session) -> None:
    headers = {"X-API-Key": "test-api-key"}

    db_session.add(User(email="legacy@example.com", notify_email=None))
    db_session.commit()

    get_response = client.get("/v1/user", headers=headers)
    assert get_response.status_code == 404
    assert get_response.json()["detail"]["code"] == "user_not_initialized"

    init_response = client.post(
        "/v1/user",
        headers=headers,
        json={"notify_email": "student-b@example.com"},
    )
    assert init_response.status_code == 201
    assert init_response.json()["notify_email"] == "student-b@example.com"


def test_user_terms_require_initialized_user(client) -> None:
    headers = {"X-API-Key": "test-api-key"}

    list_before = client.get("/v1/user/terms", headers=headers)
    assert list_before.status_code == 409
    assert list_before.json()["detail"]["code"] == "user_not_initialized"

    create_user = client.post(
        "/v1/user",
        headers=headers,
        json={"notify_email": "student-a@example.com"},
    )
    assert create_user.status_code == 201

    create_term = client.post(
        "/v1/user/terms",
        headers=headers,
        json={
            "code": "WI26",
            "label": "Winter 2026",
            "starts_on": "2026-01-06",
            "ends_on": "2026-03-21",
            "is_active": True,
        },
    )
    assert create_term.status_code == 201
