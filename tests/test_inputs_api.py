from __future__ import annotations

import importlib
from datetime import datetime, timezone

from app.db.models import Input
from app.db.models import InputType, SyncRunStatus, SyncTriggerType
from app.modules.inputs.schemas import InputCreateRequest
from app.modules.inputs.service import create_gmail_input_from_oauth, create_ics_input
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


def test_inputs_list_endpoint_returns_workspace_inputs(client, initialized_user, db_session) -> None:
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


def test_delete_email_input_soft_deactivates_row(client, initialized_user, db_session) -> None:
    headers = {"X-API-Key": "test-api-key"}

    created = create_gmail_input_from_oauth(
        db_session,
        user_id=initialized_user["id"],
        label="INBOX",
        from_contains=None,
        subject_keywords=None,
        account_email="mailbox@example.com",
        history_id=None,
        access_token="access-token",
        refresh_token="refresh-token",
        access_token_expires_at=datetime.now(timezone.utc),
    )
    input_id = created.input.id

    response = client.delete(f"/v1/inputs/{input_id}", headers=headers)
    assert response.status_code == 204
    second_response = client.delete(f"/v1/inputs/{input_id}", headers=headers)
    assert second_response.status_code == 204

    db_session.expire_all()
    row = db_session.get(Input, input_id)
    assert row is not None
    assert row.is_active is False


def test_delete_primary_ics_input_returns_conflict(client, initialized_user, db_session) -> None:
    headers = {"X-API-Key": "test-api-key"}
    ics_row = db_session.query(Input).filter(Input.user_id == initialized_user["id"], Input.type == InputType.ICS).one()

    response = client.delete(f"/v1/inputs/{ics_row.id}", headers=headers)
    assert response.status_code == 409
    payload = response.json()
    assert payload["detail"]["code"] == "cannot_deactivate_primary_ics"


def test_manual_sync_rejects_inactive_input(client, initialized_user, db_session) -> None:
    headers = {"X-API-Key": "test-api-key"}
    input_id = _create_ics_input_for_user(
        db_session=db_session,
        user_id=initialized_user["id"],
        url="https://example.com/input-inactive-sync.ics",
    )

    input_row = db_session.get(Input, input_id)
    assert input_row is not None
    input_row.is_active = False
    db_session.commit()

    response = client.post(f"/v1/inputs/{input_id}/sync", headers=headers)
    assert response.status_code == 409
    payload = response.json()
    assert payload["detail"]["code"] == "input_inactive"
