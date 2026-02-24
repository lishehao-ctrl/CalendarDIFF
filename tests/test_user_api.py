from __future__ import annotations


def test_user_api_get_patch_and_create_ics_input(client) -> None:
    headers = {"X-API-Key": "test-api-key"}

    get_response = client.get("/v1/user", headers=headers)
    assert get_response.status_code == 200
    user_payload = get_response.json()
    user_id = user_payload["id"]

    patch_response = client.patch(
        "/v1/user",
        headers=headers,
        json={
            "notify_email": "student-a@example.com",
            "calendar_delay_seconds": 120,
        },
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["notify_email"] == "student-a@example.com"

    input_response = client.post(
        "/v1/inputs/ics",
        headers=headers,
        json={
            "url": "https://example.com/student-a.ics",
        },
    )
    assert input_response.status_code == 201
    created_input = input_response.json()
    assert created_input["user_id"] == user_id
    assert created_input["type"] == "ics"
    assert created_input["interval_minutes"] == 15
    assert created_input["notify_email"] is None
    assert created_input["upserted_existing"] is False

    sources_response = client.get("/v1/inputs", headers=headers)
    assert sources_response.status_code == 200
    sources = sources_response.json()
    assert len(sources) == 1
    assert sources[0]["user_id"] == user_id


def test_user_terms_create_list_patch(client) -> None:
    headers = {"X-API-Key": "test-api-key"}

    create_response = client.post(
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
    assert create_response.status_code == 201
    term_id = create_response.json()["id"]

    list_response = client.get("/v1/user/terms", headers=headers)
    assert list_response.status_code == 200
    rows = list_response.json()
    assert len(rows) == 1
    assert rows[0]["code"] == "WI26"

    patch_response = client.patch(
        f"/v1/user/terms/{term_id}",
        headers=headers,
        json={"label": "Winter 2026 Updated"},
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["label"] == "Winter 2026 Updated"


def test_input_create_rejects_legacy_interval_or_notify_fields(client) -> None:
    headers = {"X-API-Key": "test-api-key"}

    with_interval = client.post(
        "/v1/inputs/ics",
        headers=headers,
        json={
            "url": "https://example.com/legacy.ics",
            "interval_minutes": 30,
        },
    )
    assert with_interval.status_code == 422

    with_notify = client.post(
        "/v1/inputs/ics",
        headers=headers,
        json={
            "url": "https://example.com/legacy2.ics",
            "notify_email": "legacy@example.com",
        },
    )
    assert with_notify.status_code == 422

    gmail_with_interval = client.post(
        "/v1/inputs/email/gmail/oauth/start",
        headers=headers,
        json={"interval_minutes": 10},
    )
    assert gmail_with_interval.status_code == 422

    gmail_with_notify = client.post(
        "/v1/inputs/email/gmail/oauth/start",
        headers=headers,
        json={"notify_email": "legacy@example.com"},
    )
    assert gmail_with_notify.status_code == 422
