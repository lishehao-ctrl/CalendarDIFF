from __future__ import annotations

def test_dev_inject_notify_endpoint_removed(client) -> None:
    response = client.post(
        "/v1/dev/inject_notify",
        headers={"X-API-Key": "test-api-key"},
        json={
            "subject": "demo",
            "from": "demo@example.com",
            "date": "2026-02-24T10:00:00Z",
            "body_text": "hello",
        },
    )
    assert response.status_code == 404
