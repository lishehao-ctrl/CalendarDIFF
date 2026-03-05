from __future__ import annotations

from types import SimpleNamespace

from app.db.models.ingestion import ConnectorResultStatus
from app.modules.ingestion.calendar_fetcher import fetch_calendar_delta
from app.modules.ingestion.gmail_fetcher import fetch_gmail_changes, matches_gmail_source_filters


def test_gmail_fetcher_missing_access_token_fails_auth(monkeypatch) -> None:
    source = SimpleNamespace(config=None, cursor=None)
    monkeypatch.setattr(
        "app.modules.ingestion.gmail_fetcher.decode_source_secrets",
        lambda _source: {},
    )
    outcome = fetch_gmail_changes(source=source, request_id="req-1")
    assert outcome.status == ConnectorResultStatus.AUTH_FAILED
    assert outcome.error_code == "gmail_missing_access_token"
    assert outcome.parse_payload is None


def test_calendar_fetcher_missing_url_fails_auth(monkeypatch) -> None:
    source = SimpleNamespace(id=100, cursor=None)
    monkeypatch.setattr(
        "app.modules.ingestion.calendar_fetcher.decode_source_secrets",
        lambda _source: {},
    )
    outcome = fetch_calendar_delta(source=source)
    assert outcome.status == ConnectorResultStatus.AUTH_FAILED
    assert outcome.error_code == "calendar_missing_url"
    assert outcome.parse_payload is None


def test_gmail_filter_contract_honors_subject_and_sender() -> None:
    metadata = SimpleNamespace(
        label_ids=["INBOX", "COURSE"],
        from_header="professor@school.edu",
        subject="Homework deadline reminder",
    )
    assert (
        matches_gmail_source_filters(
            metadata=metadata,
            config={
                "subject_keywords": ["deadline", "exam"],
                "from_contains": "school.edu",
                "label_ids": ["COURSE"],
            },
        )
        is True
    )
    assert (
        matches_gmail_source_filters(
            metadata=metadata,
            config={"subject_keywords": ["quiz"], "from_contains": "school.edu"},
        )
        is False
    )
