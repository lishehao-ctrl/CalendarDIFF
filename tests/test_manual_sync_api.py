from __future__ import annotations

from app.modules.sync.service import SyncRunResult


def test_manual_sync_endpoint_returns_sync_summary(client, initialized_user, monkeypatch) -> None:
    headers = {"X-API-Key": "test-api-key"}

    create_response = client.post(
        "/v1/inputs/ics",
        headers=headers,
        json={"url": "https://example.com/feed.ics"},
    )
    assert create_response.status_code == 201
    source_id = create_response.json()["id"]

    def fake_sync_source(*args, **kwargs):
        source = kwargs.get("input") or args[1]
        return SyncRunResult(
            input_id=source.id,
            changes_created=2,
            email_sent=True,
            last_error=None,
            is_baseline_sync=False,
        )

    monkeypatch.setattr("app.modules.inputs.service.sync_source", fake_sync_source)

    response = client.post(f"/v1/inputs/{source_id}/sync", headers=headers)
    assert response.status_code == 200

    payload = response.json()
    assert payload == {
        "input_id": source_id,
        "changes_created": 2,
        "email_sent": True,
        "last_error": None,
        "is_baseline_sync": False,
        "notification_state": None,
    }


def test_manual_sync_endpoint_uses_non_blocking_source_lock(client, initialized_user, monkeypatch) -> None:
    headers = {"X-API-Key": "test-api-key"}

    create_response = client.post(
        "/v1/inputs/ics",
        headers=headers,
        json={"url": "https://example.com/feed.ics"},
    )
    assert create_response.status_code == 201
    source_id = create_response.json()["id"]

    calls: list[tuple[int, int]] = []

    def fake_try_acquire_source_lock(db, namespace: int, locked_source_id: int) -> bool:  # noqa: ANN001
        calls.append((namespace, locked_source_id))
        return True

    def fake_sync_source(*args, **kwargs):
        source = kwargs.get("input") or args[1]
        return SyncRunResult(
            input_id=source.id,
            changes_created=0,
            email_sent=False,
            last_error=None,
            is_baseline_sync=False,
        )

    monkeypatch.setattr("app.modules.inputs.service.try_acquire_source_lock", fake_try_acquire_source_lock)
    monkeypatch.setattr("app.modules.inputs.service.release_source_lock", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.modules.inputs.service.sync_source", fake_sync_source)

    response = client.post(f"/v1/inputs/{source_id}/sync", headers=headers)
    assert response.status_code == 200

    payload = response.json()
    assert payload["input_id"] == source_id
    assert payload["changes_created"] == 0
    assert payload["last_error"] is None
    assert len(calls) == 1
    assert calls[0][1] == source_id


def test_manual_sync_returns_busy_and_records_lock_skipped_run(client, initialized_user, monkeypatch) -> None:
    headers = {"X-API-Key": "test-api-key"}

    create_response = client.post(
        "/v1/inputs/ics",
        headers=headers,
        json={"url": "https://example.com/feed.ics"},
    )
    assert create_response.status_code == 201
    source_id = create_response.json()["id"]

    monkeypatch.setattr("app.modules.inputs.service.try_acquire_source_lock", lambda *args, **kwargs: False)

    response = client.post(f"/v1/inputs/{source_id}/sync", headers=headers)
    assert response.status_code == 409

    payload = response.json()
    assert payload["detail"]["status"] == "LOCK_SKIPPED"
    assert payload["detail"]["code"] == "source_busy"
    assert payload["detail"]["message"] == "sync in progress"
    assert payload["detail"]["retry_after_seconds"] == 10
    assert payload["detail"]["recoverable"] is True
    assert response.headers["Retry-After"] == "10"

    runs_response = client.get(f"/v1/inputs/{source_id}/runs?limit=1", headers=headers)
    assert runs_response.status_code == 200
    runs = runs_response.json()
    assert len(runs) == 1
    assert runs[0]["status"] == "LOCK_SKIPPED"
    assert runs[0]["trigger_type"] == "manual"
    assert runs[0]["error_code"] == "source_lock_not_acquired"
