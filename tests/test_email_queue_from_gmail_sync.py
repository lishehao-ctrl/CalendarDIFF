from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import EmailMessage, EmailRoute, EmailRuleAnalysis, EmailRuleLabel, User
from app.modules.inputs.service import create_gmail_input_from_oauth
from app.modules.sync.email_llm_fallback import LlmExtractDecision
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


def test_gmail_sync_ambiguous_rule_uses_llm_keep_and_enters_review(client, db_session, monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_NOTIFICATIONS", "false")
    monkeypatch.setenv("EMAIL_LLM_FALLBACK_ENABLED", "true")
    monkeypatch.setenv("EMAIL_LLM_BASE_URL", "http://llm.local/v1")
    monkeypatch.setenv("EMAIL_LLM_API_KEY", "sk-test")
    monkeypatch.setenv("EMAIL_LLM_CONFIDENCE_THRESHOLD", "0.85")
    get_settings.cache_clear()

    user = User(
        email="owner@example.com",
        notify_email="student@example.com",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.flush()
    create_ics_input_for_user(db_session, user_id=user.id, url="https://example.com/email-queue-gmail-sync-llm-1.ics")

    input_row = create_gmail_input_from_oauth(
        db_session,
        user_id=user.id,
        label=None,
        from_contains=None,
        subject_keywords=None,
        account_email="student@example.com",
        history_id="200",
        access_token="access-token",
        refresh_token="refresh-token",
        access_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    ).input

    def fake_get_profile(self, *, access_token: str) -> GmailProfile:  # noqa: ANN001
        assert access_token == "access-token"
        return GmailProfile(email_address="student@example.com", history_id="201")

    def fake_list_history(self, *, access_token: str, start_history_id: str) -> GmailHistoryResult:  # noqa: ANN001
        assert access_token == "access-token"
        assert start_history_id == "200"
        return GmailHistoryResult(message_ids=["m-llm-keep"], history_id="201")

    def fake_get_message_metadata(self, *, access_token: str, message_id: str) -> GmailMessageMetadata:  # noqa: ANN001
        assert access_token == "access-token"
        assert message_id == "m-llm-keep"
        return GmailMessageMetadata(
            message_id=message_id,
            snippet="Please submit soon",
            body_text="This is a custom formatted reminder message",
            internal_date="2026-02-22T10:00:00+00:00",
            subject="[CSE 100] assignment reminder",
            from_header="instructor@school.edu",
            label_ids=["INBOX"],
        )

    def fake_extract(self, payload):  # noqa: ANN001
        assert payload.rule_score == 0.0
        return LlmExtractDecision.model_validate(
            {
                "label": "KEEP",
                "event_type": "deadline",
                "confidence": 0.91,
                "reasons": ["deadline inferred from arbitrary wording"],
                "raw_extract": {"deadline_text": "Mar 3 11:59 PM PT", "time_text": "2026-03-04T07:59:00+00:00"},
                "action_items": [
                    {
                        "action": "Review inferred deadline update",
                        "due_iso": "2026-03-04T07:59:00+00:00",
                        "where_text": None,
                    }
                ],
            }
        )

    monkeypatch.setattr("app.modules.sync.service.GmailClient.get_profile", fake_get_profile)
    monkeypatch.setattr("app.modules.sync.service.GmailClient.list_history", fake_list_history)
    monkeypatch.setattr("app.modules.sync.service.GmailClient.get_message_metadata", fake_get_message_metadata)
    monkeypatch.setattr("app.modules.emails.service.EmailLlmFallbackClient.extract_for_ambiguous_email", fake_extract)

    headers = {"X-API-Key": "test-api-key"}
    sync_response = client.post(f"/v1/inputs/{input_row.id}/sync", headers=headers)
    assert sync_response.status_code == 200
    assert sync_response.json()["changes_created"] == 1

    queue_response = client.get("/v1/review/emails?route=review", headers=headers)
    assert queue_response.status_code == 200
    rows = queue_response.json()
    assert len(rows) == 1
    assert rows[0]["email_id"] == "m-llm-keep"
    assert rows[0]["action_items"][0]["due_iso"] == "2026-03-04T07:59:00+00:00"

    label_row = db_session.scalar(select(EmailRuleLabel).where(EmailRuleLabel.email_id == "m-llm-keep"))
    assert label_row is not None
    assert label_row.notes is not None
    assert "origin=llm_fallback" in label_row.notes

    get_settings.cache_clear()


def test_gmail_sync_ambiguous_rule_low_confidence_keep_is_dropped(client, db_session, monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_NOTIFICATIONS", "false")
    monkeypatch.setenv("EMAIL_LLM_FALLBACK_ENABLED", "true")
    monkeypatch.setenv("EMAIL_LLM_BASE_URL", "http://llm.local/v1")
    monkeypatch.setenv("EMAIL_LLM_API_KEY", "sk-test")
    monkeypatch.setenv("EMAIL_LLM_CONFIDENCE_THRESHOLD", "0.85")
    get_settings.cache_clear()

    user = User(
        email="owner@example.com",
        notify_email="student@example.com",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.flush()
    create_ics_input_for_user(db_session, user_id=user.id, url="https://example.com/email-queue-gmail-sync-llm-2.ics")

    input_row = create_gmail_input_from_oauth(
        db_session,
        user_id=user.id,
        label=None,
        from_contains=None,
        subject_keywords=None,
        account_email="student@example.com",
        history_id="300",
        access_token="access-token",
        refresh_token="refresh-token",
        access_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    ).input

    def fake_get_profile(self, *, access_token: str) -> GmailProfile:  # noqa: ANN001
        assert access_token == "access-token"
        return GmailProfile(email_address="student@example.com", history_id="301")

    def fake_list_history(self, *, access_token: str, start_history_id: str) -> GmailHistoryResult:  # noqa: ANN001
        assert access_token == "access-token"
        assert start_history_id == "300"
        return GmailHistoryResult(message_ids=["m-llm-low"], history_id="301")

    def fake_get_message_metadata(self, *, access_token: str, message_id: str) -> GmailMessageMetadata:  # noqa: ANN001
        assert access_token == "access-token"
        assert message_id == "m-llm-low"
        return GmailMessageMetadata(
            message_id=message_id,
            snippet="Please submit soon",
            body_text="Unstructured reminder",
            internal_date="2026-02-22T10:00:00+00:00",
            subject="[CSE 100] assignment reminder",
            from_header="instructor@school.edu",
            label_ids=["INBOX"],
        )

    def fake_extract(self, payload):  # noqa: ANN001
        assert payload.rule_score == 0.0
        return LlmExtractDecision.model_validate(
            {
                "label": "KEEP",
                "event_type": "deadline",
                "confidence": 0.81,
                "reasons": ["possible deadline"],
                "raw_extract": {"deadline_text": None, "time_text": None, "location_text": None},
                "action_items": [],
            }
        )

    monkeypatch.setattr("app.modules.sync.service.GmailClient.get_profile", fake_get_profile)
    monkeypatch.setattr("app.modules.sync.service.GmailClient.list_history", fake_list_history)
    monkeypatch.setattr("app.modules.sync.service.GmailClient.get_message_metadata", fake_get_message_metadata)
    monkeypatch.setattr("app.modules.emails.service.EmailLlmFallbackClient.extract_for_ambiguous_email", fake_extract)

    headers = {"X-API-Key": "test-api-key"}
    sync_response = client.post(f"/v1/inputs/{input_row.id}/sync", headers=headers)
    assert sync_response.status_code == 200
    assert sync_response.json()["changes_created"] == 0

    route_row = db_session.scalar(select(EmailRoute).where(EmailRoute.email_id == "m-llm-low"))
    assert route_row is not None
    assert route_row.route == "drop"
    analysis_row = db_session.scalar(select(EmailRuleAnalysis).where(EmailRuleAnalysis.email_id == "m-llm-low"))
    assert analysis_row is not None
    assert analysis_row.drop_reason_codes == ["llm_fallback_low_confidence"]

    get_settings.cache_clear()


def test_gmail_sync_ambiguous_rule_llm_drop_is_not_queued(client, db_session, monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_NOTIFICATIONS", "false")
    monkeypatch.setenv("EMAIL_LLM_FALLBACK_ENABLED", "true")
    monkeypatch.setenv("EMAIL_LLM_BASE_URL", "http://llm.local/v1")
    monkeypatch.setenv("EMAIL_LLM_API_KEY", "sk-test")
    get_settings.cache_clear()

    user = User(
        email="owner@example.com",
        notify_email="student@example.com",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.flush()
    create_ics_input_for_user(db_session, user_id=user.id, url="https://example.com/email-queue-gmail-sync-llm-3.ics")

    input_row = create_gmail_input_from_oauth(
        db_session,
        user_id=user.id,
        label=None,
        from_contains=None,
        subject_keywords=None,
        account_email="student@example.com",
        history_id="400",
        access_token="access-token",
        refresh_token="refresh-token",
        access_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    ).input

    def fake_get_profile(self, *, access_token: str) -> GmailProfile:  # noqa: ANN001
        assert access_token == "access-token"
        return GmailProfile(email_address="student@example.com", history_id="401")

    def fake_list_history(self, *, access_token: str, start_history_id: str) -> GmailHistoryResult:  # noqa: ANN001
        assert access_token == "access-token"
        assert start_history_id == "400"
        return GmailHistoryResult(message_ids=["m-llm-drop"], history_id="401")

    def fake_get_message_metadata(self, *, access_token: str, message_id: str) -> GmailMessageMetadata:  # noqa: ANN001
        assert access_token == "access-token"
        assert message_id == "m-llm-drop"
        return GmailMessageMetadata(
            message_id=message_id,
            snippet="Please submit soon",
            body_text="This message has no real action",
            internal_date="2026-02-22T10:00:00+00:00",
            subject="[CSE 100] assignment reminder",
            from_header="instructor@school.edu",
            label_ids=["INBOX"],
        )

    def fake_extract(self, payload):  # noqa: ANN001
        assert payload.rule_score == 0.0
        return LlmExtractDecision.model_validate(
            {
                "label": "DROP",
                "event_type": None,
                "confidence": 0.94,
                "reasons": ["general information only"],
                "raw_extract": {"deadline_text": None, "time_text": None, "location_text": None},
                "action_items": [],
            }
        )

    monkeypatch.setattr("app.modules.sync.service.GmailClient.get_profile", fake_get_profile)
    monkeypatch.setattr("app.modules.sync.service.GmailClient.list_history", fake_list_history)
    monkeypatch.setattr("app.modules.sync.service.GmailClient.get_message_metadata", fake_get_message_metadata)
    monkeypatch.setattr("app.modules.emails.service.EmailLlmFallbackClient.extract_for_ambiguous_email", fake_extract)

    headers = {"X-API-Key": "test-api-key"}
    sync_response = client.post(f"/v1/inputs/{input_row.id}/sync", headers=headers)
    assert sync_response.status_code == 200
    assert sync_response.json()["changes_created"] == 0

    route_row = db_session.scalar(select(EmailRoute).where(EmailRoute.email_id == "m-llm-drop"))
    assert route_row is not None
    assert route_row.route == "drop"
    analysis_row = db_session.scalar(select(EmailRuleAnalysis).where(EmailRuleAnalysis.email_id == "m-llm-drop"))
    assert analysis_row is not None
    assert analysis_row.drop_reason_codes == ["llm_fallback_drop"]

    get_settings.cache_clear()
