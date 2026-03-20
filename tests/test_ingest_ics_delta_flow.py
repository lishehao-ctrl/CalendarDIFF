from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from app.db.models.runtime import ConnectorResultStatus
from app.modules.runtime.connectors import calendar_fetcher
from app.modules.runtime.connectors.clients.types import FetchResult


def _source(*, cursor_json: dict) -> SimpleNamespace:
    return SimpleNamespace(
        id=101,
        cursor=SimpleNamespace(cursor_json=cursor_json),
    )


def _ics_content(summary: str) -> bytes:
    return (
        "BEGIN:VCALENDAR\n"
        "VERSION:2.0\n"
        "BEGIN:VEVENT\n"
        "UID:evt-1\n"
        "DTSTART:20260301T100000Z\n"
        "DTEND:20260301T110000Z\n"
        f"SUMMARY:{summary}\n"
        "END:VEVENT\n"
        "END:VCALENDAR\n"
    ).encode("utf-8")


def test_calendar_fetch_not_modified_returns_no_change(monkeypatch) -> None:
    monkeypatch.setattr(calendar_fetcher, "decode_source_secrets", lambda _source: {"url": "https://example.com/test.ics"})

    class _FakeICSClient:
        def fetch(self, url, source_id, if_none_match=None, if_modified_since=None):  # noqa: ANN001, D401
            del url, source_id, if_none_match, if_modified_since
            return FetchResult(
                content=None,
                etag="etag-mainline",
                last_modified="Tue, 03 Mar 2026 12:00:00 GMT",
                status_code=304,
                not_modified=True,
                fetched_at_utc=datetime.now(timezone.utc),
            )

    monkeypatch.setattr(calendar_fetcher, "ICSClient", _FakeICSClient)
    outcome = calendar_fetcher.fetch_calendar_delta(source=_source(cursor_json={}))

    assert outcome.status == ConnectorResultStatus.NO_CHANGE
    assert outcome.parse_payload is None
    assert outcome.error_code is None
    assert outcome.error_message is None
    assert outcome.cursor_patch["etag"] == "etag-mainline"
    assert outcome.cursor_patch["ics_delta_components_total"] == 0


def test_calendar_fetch_changed_returns_calendar_delta_payload(monkeypatch) -> None:
    monkeypatch.setattr(calendar_fetcher, "decode_source_secrets", lambda _source: {"url": "https://example.com/test.ics"})

    class _FakeICSClient:
        def fetch(self, url, source_id, if_none_match=None, if_modified_since=None):  # noqa: ANN001, D401
            del url, source_id, if_none_match, if_modified_since
            return FetchResult(
                content=_ics_content("Homework Updated"),
                etag="etag-v3",
                last_modified="Tue, 03 Mar 2026 13:00:00 GMT",
                status_code=200,
                not_modified=False,
                fetched_at_utc=datetime.now(timezone.utc),
            )

    monkeypatch.setattr(calendar_fetcher, "ICSClient", _FakeICSClient)
    outcome = calendar_fetcher.fetch_calendar_delta(source=_source(cursor_json={}))

    assert outcome.status == ConnectorResultStatus.CHANGED
    assert outcome.error_code is None
    assert outcome.error_message is None
    assert outcome.parse_payload is not None
    assert outcome.parse_payload["kind"] == "calendar_delta"
    assert isinstance(outcome.parse_payload["changed_components"], list)
    assert outcome.parse_payload["changed_components"]
    assert outcome.parse_payload["removed_component_keys"] == []
    assert "ics_component_fingerprints" in outcome.cursor_patch
    assert outcome.cursor_patch["ics_delta_changed_components"] >= 1


def test_calendar_fetch_malformed_content_fails_closed(monkeypatch) -> None:
    monkeypatch.setattr(calendar_fetcher, "decode_source_secrets", lambda _source: {"url": "https://example.com/test.ics"})

    class _FakeICSClient:
        def fetch(self, url, source_id, if_none_match=None, if_modified_since=None):  # noqa: ANN001, D401
            del url, source_id, if_none_match, if_modified_since
            return FetchResult(
                content=b"BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:x\nSUMMARY:oops\n",
                etag="etag-bad",
                last_modified="Tue, 03 Mar 2026 14:00:00 GMT",
                status_code=200,
                not_modified=False,
                fetched_at_utc=datetime.now(timezone.utc),
            )

    monkeypatch.setattr(calendar_fetcher, "ICSClient", _FakeICSClient)
    outcome = calendar_fetcher.fetch_calendar_delta(source=_source(cursor_json={}))

    assert outcome.status == ConnectorResultStatus.PARSE_FAILED
    assert outcome.parse_payload is None
    assert outcome.error_code == "calendar_delta_parse_failed"
    assert isinstance(outcome.error_message, str) and outcome.error_message
