from __future__ import annotations

from datetime import datetime, timezone

from app.modules.sync.service import SyncRunResult
from app.db.models import Input, InputType, SyncRunStatus, SyncTriggerType, User


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


def test_onboarding_status_needs_ics_after_user_registration(client, db_session) -> None:
    db_session.add(User(email=None, notify_email="student@example.com", onboarding_completed_at=None))
    db_session.commit()

    response = client.get("/v1/onboarding/status", headers={"X-API-Key": "test-api-key"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["stage"] == "needs_ics"
    assert payload["registered_user_id"] is not None


def test_onboarding_register_success_marks_ready(client, monkeypatch) -> None:
    def fake_sync_input(db, input, notifier=None, trigger_type=SyncTriggerType.MANUAL, lock_owner=None):  # noqa: ANN001
        return SyncRunResult(
            input_id=input.id,
            changes_created=0,
            email_sent=False,
            last_error=None,
            is_baseline_sync=True,
            status=SyncRunStatus.NO_CHANGE,
            trigger_type=trigger_type,
        )

    monkeypatch.setattr("app.modules.onboarding.service.sync_input", fake_sync_input)

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
    def fake_sync_input(db, input, notifier=None, trigger_type=SyncTriggerType.MANUAL, lock_owner=None):  # noqa: ANN001
        return SyncRunResult(
            input_id=input.id,
            changes_created=0,
            email_sent=False,
            last_error="parse invalid ics",
            is_baseline_sync=False,
            status=SyncRunStatus.PARSE_FAILED,
            trigger_type=trigger_type,
        )

    monkeypatch.setattr("app.modules.onboarding.service.sync_input", fake_sync_input)

    register = client.post(
        "/v1/onboarding/register",
        headers={"X-API-Key": "test-api-key"},
        json=REGISTER_PAYLOAD,
    )
    assert register.status_code == 422

    status_response = client.get("/v1/onboarding/status", headers={"X-API-Key": "test-api-key"})
    assert status_response.status_code == 200
    assert status_response.json()["stage"] == "needs_ics"


def test_gate_returns_onboarding_incomplete_until_ready(client, db_session) -> None:
    db_session.add(User(email=None, notify_email="student@example.com", onboarding_completed_at=None))
    db_session.commit()

    feed = client.get("/v1/feed", headers={"X-API-Key": "test-api-key"})
    assert feed.status_code == 409
    assert feed.json()["detail"]["code"] == "user_onboarding_incomplete"

    inputs = client.get("/v1/inputs", headers={"X-API-Key": "test-api-key"})
    assert inputs.status_code == 409
    assert inputs.json()["detail"]["code"] == "user_onboarding_incomplete"

    prefs = client.get("/v1/notification_prefs", headers={"X-API-Key": "test-api-key"})
    assert prefs.status_code == 409
    assert prefs.json()["detail"]["code"] == "user_onboarding_incomplete"


def test_onboarding_reconfigure_keeps_single_ics_record(client, monkeypatch, db_session) -> None:
    def fake_sync_input(db, input, notifier=None, trigger_type=SyncTriggerType.MANUAL, lock_owner=None):  # noqa: ANN001
        return SyncRunResult(
            input_id=input.id,
            changes_created=0,
            email_sent=False,
            last_error=None,
            is_baseline_sync=True,
            status=SyncRunStatus.NO_CHANGE,
            trigger_type=trigger_type,
        )

    monkeypatch.setattr("app.modules.onboarding.service.sync_input", fake_sync_input)
    headers = {"X-API-Key": "test-api-key"}

    first = client.post("/v1/onboarding/register", headers=headers, json=REGISTER_PAYLOAD)
    assert first.status_code == 200
    first_input_id = first.json()["input_id"]

    second_payload = {
        "notify_email": "student@example.com",
        "ics": {"url": "https://example.com/calendar-2.ics"},
    }
    second = client.post("/v1/onboarding/register", headers=headers, json=second_payload)
    assert second.status_code == 200
    second_input_id = second.json()["input_id"]
    assert second_input_id != first_input_id

    inputs = db_session.query(Input).filter(Input.type == InputType.ICS).order_by(Input.id.asc()).all()
    assert len(inputs) == 1
    assert inputs[0].id == second_input_id
    assert inputs[0].is_active is True
    assert db_session.get(Input, first_input_id) is None


def test_onboarding_status_does_not_report_ready_without_ics(client, db_session) -> None:
    user = User(
        email=None,
        notify_email="student@example.com",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.commit()

    response = client.get("/v1/onboarding/status", headers={"X-API-Key": "test-api-key"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["stage"] == "needs_ics"


def test_onboarding_reconfigure_failure_clears_ics_and_blocks_gate(client, monkeypatch, db_session) -> None:
    calls = {"count": 0}

    def fake_sync_input(db, input, notifier=None, trigger_type=SyncTriggerType.MANUAL, lock_owner=None):  # noqa: ANN001
        calls["count"] += 1
        if calls["count"] == 1:
            return SyncRunResult(
                input_id=input.id,
                changes_created=0,
                email_sent=False,
                last_error=None,
                is_baseline_sync=True,
                status=SyncRunStatus.NO_CHANGE,
                trigger_type=trigger_type,
            )
        return SyncRunResult(
            input_id=input.id,
            changes_created=0,
            email_sent=False,
            last_error="parse invalid ics",
            is_baseline_sync=False,
            status=SyncRunStatus.PARSE_FAILED,
            trigger_type=trigger_type,
        )

    monkeypatch.setattr("app.modules.onboarding.service.sync_input", fake_sync_input)
    headers = {"X-API-Key": "test-api-key"}

    first = client.post("/v1/onboarding/register", headers=headers, json=REGISTER_PAYLOAD)
    assert first.status_code == 200

    second_payload = {
        "notify_email": "student@example.com",
        "ics": {"url": "https://example.com/calendar-broken.ics"},
    }
    second = client.post("/v1/onboarding/register", headers=headers, json=second_payload)
    assert second.status_code == 422

    status_response = client.get("/v1/onboarding/status", headers=headers)
    assert status_response.status_code == 200
    assert status_response.json()["stage"] == "needs_ics"

    remaining_ics = db_session.query(Input).filter(Input.type == InputType.ICS).all()
    assert remaining_ics == []

    feed = client.get("/v1/feed", headers=headers)
    assert feed.status_code == 409
    assert feed.json()["detail"]["code"] == "user_onboarding_incomplete"
