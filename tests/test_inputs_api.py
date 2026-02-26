from __future__ import annotations

import importlib

from app.db.models import SyncRunStatus, SyncTriggerType
from app.modules.inputs.schemas import InputCreateRequest
from app.modules.inputs.service import create_ics_input
from app.modules.sync.service import SyncRunResult

inputs_router_module = importlib.import_module("app.modules.inputs.router")


def _create_ics_input_for_user(*, db_session, user_id: int, url: str) -> int:
    created = create_ics_input(
        db_session,
        user_id=user_id,
        payload=InputCreateRequest(url=url),
    )
    return created.input.id


def test_inputs_require_initialized_user(client) -> None:
    headers = {"X-API-Key": "test-api-key"}

    list_response = client.get("/v1/inputs", headers=headers)
    assert list_response.status_code == 409
    assert list_response.json()["detail"]["code"] == "user_not_initialized"

    feed_response = client.get("/v1/feed", headers=headers)
    assert feed_response.status_code == 409
    assert feed_response.json()["detail"]["code"] == "user_not_initialized"


def test_inputs_list_endpoint_and_runs_removed(client, initialized_user, db_session) -> None:
    headers = {"X-API-Key": "test-api-key"}
    input_id = _create_ics_input_for_user(
        db_session=db_session,
        user_id=initialized_user["id"],
        url="https://example.com/input-alias.ics",
    )

    list_response = client.get("/v1/inputs", headers=headers)
    assert list_response.status_code == 200
    rows = list_response.json()
    assert rows
    assert "user_id" not in rows[0]
    assert any(item["id"] == input_id for item in rows)

    runs_response = client.get(f"/v1/inputs/{input_id}/runs?limit=20", headers=headers)
    assert runs_response.status_code == 404


def test_input_sync_endpoint_uses_existing_manual_sync_flow(client, initialized_user, db_session, monkeypatch) -> None:
    headers = {"X-API-Key": "test-api-key"}
    input_id = _create_ics_input_for_user(
        db_session=db_session,
        user_id=initialized_user["id"],
        url="https://example.com/input-sync.ics",
    )

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
    sync_response = client.post(f"/v1/inputs/{input_id}/sync", headers=headers)
    assert sync_response.status_code == 200
    payload = sync_response.json()
    assert payload["input_id"] == input_id
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


def test_ics_input_create_route_removed(client, initialized_user) -> None:
    headers = {"X-API-Key": "test-api-key"}
    response = client.post(
        "/v1/inputs/ics",
        headers=headers,
        json={"url": "https://example.com/input-legacy.ics"},
    )
    assert response.status_code == 404
