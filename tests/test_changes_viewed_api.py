from __future__ import annotations

from datetime import datetime, timezone

from app.modules.sync.types import FetchResult
from tests.helpers_inputs import create_ics_input_for_user


ICS_V1 = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Viewed Test//EN
BEGIN:VEVENT
UID:event-1
DTSTART:20260220T100000Z
DTEND:20260220T110000Z
SUMMARY:CSE 151A Homework 1
DESCRIPTION:First version
END:VEVENT
END:VCALENDAR
"""

ICS_V2 = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Viewed Test//EN
BEGIN:VEVENT
UID:event-1
DTSTART:20260220T120000Z
DTEND:20260220T130000Z
SUMMARY:CSE 151A Homework 1
DESCRIPTION:Updated version
END:VEVENT
END:VCALENDAR
"""


def test_patch_change_viewed_status(client, initialized_user, db_session, monkeypatch) -> None:
    headers = {"X-API-Key": "test-api-key"}
    source_id = create_ics_input_for_user(
        db_session,
        user_id=initialized_user["id"],
        url="https://example.com/feed.ics",
    )

    responses = [
        FetchResult(content=ICS_V1, etag="v1", fetched_at_utc=datetime(2026, 2, 19, 20, 31, 10, tzinfo=timezone.utc)),
        FetchResult(content=ICS_V2, etag="v2", fetched_at_utc=datetime(2026, 2, 19, 21, 31, 10, tzinfo=timezone.utc)),
    ]

    def fake_fetch(self, url: str, source_id: int, **kwargs):  # noqa: ARG001
        return responses.pop(0)

    monkeypatch.setattr("app.modules.sync.service.ICSClient.fetch", fake_fetch)
    first_sync = client.post(f"/v1/inputs/{source_id}/sync", headers=headers)
    second_sync = client.post(f"/v1/inputs/{source_id}/sync", headers=headers)
    assert first_sync.status_code == 200
    assert second_sync.status_code == 200
    assert first_sync.json()["is_baseline_sync"] is True
    assert second_sync.json()["is_baseline_sync"] is False

    list_response = client.get(f"/v1/inputs/{source_id}/changes", headers=headers)
    assert list_response.status_code == 200
    changes = list_response.json()
    assert len(changes) == 1
    target_change = changes[0]

    mark_read = client.patch(
        f"/v1/inputs/{source_id}/changes/{target_change['id']}/viewed",
        headers=headers,
        json={"viewed": True, "note": "reviewed in ui"},
    )
    assert mark_read.status_code == 200
    payload = mark_read.json()
    assert payload["viewed_at"] is not None
    assert payload["viewed_note"] == "reviewed in ui"

    refreshed = client.get(f"/v1/inputs/{source_id}/changes", headers=headers)
    assert refreshed.status_code == 200
    refreshed_change = refreshed.json()[0]
    assert refreshed_change["viewed_at"] is not None
    assert refreshed_change["viewed_note"] == "reviewed in ui"

    mark_unread = client.patch(
        f"/v1/inputs/{source_id}/changes/{target_change['id']}/viewed",
        headers=headers,
        json={"viewed": False},
    )
    assert mark_unread.status_code == 200
    payload = mark_unread.json()
    assert payload["viewed_at"] is None
    assert payload["viewed_note"] is None
