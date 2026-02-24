from __future__ import annotations

from app.modules.sync.service import SyncRunResult
from app.db.models import SyncRunStatus, SyncTriggerType


REGISTER_PAYLOAD = {
    "notify_email": "student@example.com",
    "ics": {
        "url": "https://example.com/calendar.ics",
    },
}


def test_onboarding_status_needs_user_by_default(client) -> None:
    response = client.get("/v1/onboarding/status", headers={"X-API-Key": "test-api-key"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["stage"] == "needs_user"
    assert payload["registered_user_id"] is None


def test_onboarding_status_needs_ics_after_user_registration(client) -> None:
    init = client.post(
        "/v1/user",
        headers={"X-API-Key": "test-api-key"},
        json={"notify_email": "student@example.com"},
    )
    assert init.status_code in {200, 201}

    response = client.get("/v1/onboarding/status", headers={"X-API-Key": "test-api-key"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["stage"] == "needs_ics"
    assert payload["registered_user_id"] is not None


def test_onboarding_register_success_marks_ready(client, monkeypatch) -> None:
    def fake_sync_source(db, input, notifier=None, trigger_type=SyncTriggerType.MANUAL, lock_owner=None):  # noqa: ANN001
        return SyncRunResult(
            input_id=input.id,
            changes_created=0,
            email_sent=False,
            last_error=None,
            is_baseline_sync=True,
            status=SyncRunStatus.NO_CHANGE,
            trigger_type=trigger_type,
        )

    monkeypatch.setattr("app.modules.onboarding.service.sync_source", fake_sync_source)

    register = client.post(
        "/v1/onboarding/register",
        headers={"X-API-Key": "test-api-key"},
        json=REGISTER_PAYLOAD,
    )
    assert register.status_code == 200
    body = register.json()
    assert body["status"] == "ready"
    assert body["is_baseline_sync"] is True
    assert "term_id" not in body

    status_response = client.get("/v1/onboarding/status", headers={"X-API-Key": "test-api-key"})
    assert status_response.status_code == 200
    assert status_response.json()["stage"] == "ready"


def test_onboarding_register_blocks_on_baseline_failure(client, monkeypatch) -> None:
    def fake_sync_source(db, input, notifier=None, trigger_type=SyncTriggerType.MANUAL, lock_owner=None):  # noqa: ANN001
        return SyncRunResult(
            input_id=input.id,
            changes_created=0,
            email_sent=False,
            last_error="parse invalid ics",
            is_baseline_sync=False,
            status=SyncRunStatus.PARSE_FAILED,
            trigger_type=trigger_type,
        )

    monkeypatch.setattr("app.modules.onboarding.service.sync_source", fake_sync_source)

    register = client.post(
        "/v1/onboarding/register",
        headers={"X-API-Key": "test-api-key"},
        json=REGISTER_PAYLOAD,
    )
    assert register.status_code == 422

    status_response = client.get("/v1/onboarding/status", headers={"X-API-Key": "test-api-key"})
    assert status_response.status_code == 200
    assert status_response.json()["stage"] == "needs_baseline"


def test_gate_returns_onboarding_incomplete_until_ready(client) -> None:
    init = client.post(
        "/v1/user",
        headers={"X-API-Key": "test-api-key"},
        json={"notify_email": "student@example.com"},
    )
    assert init.status_code in {200, 201}

    feed = client.get("/v1/feed", headers={"X-API-Key": "test-api-key"})
    assert feed.status_code == 409
    assert feed.json()["detail"]["code"] == "user_onboarding_incomplete"

    create_input = client.post(
        "/v1/inputs/ics",
        headers={"X-API-Key": "test-api-key"},
        json={"url": "https://example.com/incomplete.ics"},
    )
    assert create_input.status_code == 409
    assert create_input.json()["detail"]["code"] == "user_onboarding_incomplete"

    prefs = client.get("/v1/notification_prefs", headers={"X-API-Key": "test-api-key"})
    assert prefs.status_code == 409
    assert prefs.json()["detail"]["code"] == "user_onboarding_incomplete"
