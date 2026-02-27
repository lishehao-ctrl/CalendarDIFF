from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Change, ChangeType, Snapshot, Input, InputType, User
from app.modules.inputs.schemas import InputCreateRequest
from app.modules.inputs.service import create_ics_input
from app.modules.sync.types import FetchResult


ICS_V1 = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Evidence Preview Test//EN
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
PRODID:-//Evidence Preview Test//EN
BEGIN:VEVENT
UID:event-1
DTSTART:20260220T120000Z
DTEND:20260220T130000Z
SUMMARY:CSE 151A Homework 1
DESCRIPTION:Updated version
END:VEVENT
END:VCALENDAR
"""


def _create_ics_input(db_session: Session, *, user_id: int, url: str) -> int:
    created = create_ics_input(
        db_session,
        user_id=user_id,
        payload=InputCreateRequest(url=url),
    )
    return created.input.id


def test_preview_change_evidence_before_and_after_success(client, initialized_user, db_session: Session, monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EVIDENCE_DIR", "./evidence")
    monkeypatch.setenv("ENABLE_NOTIFICATIONS", "false")
    get_settings.cache_clear()

    headers = {"X-API-Key": "test-api-key"}
    input_id = _create_ics_input(db_session, user_id=initialized_user["id"], url="https://example.com/calendar-preview.ics")

    responses = [
        FetchResult(content=ICS_V1, etag="v1", fetched_at_utc=datetime(2026, 2, 19, 20, 31, 10, tzinfo=timezone.utc)),
        FetchResult(content=ICS_V2, etag="v2", fetched_at_utc=datetime(2026, 2, 19, 21, 31, 10, tzinfo=timezone.utc)),
    ]

    def fake_fetch(self, url: str, source_id: int, **kwargs):  # noqa: ARG001
        return responses.pop(0)

    monkeypatch.setattr("app.modules.sync.service.ICSClient.fetch", fake_fetch)

    first_sync = client.post(f"/v1/inputs/{input_id}/sync", headers=headers)
    second_sync = client.post(f"/v1/inputs/{input_id}/sync", headers=headers)
    assert first_sync.status_code == 200
    assert second_sync.status_code == 200

    changes_response = client.get(f"/v1/feed?input_id={input_id}", headers=headers)
    assert changes_response.status_code == 200
    changes = changes_response.json()
    assert len(changes) == 1
    change_id = changes[0]["id"]

    before_preview = client.get(f"/v1/changes/{change_id}/evidence/before/preview", headers=headers)
    assert before_preview.status_code == 200
    before_payload = before_preview.json()
    assert before_payload["side"] == "before"
    assert before_payload["content_type"] == "text/calendar"
    assert before_payload["truncated"] is False
    assert before_payload["event_count"] == 1
    assert before_payload["events"][0]["uid"] == "event-1"
    assert before_payload["events"][0]["dtstart"] == "20260220T100000Z"

    after_preview = client.get(f"/v1/changes/{change_id}/evidence/after/preview", headers=headers)
    assert after_preview.status_code == 200
    after_payload = after_preview.json()
    assert after_payload["side"] == "after"
    assert after_payload["content_type"] == "text/calendar"
    assert after_payload["truncated"] is False
    assert after_payload["event_count"] == 1
    assert after_payload["events"][0]["uid"] == "event-1"
    assert after_payload["events"][0]["dtstart"] == "20260220T120000Z"

    get_settings.cache_clear()


def test_preview_change_evidence_before_missing_returns_404(client, db_session: Session) -> None:
    user = User(
        email="owner@example.com",
        notify_email="student@example.com",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.flush()

    input_row = Input(
        user_id=user.id,
        type=InputType.ICS,
        identity_key="Preview Missing Before",
        encrypted_url="encrypted",
        interval_minutes=15,
        is_active=True,
    )
    db_session.add(input_row)
    db_session.flush()

    after_snapshot = Snapshot(
        input_id=input_row.id,
        content_hash="hash-after",
        event_count=1,
        raw_evidence_key={"kind": "ics", "store": "fs", "path": "evidence/ics/source_1/after.ics"},
    )
    db_session.add(after_snapshot)
    db_session.flush()

    change = Change(
        input_id=input_row.id,
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
    response = client.get(f"/v1/changes/{change.id}/evidence/before/preview", headers=headers)
    assert response.status_code == 404
    assert response.json()["detail"] == "Evidence file not found"


def test_preview_change_evidence_path_traversal_returns_404(client, db_session: Session, monkeypatch, tmp_path) -> None:
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

    input_row = Input(
        user_id=user.id,
        type=InputType.ICS,
        identity_key="Preview Traversal",
        encrypted_url="encrypted",
        interval_minutes=15,
        is_active=True,
    )
    db_session.add(input_row)
    db_session.flush()

    after_snapshot = Snapshot(
        input_id=input_row.id,
        content_hash="hash-after",
        event_count=1,
        raw_evidence_key={"kind": "ics", "store": "fs", "path": "../outside.ics"},
    )
    db_session.add(after_snapshot)
    db_session.flush()

    change = Change(
        input_id=input_row.id,
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
    response = client.get(f"/v1/changes/{change.id}/evidence/after/preview", headers=headers)
    assert response.status_code == 404
    assert response.json()["detail"] == "Evidence file not found"

    get_settings.cache_clear()


def test_preview_change_evidence_truncated_flag(client, initialized_user, db_session: Session, monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EVIDENCE_DIR", "./evidence")
    monkeypatch.setenv("ENABLE_NOTIFICATIONS", "false")
    get_settings.cache_clear()

    large_description = "A" * 70000
    large_ics = (
        "BEGIN:VCALENDAR\n"
        "VERSION:2.0\n"
        "PRODID:-//Evidence Preview Test//EN\n"
        "BEGIN:VEVENT\n"
        "UID:event-1\n"
        "DTSTART:20260220T140000Z\n"
        "DTEND:20260220T150000Z\n"
        "SUMMARY:CSE 151A Homework 1\n"
        f"DESCRIPTION:{large_description}\n"
        "END:VEVENT\n"
        "END:VCALENDAR\n"
    ).encode("utf-8")

    headers = {"X-API-Key": "test-api-key"}
    input_id = _create_ics_input(db_session, user_id=initialized_user["id"], url="https://example.com/calendar-preview-large.ics")

    responses = [
        FetchResult(content=ICS_V1, etag="v1", fetched_at_utc=datetime(2026, 2, 19, 20, 31, 10, tzinfo=timezone.utc)),
        FetchResult(content=large_ics, etag="v3", fetched_at_utc=datetime(2026, 2, 19, 21, 31, 10, tzinfo=timezone.utc)),
    ]

    def fake_fetch(self, url: str, source_id: int, **kwargs):  # noqa: ARG001
        return responses.pop(0)

    monkeypatch.setattr("app.modules.sync.service.ICSClient.fetch", fake_fetch)

    first_sync = client.post(f"/v1/inputs/{input_id}/sync", headers=headers)
    second_sync = client.post(f"/v1/inputs/{input_id}/sync", headers=headers)
    assert first_sync.status_code == 200
    assert second_sync.status_code == 200

    changes_response = client.get(f"/v1/feed?input_id={input_id}", headers=headers)
    assert changes_response.status_code == 200
    changes = changes_response.json()
    assert len(changes) == 1
    change_id = changes[0]["id"]

    response = client.get(f"/v1/changes/{change_id}/evidence/after/preview", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["truncated"] is True
    assert payload["event_count"] == 1
    assert payload["events"][0]["uid"] == "event-1"
    description = payload["events"][0]["description"]
    assert isinstance(description, str)
    assert len(description) <= 243

    get_settings.cache_clear()


def test_preview_change_evidence_parse_failure_returns_422(client, db_session: Session, monkeypatch, tmp_path) -> None:
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

    input_row = Input(
        user_id=user.id,
        type=InputType.ICS,
        identity_key="ics-parse-failure",
        encrypted_url="encrypted",
        interval_minutes=15,
        is_active=True,
    )
    db_session.add(input_row)
    db_session.flush()

    evidence_dir = tmp_path / "evidence" / "ics" / "source_1"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    broken_path = evidence_dir / "broken.ics"
    broken_path.write_text("NOT A VCALENDAR", encoding="utf-8")

    after_snapshot = Snapshot(
        input_id=input_row.id,
        content_hash="hash-broken",
        event_count=1,
        raw_evidence_key={"kind": "ics", "store": "fs", "path": str(broken_path.relative_to(tmp_path))},
    )
    db_session.add(after_snapshot)
    db_session.flush()

    change = Change(
        input_id=input_row.id,
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
    response = client.get(f"/v1/changes/{change.id}/evidence/after/preview", headers=headers)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "evidence_parse_failed"
    assert detail["message"] == "Failed to parse ICS evidence preview"

    get_settings.cache_clear()
