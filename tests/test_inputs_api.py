from __future__ import annotations

import importlib

from app.db.models import SyncRunStatus, SyncTriggerType
from app.modules.sync.service import SyncRunResult

inputs_router_module = importlib.import_module("app.modules.inputs.router")


def _init_user(client) -> None:
    response = client.post(
        "/v1/user",
        headers={"X-API-Key": "test-api-key"},
        json={"notify_email": "student@example.com"},
    )
    assert response.status_code in {200, 201}


def test_inputs_require_initialized_user(client) -> None:
    headers = {"X-API-Key": "test-api-key"}

    create_response = client.post(
        "/v1/inputs/ics",
        headers=headers,
        json={"url": "https://example.com/input-alias.ics"},
    )
    assert create_response.status_code == 409
    assert create_response.json()["detail"]["code"] == "user_not_initialized"

    feed_response = client.get("/v1/feed", headers=headers)
    assert feed_response.status_code == 409
    assert feed_response.json()["detail"]["code"] == "user_not_initialized"


def test_inputs_list_and_runs_endpoints(client) -> None:
    headers = {"X-API-Key": "test-api-key"}
    _init_user(client)

    create_response = client.post(
        "/v1/inputs/ics",
        headers=headers,
        json={
            "url": "https://example.com/input-alias.ics",
        },
    )
    assert create_response.status_code == 201
    assert "user_id" not in create_response.json()
    source_id = create_response.json()["id"]

    list_response = client.get("/v1/inputs", headers=headers)
    assert list_response.status_code == 200
    rows = list_response.json()
    assert rows
    assert "user_id" not in rows[0]
    assert any(item["id"] == source_id for item in rows)

    runs_response = client.get(f"/v1/inputs/{source_id}/runs?limit=20", headers=headers)
    assert runs_response.status_code == 200
    assert isinstance(runs_response.json(), list)


def test_input_sync_endpoint_uses_existing_manual_sync_flow(client, monkeypatch) -> None:
    headers = {"X-API-Key": "test-api-key"}
    _init_user(client)

    create_response = client.post(
        "/v1/inputs/ics",
        headers=headers,
        json={
            "url": "https://example.com/input-sync.ics",
        },
    )
    assert create_response.status_code == 201
    source_id = create_response.json()["id"]

    def _fake_manual_sync(_db, input):
        return SyncRunResult(
            input_id=input.id,
            changes_created=0,
            email_sent=False,
            last_error=None,
            is_baseline_sync=True,
            status=SyncRunStatus.NO_CHANGE,
            trigger_type=SyncTriggerType.MANUAL,
        )

    monkeypatch.setattr(inputs_router_module, "run_manual_input_sync", _fake_manual_sync)
    sync_response = client.post(f"/v1/inputs/{source_id}/sync", headers=headers)
    assert sync_response.status_code == 200
    payload = sync_response.json()
    assert payload["input_id"] == source_id
    assert payload["is_baseline_sync"] is True


def test_legacy_source_routes_are_removed(client) -> None:
    headers = {"X-API-Key": "test-api-key"}

    source_list = client.get("/v1/sources", headers=headers)
    legacy_feed = client.get("/v1/changes/feed", headers=headers)
    legacy_changes = client.get("/v1/changes?input_id=1", headers=headers)
    legacy_snapshots = client.get("/v1/snapshots?input_id=1", headers=headers)

    assert source_list.status_code == 404
    assert legacy_feed.status_code == 404
    assert legacy_changes.status_code == 404
    assert legacy_snapshots.status_code == 404


def test_input_create_rejects_legacy_interval_or_notify_fields(client) -> None:
    headers = {"X-API-Key": "test-api-key"}
    _init_user(client)

    with_interval = client.post(
        "/v1/inputs/ics",
        headers=headers,
        json={
            "url": "https://example.com/input-legacy.ics",
            "interval_minutes": 5,
        },
    )
    assert with_interval.status_code == 422

    with_notify = client.post(
        "/v1/inputs/ics",
        headers=headers,
        json={
            "url": "https://example.com/input-legacy-notify.ics",
            "notify_email": "legacy@example.com",
        },
    )
    assert with_notify.status_code == 422
