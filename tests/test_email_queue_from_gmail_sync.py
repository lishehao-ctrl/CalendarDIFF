from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import EmailMessage, EmailRoute, EmailRuleLabel, User
from app.modules.inputs.service import create_gmail_input_from_oauth
from app.modules.sync.gmail_client import GmailHistoryResult, GmailMessageMetadata, GmailProfile
from tests.helpers_inputs import create_ics_input_for_user


def test_gmail_sync_creates_email_review_queue_item_and_is_idempotent(client, db_session, monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_NOTIFICATIONS", "false")
    get_settings.cache_clear()

    user = User(
        email="owner@example.com",
        notify_email="student@example.com",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.flush()
    create_ics_input_for_user(db_session, user_id=user.id, url="https://example.com/email-queue-gmail-sync.ics")

    input_row = create_gmail_input_from_oauth(
        db_session,
        user_id=user.id,
        label=None,
        from_contains=None,
        subject_keywords=None,
        account_email="student@example.com",
        history_id="100",
        access_token="access-token",
        refresh_token="refresh-token",
        access_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    ).input

    def fake_get_profile(self, *, access_token: str) -> GmailProfile:  # noqa: ANN001
        assert access_token == "access-token"
        return GmailProfile(email_address="student@example.com", history_id="101")

    history_results = [
        GmailHistoryResult(message_ids=["m1"], history_id="101"),
        GmailHistoryResult(message_ids=["m1"], history_id="102"),
    ]

    def fake_list_history(self, *, access_token: str, start_history_id: str) -> GmailHistoryResult:  # noqa: ANN001
        assert access_token == "access-token"
        assert start_history_id in {"100", "101"}
        return history_results.pop(0)

    def fake_get_message_metadata(self, *, access_token: str, message_id: str) -> GmailMessageMetadata:  # noqa: ANN001
        assert access_token == "access-token"
        assert message_id == "m1"
        return GmailMessageMetadata(
            message_id="m1",
            snippet="Homework deadline moved to Mar 1 11:59 PM PT",
            body_text="Deadline moved to Mar 1 11:59 PM PT",
            internal_date="2026-02-22T10:00:00+00:00",
            subject="[CSE 100] homework deadline extension",
            from_header="instructor@school.edu",
            label_ids=["INBOX"],
        )

    monkeypatch.setattr("app.modules.sync.service.GmailClient.get_profile", fake_get_profile)
    monkeypatch.setattr("app.modules.sync.service.GmailClient.list_history", fake_list_history)
    monkeypatch.setattr("app.modules.sync.service.GmailClient.get_message_metadata", fake_get_message_metadata)

    headers = {"X-API-Key": "test-api-key"}
    first = client.post(f"/v1/inputs/{input_row.id}/sync", headers=headers)
    second = client.post(f"/v1/inputs/{input_row.id}/sync", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["changes_created"] == 1
    assert second.json()["changes_created"] == 0

    db_session.expire_all()
    assert db_session.scalar(select(EmailMessage).where(EmailMessage.email_id == "m1")) is not None
    route_row = db_session.scalar(select(EmailRoute).where(EmailRoute.email_id == "m1"))
    assert route_row is not None
    assert route_row.route == "review"
    label_row = db_session.scalar(select(EmailRuleLabel).where(EmailRuleLabel.email_id == "m1"))
    assert label_row is not None

    queue_response = client.get("/v1/review/emails?route=review", headers=headers)
    assert queue_response.status_code == 200
    rows = queue_response.json()
    assert len(rows) == 1
    assert rows[0]["email_id"] == "m1"
    assert rows[0]["action_items"][0]["due_iso"] == "2026-03-02T07:59:00+00:00"

    get_settings.cache_clear()
