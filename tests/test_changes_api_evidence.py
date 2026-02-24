from __future__ import annotations

from datetime import datetime, timezone

from app.core.config import get_settings
from app.modules.sync.types import FetchResult


ICS_V1 = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//API Audit Test//EN
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
PRODID:-//API Audit Test//EN
BEGIN:VEVENT
UID:event-1
DTSTART:20260220T120000Z
DTEND:20260220T130000Z
SUMMARY:CSE 151A Homework 1
DESCRIPTION:Updated version
END:VEVENT
END:VCALENDAR
"""


def test_changes_and_snapshots_endpoints_include_evidence(client, initialized_user, monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EVIDENCE_DIR", "./evidence")
    monkeypatch.setenv("ENABLE_NOTIFICATIONS", "false")
    get_settings.cache_clear()

    headers = {"X-API-Key": "test-api-key"}
    create_response = client.post(
        "/v1/inputs/ics",
        headers=headers,
        json={"url": "https://example.com/calendar.ics"},
    )
    assert create_response.status_code == 201
    source_id = create_response.json()["id"]

    responses = [
        FetchResult(content=ICS_V1, etag="v1", fetched_at_utc=datetime(2026, 2, 19, 20, 31, 10, tzinfo=timezone.utc)),
        FetchResult(content=ICS_V2, etag="v2", fetched_at_utc=datetime(2026, 2, 19, 21, 31, 10, tzinfo=timezone.utc)),
    ]

    def fake_fetch(self, url: str, source_id: int, **kwargs):  # noqa: ARG001
        if not responses:
            raise RuntimeError("No stub responses left")
        return responses.pop(0)

    monkeypatch.setattr("app.modules.sync.service.ICSClient.fetch", fake_fetch)

    first_sync = client.post(f"/v1/inputs/{source_id}/sync", headers=headers)
    assert first_sync.status_code == 200
    assert first_sync.json()["is_baseline_sync"] is True
    second_sync = client.post(f"/v1/inputs/{source_id}/sync", headers=headers)
    assert second_sync.status_code == 200
    assert second_sync.json()["is_baseline_sync"] is False

    changes_response = client.get(f"/v1/inputs/{source_id}/changes", headers=headers)
    assert changes_response.status_code == 200
    changes = changes_response.json()
    assert len(changes) == 1

    due_change = next(change for change in changes if change["change_type"] == "due_changed")
    assert due_change["before_snapshot_id"] is not None
    assert due_change["after_snapshot_id"] is not None
    assert due_change["evidence_keys"]["after"]["kind"] == "ics"
    assert due_change["after_raw_evidence_key"]["store"] == "fs"

    snapshots_response = client.get(f"/v1/inputs/{source_id}/snapshots", headers=headers)
    assert snapshots_response.status_code == 200
    snapshots = snapshots_response.json()
    assert len(snapshots) == 2
    assert snapshots[0]["raw_evidence_key"]["kind"] == "ics"

    get_settings.cache_clear()
