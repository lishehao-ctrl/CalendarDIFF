from __future__ import annotations

from sqlalchemy import select

from app.db.models import SyncRun
from app.modules.sync.service import SyncRunResult
from tests.helpers_inputs import create_ics_input_for_user


def test_manual_sync_endpoint_returns_sync_summary(client, initialized_user, db_session, monkeypatch) -> None:
    headers = {"X-API-Key": "test-api-key"}
    source_id = create_ics_input_for_user(
        db_session,
        user_id=initialized_user["id"],
        url="https://example.com/feed.ics",
    )

    def fake_sync_input(*args, **kwargs):
        source = kwargs.get("input") or args[1]
        return SyncRunResult(
            input_id=source.id,
            changes_created=2,
            email_sent=True,
            last_error=None,
            is_baseline_sync=False,
        )

    monkeypatch.setattr("app.modules.inputs.service.sync_input", fake_sync_input)

    response = client.post(f"/v1/inputs/{source_id}/sync", headers=headers)
    assert response.status_code == 200

    payload = response.json()
    assert payload == {
        "input_id": source_id,
        "changes_created": 2,
        "email_sent": True,
        "last_error": None,
        "error_code": None,
        "is_baseline_sync": False,
        "notification_state": None,
    }


def test_manual_sync_endpoint_uses_non_blocking_input_lock(client, initialized_user, db_session, monkeypatch) -> None:
    headers = {"X-API-Key": "test-api-key"}
    source_id = create_ics_input_for_user(
        db_session,
        user_id=initialized_user["id"],
        url="https://example.com/feed.ics",
    )

    calls: list[tuple[int, int]] = []

    def fake_try_acquire_input_lock(db, namespace: int, locked_input_id: int) -> bool:  # noqa: ANN001
        calls.append((namespace, locked_input_id))
        return True

    def fake_sync_input(*args, **kwargs):
        source = kwargs.get("input") or args[1]
        return SyncRunResult(
            input_id=source.id,
            changes_created=0,
            email_sent=False,
            last_error=None,
            is_baseline_sync=False,
        )

    monkeypatch.setattr("app.modules.inputs.service.try_acquire_input_lock", fake_try_acquire_input_lock)
    monkeypatch.setattr("app.modules.inputs.service.release_input_lock", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.modules.inputs.service.sync_input", fake_sync_input)

    response = client.post(f"/v1/inputs/{source_id}/sync", headers=headers)
    assert response.status_code == 200

    payload = response.json()
    assert payload["input_id"] == source_id
    assert payload["changes_created"] == 0
    assert payload["last_error"] is None
    assert len(calls) == 1
    assert calls[0][1] == source_id


def test_manual_sync_returns_busy_and_records_lock_skipped_run(client, initialized_user, db_session, monkeypatch) -> None:
    headers = {"X-API-Key": "test-api-key"}
    source_id = create_ics_input_for_user(
        db_session,
        user_id=initialized_user["id"],
        url="https://example.com/feed.ics",
    )

    monkeypatch.setattr("app.modules.inputs.service.try_acquire_input_lock", lambda *args, **kwargs: False)

    response = client.post(f"/v1/inputs/{source_id}/sync", headers=headers)
    assert response.status_code == 409

    payload = response.json()
    assert payload["detail"]["status"] == "LOCK_SKIPPED"
    assert payload["detail"]["code"] == "input_busy"
    assert payload["detail"]["message"] == "sync in progress"
    assert payload["detail"]["retry_after_seconds"] == 10
    assert payload["detail"]["recoverable"] is True
    assert response.headers["Retry-After"] == "10"

    runs_response = client.get(f"/v1/inputs/{source_id}/runs?limit=1", headers=headers)
    assert runs_response.status_code == 404

    run = db_session.scalar(
        select(SyncRun)
        .where(SyncRun.input_id == source_id)
        .order_by(SyncRun.id.desc())
        .limit(1)
    )
    assert run is not None
    assert run.status.value == "LOCK_SKIPPED"
    assert run.trigger_type.value == "manual"
    assert run.error_code == "input_lock_not_acquired"
