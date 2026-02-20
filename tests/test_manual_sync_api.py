from __future__ import annotations

from app.modules.sync.service import SyncRunResult


def test_manual_sync_endpoint_returns_sync_summary(client, monkeypatch) -> None:
    headers = {"X-API-Key": "test-api-key"}

    create_response = client.post(
        "/v1/sources/ics",
        headers=headers,
        json={"name": "My Calendar", "url": "https://example.com/feed.ics"},
    )
    assert create_response.status_code == 201
    source_id = create_response.json()["id"]

    def fake_sync_source(*args, **kwargs):
        source = kwargs.get("source") or args[1]
        return SyncRunResult(source_id=source.id, changes_created=2, email_sent=True, last_error=None)

    monkeypatch.setattr("app.modules.sources.service.sync_source", fake_sync_source)

    response = client.post(f"/v1/sources/{source_id}/sync", headers=headers)
    assert response.status_code == 200

    payload = response.json()
    assert payload == {
        "source_id": source_id,
        "changes_created": 2,
        "email_sent": True,
        "last_error": None,
    }
