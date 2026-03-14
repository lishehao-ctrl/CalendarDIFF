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


def test_gmail_fetcher_bootstraps_term_window_messages(monkeypatch) -> None:
    source = SimpleNamespace(
        config=SimpleNamespace(
            config_json={
                "label_id": "COURSE",
                "term_key": "WI26",
                "term_from": "2026-01-05",
                "term_to": "2026-03-20",
            }
        ),
        cursor=SimpleNamespace(cursor_json={}),
        user=SimpleNamespace(timezone_name="America/Los_Angeles"),
    )

    class _FakeGmailClient:
        def get_profile(self, *, access_token: str):
            assert access_token == "token"
            return SimpleNamespace(email_address="student@example.edu", history_id="200")

        def list_message_ids(self, *, access_token: str, query: str | None = None, label_ids=None):
            assert access_token == "token"
            assert query == "after:2025/12/06 before:2026/04/20"
            assert label_ids == ["COURSE"]
            return ["m1", "m2"]

        def get_message_metadata(self, *, access_token: str, message_id: str):
            assert access_token == "token"
            internal_date = {
                "m1": "2026-02-01T15:00:00+00:00",
                "m2": "2026-05-01T15:00:00+00:00",
            }[message_id]
            return SimpleNamespace(
                message_id=message_id,
                thread_id=f"thread-{message_id}",
                snippet=f"snippet-{message_id}",
                body_text=f"body-{message_id}",
                from_header="professor@school.edu",
                subject="Homework reminder",
                internal_date=internal_date,
                label_ids=["COURSE"],
            )

    monkeypatch.setattr("app.modules.ingestion.gmail_fetcher.decode_source_secrets", lambda _source: {"access_token": "token"})
    monkeypatch.setattr("app.modules.ingestion.gmail_fetcher.GmailClient", _FakeGmailClient)

    outcome = fetch_gmail_changes(source=source, request_id="req-bootstrap")

    assert outcome.status == ConnectorResultStatus.CHANGED
    assert outcome.cursor_patch == {"history_id": "200"}
    assert outcome.parse_payload is not None
    assert outcome.parse_payload["kind"] == "gmail"
    assert [row["message_id"] for row in outcome.parse_payload["messages"]] == ["m1"]


def test_calendar_fetcher_filters_changed_components_outside_term_window(monkeypatch) -> None:
    source = SimpleNamespace(
        id=100,
        config=SimpleNamespace(
            config_json={
                "term_key": "WI26",
                "term_from": "2026-01-05",
                "term_to": "2026-03-20",
            }
        ),
        cursor=SimpleNamespace(cursor_json={}),
        user=SimpleNamespace(timezone_name="America/Los_Angeles"),
    )
    monkeypatch.setattr("app.modules.ingestion.calendar_fetcher.decode_source_secrets", lambda _source: {"url": "https://example.com/calendar.ics"})

    class _FakeFetched:
        not_modified = False
        etag = "etag-1"
        last_modified = "Mon, 01 Jan 2026 00:00:00 GMT"

        def __init__(self, content: bytes):
            self.content = content

    class _FakeIcsClient:
        def fetch(self, url: str, source_id: int, if_none_match=None, if_modified_since=None):
            assert url == "https://example.com/calendar.ics"
            assert source_id == 100
            del if_none_match, if_modified_since
            content = b"""BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:evt-in
DTSTART:20260201T180000Z
DTEND:20260201T190000Z
SUMMARY:In term
END:VEVENT
BEGIN:VEVENT
UID:evt-out
DTSTART:20260501T180000Z
DTEND:20260501T190000Z
SUMMARY:Out of term
END:VEVENT
END:VCALENDAR
"""
            return _FakeFetched(content)

    monkeypatch.setattr("app.modules.ingestion.calendar_fetcher.ICSClient", _FakeIcsClient)

    outcome = fetch_calendar_delta(source=source)

    assert outcome.status == ConnectorResultStatus.CHANGED
    assert outcome.parse_payload is not None
    assert outcome.parse_payload["kind"] == "calendar_delta"
    changed = outcome.parse_payload["changed_components"]
    assert len(changed) == 1
    assert changed[0]["external_event_id"] == "evt-in"
