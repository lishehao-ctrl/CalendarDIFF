from __future__ import annotations

from datetime import datetime, timezone

from app.modules.sync.types import FetchResult


SAMPLE_ICS = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Deadline Diff//EN
BEGIN:VEVENT
UID:cse-hw-1
DTSTART:20260224T090000Z
DTEND:20260224T100000Z
SUMMARY:CSE 151A Homework 1
DESCRIPTION:submit to portal
END:VEVENT
BEGIN:VEVENT
UID:math-project
DTSTART:20260226T090000Z
DTEND:20260226T100000Z
SUMMARY:MATH 20A Project Milestone
DESCRIPTION:proposal checkpoint
END:VEVENT
END:VCALENDAR
"""


def test_source_deadlines_endpoint_returns_grouped_output(client, monkeypatch) -> None:
    headers = {"X-API-Key": "test-api-key"}

    create_response = client.post(
        "/v1/inputs/ics",
        headers=headers,
        json={"url": "https://example.com/calendar.ics"},
    )
    assert create_response.status_code == 201
    source_id = create_response.json()["id"]

    def fake_fetch(self, url: str, source_id: int, **kwargs):
        return FetchResult(
            content=SAMPLE_ICS,
            etag=None,
            fetched_at_utc=datetime(2026, 2, 20, 12, 0, tzinfo=timezone.utc),
        )

    monkeypatch.setattr("app.modules.inputs.service.ICSClient.fetch", fake_fetch)

    response = client.get(f"/v1/inputs/{source_id}/deadlines", headers=headers)
    assert response.status_code == 200

    payload = response.json()
    assert payload["input_id"] == source_id
    assert payload["input_label"].startswith("Calendar")
    assert payload["total_deadlines"] == 2

    course_names = {item["course_label"] for item in payload["courses"]}
    assert course_names == {"CSE 151A", "MATH 20A"}

    all_types = {ddl["ddl_type"] for course in payload["courses"] for ddl in course["deadlines"]}
    assert all_types == {"assignment", "project"}
