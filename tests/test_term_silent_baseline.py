from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import Change, InputTermBaseline
from app.modules.sync.types import FetchResult


def _build_ics(dtstart: str, dtend: str) -> bytes:
    return f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Deadline Diff//EN
BEGIN:VEVENT
UID:event-1
DTSTART:{dtstart}
DTEND:{dtend}
SUMMARY:CSE 151A Homework 1
DESCRIPTION:submit to portal
END:VEVENT
END:VCALENDAR
""".encode("utf-8")


def test_term_first_change_run_is_silent_then_emits_after_baseline(client, initialized_user, db_session, monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_NOTIFICATIONS", "false")
    get_settings.cache_clear()

    headers = {"X-API-Key": "test-api-key"}
    create_term = client.post(
        "/v1/user/terms",
        headers=headers,
        json={
            "code": "WI26",
            "label": "Winter 2026",
            "starts_on": "2026-01-06",
            "ends_on": "2026-03-21",
            "is_active": True,
        },
    )
    assert create_term.status_code == 201
    term_id = create_term.json()["id"]

    create_input = client.post(
        "/v1/inputs/ics",
        headers=headers,
        json={"url": "https://example.com/term-silent.ics", "user_term_id": term_id},
    )
    assert create_input.status_code == 201
    input_id = create_input.json()["id"]

    responses = [
        FetchResult(
            content=_build_ics("20260224T090000Z", "20260224T100000Z"),
            etag="v1",
            fetched_at_utc=datetime(2026, 2, 24, 9, 0, tzinfo=timezone.utc),
        ),
        FetchResult(
            content=_build_ics("20260224T100000Z", "20260224T110000Z"),
            etag="v2",
            fetched_at_utc=datetime(2026, 2, 24, 10, 0, tzinfo=timezone.utc),
        ),
        FetchResult(
            content=_build_ics("20260224T110000Z", "20260224T120000Z"),
            etag="v3",
            fetched_at_utc=datetime(2026, 2, 24, 11, 0, tzinfo=timezone.utc),
        ),
    ]

    def fake_fetch(self, url: str, input_id: int, **kwargs):  # noqa: ANN001, ARG001
        if not responses:
            raise RuntimeError("No stub responses left")
        return responses.pop(0)

    monkeypatch.setattr("app.modules.sync.service.ICSClient.fetch", fake_fetch)

    first_sync = client.post(f"/v1/inputs/{input_id}/sync", headers=headers)
    second_sync = client.post(f"/v1/inputs/{input_id}/sync", headers=headers)
    third_sync = client.post(f"/v1/inputs/{input_id}/sync", headers=headers)

    assert first_sync.status_code == 200
    assert second_sync.status_code == 200
    assert third_sync.status_code == 200

    assert first_sync.json()["is_baseline_sync"] is True
    assert first_sync.json()["changes_created"] == 0
    assert second_sync.json()["is_baseline_sync"] is False
    assert second_sync.json()["changes_created"] == 0
    assert third_sync.json()["changes_created"] == 1

    baseline_rows = db_session.scalars(
        select(InputTermBaseline).where(InputTermBaseline.input_id == input_id, InputTermBaseline.user_term_id == term_id)
    ).all()
    assert len(baseline_rows) == 1

    changes = db_session.scalars(select(Change).where(Change.input_id == input_id).order_by(Change.id.asc())).all()
    assert len(changes) == 1
    assert changes[0].user_term_id == term_id

    feed_for_term = client.get(f"/v1/feed?term_scope=term&term_id={term_id}", headers=headers)
    assert feed_for_term.status_code == 200
    assert len(feed_for_term.json()) == 1

    get_settings.cache_clear()
