from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.modules.sync.ics_client import ICSClient


def test_fetch_sends_conditional_headers_and_handles_304(monkeypatch) -> None:
    captured_headers: list[dict[str, str]] = []
    response = httpx.Response(
        status_code=304,
        headers={"etag": "etag-v2", "last-modified": "Wed, 19 Feb 2026 20:31:10 GMT"},
        request=httpx.Request("GET", "https://example.com/calendar.ics"),
    )

    class FakeClient:
        def __init__(self, *args, **kwargs):  # noqa: D401, ANN003
            """minimal httpx.Client replacement for deterministic tests."""

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
            return False

        def get(self, url: str, headers: dict[str, str] | None = None):
            assert url == "https://example.com/calendar.ics"
            captured_headers.append(headers or {})
            return response

    monkeypatch.setattr("app.modules.sync.ics_client.httpx.Client", FakeClient)

    client = ICSClient()
    result = client.fetch(
        "https://example.com/calendar.ics",
        input_id=1,
        if_none_match="etag-v1",
        if_modified_since="Tue, 18 Feb 2026 20:31:10 GMT",
    )

    assert captured_headers == [
        {
            "If-None-Match": "etag-v1",
            "If-Modified-Since": "Tue, 18 Feb 2026 20:31:10 GMT",
        }
    ]
    assert result.not_modified is True
    assert result.status_code == 304
    assert result.content is None
    assert result.etag == "etag-v2"
    assert result.last_modified == "Wed, 19 Feb 2026 20:31:10 GMT"
    assert isinstance(result.fetched_at_utc, datetime)
    assert result.fetched_at_utc.tzinfo == timezone.utc


def test_fetch_returns_content_for_200(monkeypatch) -> None:
    captured_headers: list[dict[str, str] | None] = []
    response = httpx.Response(
        status_code=200,
        headers={"etag": "etag-v1", "last-modified": "Wed, 19 Feb 2026 20:31:10 GMT"},
        content=b"BEGIN:VCALENDAR\nEND:VCALENDAR\n",
        request=httpx.Request("GET", "https://example.com/calendar.ics"),
    )

    class FakeClient:
        def __init__(self, *args, **kwargs):  # noqa: ANN003
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
            return False

        def get(self, url: str, headers: dict[str, str] | None = None):
            assert url == "https://example.com/calendar.ics"
            captured_headers.append(headers)
            return response

    monkeypatch.setattr("app.modules.sync.ics_client.httpx.Client", FakeClient)

    client = ICSClient()
    result = client.fetch("https://example.com/calendar.ics", input_id=2)

    assert captured_headers == [None]
    assert result.not_modified is False
    assert result.status_code == 200
    assert result.content == b"BEGIN:VCALENDAR\nEND:VCALENDAR\n"
    assert result.etag == "etag-v1"
    assert result.last_modified == "Wed, 19 Feb 2026 20:31:10 GMT"
