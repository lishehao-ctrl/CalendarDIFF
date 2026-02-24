from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.core.config import get_settings
from app.db.models import EmailRuleCandidate, ReviewCandidateStatus, User
from app.modules.inputs.service import create_gmail_input_from_oauth
from app.modules.sync.gmail_client import GmailHistoryResult, GmailMessageMetadata, GmailProfile


def test_gmail_sync_creates_review_candidate_and_is_idempotent(client, db_session, monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_NOTIFICATIONS", "false")
    get_settings.cache_clear()

    user = User(
        email="owner@example.com",
        notify_email="student@example.com",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.flush()

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
            snippet="Homework deadline moved to 2026-03-01T23:59:00-08:00",
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
    candidates = db_session.query(EmailRuleCandidate).filter(EmailRuleCandidate.input_id == input_row.id).all()
    list_response = client.get("/v1/review_candidates", headers=headers)
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.gmail_message_id == "m1"
    assert candidate.status == ReviewCandidateStatus.PENDING
    assert candidate.source_change_id is not None
    assert candidate.proposed_event_type in {"deadline", "schedule_change", "assignment", "exam", "action_required"}

    get_settings.cache_clear()
