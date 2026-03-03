from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from app.db.models import ConnectorResultStatus
from app.modules.ingestion import connector_runtime
from app.modules.sync.types import FetchResult


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
    monkeypatch.setattr(connector_runtime, "decode_source_secrets", lambda _source: {"url": "https://example.com/test.ics"})

    class _FakeICSClient:
        def fetch(self, url, input_id, if_none_match=None, if_modified_since=None):  # noqa: ANN001, D401
            del url, input_id, if_none_match, if_modified_since
            return FetchResult(
                content=None,
                etag="etag-v2",
                last_modified="Tue, 03 Mar 2026 12:00:00 GMT",
                status_code=304,
                not_modified=True,
                fetched_at_utc=datetime.now(timezone.utc),
            )

    monkeypatch.setattr(connector_runtime, "ICSClient", _FakeICSClient)
    status, cursor_patch, parse_payload, error_code, error_message = connector_runtime._run_calendar_connector_fetch_only(
        source=_source(cursor_json={}),
    )

    assert status == ConnectorResultStatus.NO_CHANGE
    assert parse_payload is None
    assert error_code is None
    assert error_message is None
    assert cursor_patch["etag"] == "etag-v2"
    assert cursor_patch["ics_delta_components_total"] == 0


def test_calendar_fetch_changed_returns_calendar_delta_payload(monkeypatch) -> None:
    monkeypatch.setattr(connector_runtime, "decode_source_secrets", lambda _source: {"url": "https://example.com/test.ics"})

    class _FakeICSClient:
        def fetch(self, url, input_id, if_none_match=None, if_modified_since=None):  # noqa: ANN001, D401
            del url, input_id, if_none_match, if_modified_since
            return FetchResult(
                content=_ics_content("Homework Updated"),
                etag="etag-v3",
                last_modified="Tue, 03 Mar 2026 13:00:00 GMT",
                status_code=200,
                not_modified=False,
                fetched_at_utc=datetime.now(timezone.utc),
            )

    monkeypatch.setattr(connector_runtime, "ICSClient", _FakeICSClient)
    status, cursor_patch, parse_payload, error_code, error_message = connector_runtime._run_calendar_connector_fetch_only(
        source=_source(cursor_json={}),
    )

    assert status == ConnectorResultStatus.CHANGED
    assert error_code is None
    assert error_message is None
    assert parse_payload is not None
    assert parse_payload["kind"] == "calendar_delta_v1"
    assert isinstance(parse_payload["changed_components"], list)
    assert parse_payload["changed_components"]
    assert parse_payload["removed_component_keys"] == []
    assert "ics_component_fingerprints_v1" in cursor_patch
    assert cursor_patch["ics_delta_changed_components"] >= 1


def test_calendar_fetch_malformed_content_fails_closed(monkeypatch) -> None:
    monkeypatch.setattr(connector_runtime, "decode_source_secrets", lambda _source: {"url": "https://example.com/test.ics"})

    class _FakeICSClient:
        def fetch(self, url, input_id, if_none_match=None, if_modified_since=None):  # noqa: ANN001, D401
            del url, input_id, if_none_match, if_modified_since
            return FetchResult(
                content=b"BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:x\nSUMMARY:oops\n",
                etag="etag-bad",
                last_modified="Tue, 03 Mar 2026 14:00:00 GMT",
                status_code=200,
                not_modified=False,
                fetched_at_utc=datetime.now(timezone.utc),
            )

    monkeypatch.setattr(connector_runtime, "ICSClient", _FakeICSClient)
    status, _cursor_patch, parse_payload, error_code, error_message = connector_runtime._run_calendar_connector_fetch_only(
        source=_source(cursor_json={}),
    )

    assert status == ConnectorResultStatus.PARSE_FAILED
    assert parse_payload is None
    assert error_code == "calendar_delta_parse_failed"
    assert isinstance(error_message, str) and error_message
