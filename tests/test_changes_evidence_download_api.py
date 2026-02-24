from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Change, ChangeType, Snapshot, Source, SourceType, User
from app.modules.sync.types import FetchResult


ICS_V1 = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Evidence Download Test//EN
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
PRODID:-//Evidence Download Test//EN
BEGIN:VEVENT
UID:event-1
DTSTART:20260220T120000Z
DTEND:20260220T130000Z
SUMMARY:CSE 151A Homework 1
DESCRIPTION:Updated version
END:VEVENT
END:VCALENDAR
"""


def test_download_change_evidence_before_and_after_success(client, initialized_user, monkeypatch, tmp_path) -> None:
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
        return responses.pop(0)

    monkeypatch.setattr("app.modules.sync.service.ICSClient.fetch", fake_fetch)

    first_sync = client.post(f"/v1/inputs/{source_id}/sync", headers=headers)
    second_sync = client.post(f"/v1/inputs/{source_id}/sync", headers=headers)
    assert first_sync.status_code == 200
    assert second_sync.status_code == 200

    changes = client.get(f"/v1/inputs/{source_id}/changes", headers=headers).json()
    assert len(changes) == 1
    change_id = changes[0]["id"]

    before_download = client.get(
        f"/v1/inputs/{source_id}/changes/{change_id}/evidence/before/download",
        headers=headers,
    )
    assert before_download.status_code == 200
    assert "text/calendar" in before_download.headers["content-type"]
    assert "attachment;" in before_download.headers["content-disposition"]
    assert before_download.content == ICS_V1

    after_download = client.get(
        f"/v1/inputs/{source_id}/changes/{change_id}/evidence/after/download",
        headers=headers,
    )
    assert after_download.status_code == 200
    assert "text/calendar" in after_download.headers["content-type"]
    assert "attachment;" in after_download.headers["content-disposition"]
    assert after_download.content == ICS_V2

    get_settings.cache_clear()


def test_download_change_evidence_before_missing_returns_404(client, db_session: Session) -> None:
    user = User(
        email="owner@example.com",
        notify_email="student@example.com",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.flush()

    source = Source(
        user_id=user.id,
        type=SourceType.ICS,
        name="Before Missing",
        normalized_name="before missing",
        encrypted_url="encrypted",
        interval_minutes=15,
        is_active=True,
    )
    db_session.add(source)
    db_session.flush()

    after_snapshot = Snapshot(
        input_id=source.id,
        content_hash="hash-after",
        event_count=1,
        raw_evidence_key={"kind": "ics", "store": "fs", "path": "evidence/ics/source_1/after.ics"},
    )
    db_session.add(after_snapshot)
    db_session.flush()

    change = Change(
        input_id=source.id,
        event_uid="event-1",
        change_type=ChangeType.DUE_CHANGED,
        detected_at=datetime.now(timezone.utc),
        before_json={"title": "A"},
        after_json={"title": "A"},
        delta_seconds=3600,
        before_snapshot_id=None,
        after_snapshot_id=after_snapshot.id,
    )
    db_session.add(change)
    db_session.commit()

    headers = {"X-API-Key": "test-api-key"}
    response = client.get(f"/v1/inputs/{source.id}/changes/{change.id}/evidence/before/download", headers=headers)
    assert response.status_code == 404
    assert response.json()["detail"] == "Evidence file not found"


def test_download_change_evidence_missing_file_returns_404(client, db_session: Session) -> None:
    user = User(
        email="owner@example.com",
        notify_email="student@example.com",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.flush()

    source = Source(
        user_id=user.id,
        type=SourceType.ICS,
        name="Missing File",
        normalized_name="missing file",
        encrypted_url="encrypted",
        interval_minutes=15,
        is_active=True,
    )
    db_session.add(source)
    db_session.flush()

    after_snapshot = Snapshot(
        input_id=source.id,
        content_hash="hash-after",
        event_count=1,
        raw_evidence_key={"kind": "ics", "store": "fs", "path": "evidence/ics/source_1/not-exist.ics"},
    )
    db_session.add(after_snapshot)
    db_session.flush()

    change = Change(
        input_id=source.id,
        event_uid="event-1",
        change_type=ChangeType.DUE_CHANGED,
        detected_at=datetime.now(timezone.utc),
        before_json={"title": "A"},
        after_json={"title": "A"},
        delta_seconds=3600,
        before_snapshot_id=None,
        after_snapshot_id=after_snapshot.id,
    )
    db_session.add(change)
    db_session.commit()

    headers = {"X-API-Key": "test-api-key"}
    response = client.get(f"/v1/inputs/{source.id}/changes/{change.id}/evidence/after/download", headers=headers)
    assert response.status_code == 404
    assert response.json()["detail"] == "Evidence file not found"


def test_download_change_evidence_path_traversal_returns_404(client, db_session: Session, monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EVIDENCE_DIR", "./evidence")
    get_settings.cache_clear()

    user = User(
        email="owner@example.com",
        notify_email="student@example.com",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.flush()

    source = Source(
        user_id=user.id,
        type=SourceType.ICS,
        name="Traversal",
        normalized_name="traversal",
        encrypted_url="encrypted",
        interval_minutes=15,
        is_active=True,
    )
    db_session.add(source)
    db_session.flush()

    after_snapshot = Snapshot(
        input_id=source.id,
        content_hash="hash-after",
        event_count=1,
        raw_evidence_key={"kind": "ics", "store": "fs", "path": "../outside.ics"},
    )
    db_session.add(after_snapshot)
    db_session.flush()

    change = Change(
        input_id=source.id,
        event_uid="event-1",
        change_type=ChangeType.DUE_CHANGED,
        detected_at=datetime.now(timezone.utc),
        before_json={"title": "A"},
        after_json={"title": "A"},
        delta_seconds=3600,
        before_snapshot_id=None,
        after_snapshot_id=after_snapshot.id,
    )
    db_session.add(change)
    db_session.commit()

    headers = {"X-API-Key": "test-api-key"}
    response = client.get(f"/v1/inputs/{source.id}/changes/{change.id}/evidence/after/download", headers=headers)
    assert response.status_code == 404
    assert response.json()["detail"] == "Evidence file not found"

    get_settings.cache_clear()
