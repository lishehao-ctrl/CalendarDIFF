from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.models import Change, EmailMessage, Input, User
from app.modules.inputs.service import create_gmail_input_from_oauth
from app.modules.sync.gmail_client import (
    GmailHistoryExpiredError,
    GmailHistoryResult,
    GmailMessageMetadata,
    GmailProfile,
)
from tests.helpers_inputs import create_ics_input_for_user


def test_email_input_first_sync_is_baseline_without_notification(client, db_session, monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_NOTIFICATIONS", "false")
    get_settings.cache_clear()

    user = User(
        email="owner@example.com",
        notify_email="student@example.com",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.flush()
    create_ics_input_for_user(db_session, user_id=user.id, url="https://example.com/email-source-sync-1.ics")

    input_row = create_gmail_input_from_oauth(
        db_session,
        user_id=user.id,
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
    assert runs_response.status_code == 404
    get_settings.cache_clear()


def test_email_input_changed_sync_queues_review_items_without_feed_changes(client, db_session, monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_NOTIFICATIONS", "false")
    get_settings.cache_clear()

    user = User(
        email="owner@example.com",
        notify_email="student@example.com",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.flush()
    create_ics_input_for_user(db_session, user_id=user.id, url="https://example.com/email-source-sync-2.ics")

    input_row = create_gmail_input_from_oauth(
        db_session,
        user_id=user.id,
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
            body_text="Deadline moved to 2026-03-01T23:59:00-08:00",
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

    assert first_sync.json()["changes_created"] == 2
    assert second_sync.json()["changes_created"] == 0

    # Queue-first: gmail sync no longer writes directly into feed change rows.
    change_count = db_session.scalar(select(func.count(Change.id)).where(Change.input_id == input_row.id))
    assert change_count == 0
    assert db_session.scalar(select(EmailMessage).where(EmailMessage.email_id == "m1")) is not None
    assert db_session.scalar(select(EmailMessage).where(EmailMessage.email_id == "m2")) is not None

    runs_response = client.get(f"/v1/inputs/{input_row.id}/runs?limit=2", headers=headers)
    assert runs_response.status_code == 404
    get_settings.cache_clear()


def test_email_input_history_expired_resets_cursor_without_notifying(client, db_session, monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_NOTIFICATIONS", "false")
    get_settings.cache_clear()

    user = User(
        email="owner@example.com",
        notify_email="student@example.com",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.flush()
    create_ics_input_for_user(db_session, user_id=user.id, url="https://example.com/email-source-sync-3.ics")

    input_row = create_gmail_input_from_oauth(
        db_session,
        user_id=user.id,
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
    assert runs_response.status_code == 404
    get_settings.cache_clear()
