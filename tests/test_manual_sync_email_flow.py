from __future__ import annotations

from datetime import datetime, timezone

from app.core.config import get_settings
from app.modules.notify.interface import SendResult
from app.modules.sync.types import FetchResult


ICS_V1 = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Deadline Diff//EN
BEGIN:VEVENT
UID:event-1
DTSTART:20260224T090000Z
DTEND:20260224T100000Z
SUMMARY:CSE 151A Homework 1
DESCRIPTION:submit to portal
END:VEVENT
END:VCALENDAR
"""

ICS_V2 = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Deadline Diff//EN
BEGIN:VEVENT
UID:event-1
DTSTART:20260224T100000Z
DTEND:20260224T110000Z
SUMMARY:CSE 151A Homework 1
DESCRIPTION:submit to portal
END:VEVENT
END:VCALENDAR
"""


def test_manual_sync_sends_single_digest_per_changed_run(client, monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_NOTIFICATIONS", "true")
    monkeypatch.setenv("DEFAULT_NOTIFY_EMAIL", "notify@example.com")
    get_settings.cache_clear()

    headers = {"X-API-Key": "test-api-key"}
    create_response = client.post(
        "/v1/sources/ics",
        headers=headers,
        json={"name": "My Calendar", "url": "https://example.com/feed.ics"},
    )
    assert create_response.status_code == 201
    source_id = create_response.json()["id"]

    responses = [
        FetchResult(content=ICS_V1, etag="v1", fetched_at_utc=datetime(2026, 2, 20, 10, 0, tzinfo=timezone.utc)),
        FetchResult(content=ICS_V2, etag="v2", fetched_at_utc=datetime(2026, 2, 20, 11, 0, tzinfo=timezone.utc)),
        FetchResult(content=ICS_V2, etag="v2", fetched_at_utc=datetime(2026, 2, 20, 12, 0, tzinfo=timezone.utc)),
    ]

    def fake_fetch(self, url: str, source_id: int):  # noqa: ARG001
        if not responses:
            raise RuntimeError("No stub responses left")
        return responses.pop(0)

    send_calls: list[tuple[str, str, int, int]] = []

    def fake_send_changes_digest(self, to_email: str, source_name: str, source_id: int, items):  # noqa: ANN001
        send_calls.append((to_email, source_name, source_id, len(items)))
        return SendResult(success=True)

    monkeypatch.setattr("app.modules.sync.service.ICSClient.fetch", fake_fetch)
    monkeypatch.setattr("app.modules.notify.email.SMTPEmailNotifier.send_changes_digest", fake_send_changes_digest)

    first_sync = client.post(f"/v1/sources/{source_id}/sync", headers=headers)
    second_sync = client.post(f"/v1/sources/{source_id}/sync", headers=headers)
    third_sync = client.post(f"/v1/sources/{source_id}/sync", headers=headers)

    assert first_sync.status_code == 200
    assert second_sync.status_code == 200
    assert third_sync.status_code == 200

    first_payload = first_sync.json()
    second_payload = second_sync.json()
    third_payload = third_sync.json()

    assert first_payload["changes_created"] == 1
    assert first_payload["email_sent"] is True
    assert second_payload["changes_created"] == 1
    assert second_payload["email_sent"] is True
    assert third_payload["changes_created"] == 0
    assert third_payload["email_sent"] is False

    # Exactly one digest email per changed run, none on unchanged rerun.
    assert len(send_calls) == 2
    assert send_calls[0][0] == "notify@example.com"
    assert send_calls[0][3] == 1
    assert send_calls[1][3] == 1

    get_settings.cache_clear()
