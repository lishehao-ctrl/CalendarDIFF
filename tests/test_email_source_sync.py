from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.core.config import get_settings
from app.db.models import Input
from app.modules.inputs.service import create_gmail_input_from_oauth
from app.modules.sync.gmail_client import (
    GmailHistoryExpiredError,
    GmailHistoryResult,
    GmailMessageMetadata,
    GmailProfile,
)


def test_email_input_first_sync_is_baseline_without_notification(client, db_session, monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_NOTIFICATIONS", "false")
    get_settings.cache_clear()

    input_row = create_gmail_input_from_oauth(
        db_session,
        label=None,
        from_contains=None,
        subject_keywords=None,
        account_email="student@example.com",
        history_id=None,
        access_token="access-token",
        refresh_token="refresh-token",
        access_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    ).input

    def fake_get_profile(self, *, access_token: str) -> GmailProfile:  # noqa: ANN001
        assert access_token == "access-token"
        return GmailProfile(email_address="student@example.com", history_id="101")

    monkeypatch.setattr("app.modules.sync.service.GmailClient.get_profile", fake_get_profile)

    headers = {"X-API-Key": "test-api-key"}
    sync_response = client.post(f"/v1/inputs/{input_row.id}/sync", headers=headers)
    assert sync_response.status_code == 200
    payload = sync_response.json()
    assert payload["is_baseline_sync"] is True
    assert payload["changes_created"] == 0
    assert payload["email_sent"] is False

    runs_response = client.get(f"/v1/inputs/{input_row.id}/runs?limit=1", headers=headers)
    assert runs_response.status_code == 200
    runs = runs_response.json()
    assert len(runs) == 1
    assert runs[0]["status"] == "NO_CHANGE"
    assert runs[0]["trigger_type"] == "manual"

    get_settings.cache_clear()


def test_email_input_changed_sync_creates_changes_and_deduplicates(client, db_session, monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_NOTIFICATIONS", "false")
    get_settings.cache_clear()

    input_row = create_gmail_input_from_oauth(
        db_session,
        label=None,
        from_contains=None,
        subject_keywords=None,
        account_email="student@example.com",
        history_id="101",
        access_token="access-token",
        refresh_token="refresh-token",
        access_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    ).input

    def fake_get_profile(self, *, access_token: str) -> GmailProfile:  # noqa: ANN001
        assert access_token == "access-token"
        return GmailProfile(email_address="student@example.com", history_id="200")

    history_results = [
        GmailHistoryResult(message_ids=["m1", "m2"], history_id="200"),
        GmailHistoryResult(message_ids=["m1", "m2"], history_id="201"),
    ]

    def fake_list_history(self, *, access_token: str, start_history_id: str) -> GmailHistoryResult:  # noqa: ANN001
        assert access_token == "access-token"
        assert start_history_id in {"101", "200"}
        return history_results.pop(0)

    def fake_get_message_metadata(self, *, access_token: str, message_id: str) -> GmailMessageMetadata:  # noqa: ANN001
        assert access_token == "access-token"
        return GmailMessageMetadata(
            message_id=message_id,
            snippet=f"Snippet for {message_id}",
            internal_date="2026-02-22T10:00:00+00:00",
            subject=f"Subject {message_id}",
            from_header="instructor@school.edu",
            label_ids=["INBOX"],
        )

    monkeypatch.setattr("app.modules.sync.service.GmailClient.get_profile", fake_get_profile)
    monkeypatch.setattr("app.modules.sync.service.GmailClient.list_history", fake_list_history)
    monkeypatch.setattr("app.modules.sync.service.GmailClient.get_message_metadata", fake_get_message_metadata)

    headers = {"X-API-Key": "test-api-key"}
    first_sync = client.post(f"/v1/inputs/{input_row.id}/sync", headers=headers)
    second_sync = client.post(f"/v1/inputs/{input_row.id}/sync", headers=headers)
    assert first_sync.status_code == 200
    assert second_sync.status_code == 200

    first_payload = first_sync.json()
    second_payload = second_sync.json()
    assert first_payload["is_baseline_sync"] is False
    assert first_payload["changes_created"] == 2
    assert second_payload["changes_created"] == 0

    changes_response = client.get(f"/v1/inputs/{input_row.id}/changes?limit=20", headers=headers)
    assert changes_response.status_code == 200
    changes = changes_response.json()
    assert len(changes) == 2
    after_json = changes[0]["after_json"]
    assert after_json["subject"].startswith("Subject ")
    assert after_json["snippet"].startswith("Snippet for ")
    assert after_json["internal_date"] == "2026-02-22T10:00:00+00:00"
    assert after_json["from"] == "instructor@school.edu"
    assert after_json["gmail_message_id"] in {"m1", "m2"}
    assert after_json["open_in_gmail_url"].endswith(after_json["gmail_message_id"])

    runs_response = client.get(f"/v1/inputs/{input_row.id}/runs?limit=2", headers=headers)
    assert runs_response.status_code == 200
    runs = runs_response.json()
    assert len(runs) == 2
    assert runs[0]["status"] == "NO_CHANGE"
    assert runs[1]["status"] == "CHANGED"

    get_settings.cache_clear()


def test_email_input_history_expired_resets_cursor_without_notifying(client, db_session, monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_NOTIFICATIONS", "false")
    get_settings.cache_clear()

    input_row = create_gmail_input_from_oauth(
        db_session,
        label=None,
        from_contains=None,
        subject_keywords=None,
        account_email="student@example.com",
        history_id="101",
        access_token="access-token",
        refresh_token="refresh-token",
        access_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    ).input

    def fake_get_profile(self, *, access_token: str) -> GmailProfile:  # noqa: ANN001
        assert access_token == "access-token"
        return GmailProfile(email_address="student@example.com", history_id="999")

    def fake_list_history(self, *, access_token: str, start_history_id: str):  # noqa: ANN001
        assert access_token == "access-token"
        assert start_history_id == "101"
        raise GmailHistoryExpiredError(status_code=404, message="History not found")

    monkeypatch.setattr("app.modules.sync.service.GmailClient.get_profile", fake_get_profile)
    monkeypatch.setattr("app.modules.sync.service.GmailClient.list_history", fake_list_history)

    headers = {"X-API-Key": "test-api-key"}
    sync_response = client.post(f"/v1/inputs/{input_row.id}/sync", headers=headers)
    assert sync_response.status_code == 200
    payload = sync_response.json()
    assert payload["is_baseline_sync"] is False
    assert payload["changes_created"] == 0
    assert payload["email_sent"] is False

    db_session.expire_all()
    updated_input = db_session.get(Input, input_row.id)
    assert updated_input is not None
    assert updated_input.gmail_history_id == "999"

    runs_response = client.get(f"/v1/inputs/{input_row.id}/runs?limit=1", headers=headers)
    assert runs_response.status_code == 200
    assert runs_response.json()[0]["status"] == "NO_CHANGE"

    get_settings.cache_clear()
