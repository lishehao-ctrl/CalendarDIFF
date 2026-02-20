from __future__ import annotations


def test_sources_api_requires_api_key(client) -> None:
    response = client.post(
        "/v1/sources/ics",
        json={"name": "My Calendar", "url": "https://example.com/feed.ics", "interval_minutes": 15},
    )
    assert response.status_code == 401


def test_create_and_list_sources_hides_url(client) -> None:
    headers = {"X-API-Key": "test-api-key"}

    create_response = client.post(
        "/v1/sources/ics",
        headers=headers,
        json={"name": "My Calendar", "url": "https://example.com/feed.ics", "interval_minutes": 20},
    )
    assert create_response.status_code == 201
    payload = create_response.json()

    assert payload["name"] == "My Calendar"
    assert payload["interval_minutes"] == 20
    assert "url" not in payload
    assert "encrypted_url" not in payload

    list_response = client.get("/v1/sources", headers=headers)
    assert list_response.status_code == 200

    items = list_response.json()
    assert len(items) == 1
    assert "url" not in items[0]
    assert "encrypted_url" not in items[0]
