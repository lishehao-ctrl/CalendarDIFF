from __future__ import annotations

from sqlalchemy import func, select

from app.db.models import Change, Notification, Source


def test_manual_sync_failure_updates_source_error_without_changes_or_notifications(client, initialized_user, db_session, monkeypatch) -> None:
    headers = {"X-API-Key": "test-api-key"}

    create_response = client.post(
        "/v1/inputs/ics",
        headers=headers,
        json={"url": "https://example.com/failure.ics"},
    )
    assert create_response.status_code == 201
    source_id = create_response.json()["id"]

    def fake_fetch(self, url: str, source_id: int, **kwargs):  # noqa: ARG001
        raise RuntimeError("simulated fetch failure")

    monkeypatch.setattr("app.modules.sync.service.ICSClient.fetch", fake_fetch)

    sync_response = client.post(f"/v1/inputs/{source_id}/sync", headers=headers)
    assert sync_response.status_code == 200
    payload = sync_response.json()
    assert payload["changes_created"] == 0
    assert payload["email_sent"] is False
    assert payload["last_error"] is not None

    db_session.expire_all()
    source = db_session.get(Source, source_id)
    assert source is not None
    assert source.last_checked_at is not None
    assert source.last_error is not None

    change_count = db_session.scalar(select(func.count(Change.id)).where(Change.input_id == source_id))
    notification_count = db_session.scalar(
        select(func.count(Notification.id)).join(Change, Notification.change_id == Change.id).where(Change.input_id == source_id)
    )
    assert change_count == 0
    assert notification_count == 0
