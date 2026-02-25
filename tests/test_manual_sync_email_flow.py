from __future__ import annotations

from datetime import datetime, timezone

from app.core.config import get_settings
from app.modules.inputs.schemas import InputCreateRequest
from app.modules.inputs.service import create_ics_input
from app.modules.notify.interface import SendResult
from app.modules.sync.types import FetchResult
from tests.helpers_inputs import create_ics_input_for_user


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


def test_manual_sync_sends_single_digest_per_changed_run(client, initialized_user, db_session, monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_NOTIFICATIONS", "true")
    monkeypatch.setenv("DEFAULT_NOTIFY_EMAIL", "notify@example.com")
    get_settings.cache_clear()

    headers = {"X-API-Key": "test-api-key"}
    source_id = create_ics_input_for_user(
        db_session,
        user_id=initialized_user["id"],
        url="https://example.com/feed.ics",
    )
    prefs_response = client.put(
        "/v1/notification_prefs",
        headers=headers,
        json={"digest_enabled": False},
    )
    assert prefs_response.status_code == 200

    responses = [
        FetchResult(content=ICS_V1, etag="v1", fetched_at_utc=datetime(2026, 2, 20, 10, 0, tzinfo=timezone.utc)),
        FetchResult(content=ICS_V2, etag="v2", fetched_at_utc=datetime(2026, 2, 20, 11, 0, tzinfo=timezone.utc)),
        FetchResult(content=ICS_V2, etag="v2", fetched_at_utc=datetime(2026, 2, 20, 12, 0, tzinfo=timezone.utc)),
    ]

    def fake_fetch(self, url: str, source_id: int, **kwargs):  # noqa: ARG001
        if not responses:
            raise RuntimeError("No stub responses left")
        return responses.pop(0)

    send_calls: list[tuple[str, str, int, int]] = []

    def fake_send_changes_digest(self, to_email: str, source_name: str, source_id: int, items):  # noqa: ANN001
        send_calls.append((to_email, source_name, source_id, len(items)))
        return SendResult(success=True)

    monkeypatch.setattr("app.modules.sync.service.ICSClient.fetch", fake_fetch)
    monkeypatch.setattr("app.modules.notify.email.SMTPEmailNotifier.send_changes_digest", fake_send_changes_digest)

    first_sync = client.post(f"/v1/inputs/{source_id}/sync", headers=headers)
    second_sync = client.post(f"/v1/inputs/{source_id}/sync", headers=headers)
    third_sync = client.post(f"/v1/inputs/{source_id}/sync", headers=headers)

    assert first_sync.status_code == 200
    assert second_sync.status_code == 200
    assert third_sync.status_code == 200

    first_payload = first_sync.json()
    second_payload = second_sync.json()
    third_payload = third_sync.json()

    assert first_payload["changes_created"] == 0
    assert first_payload["email_sent"] is False
    assert first_payload["is_baseline_sync"] is True
    assert second_payload["changes_created"] == 1
    assert second_payload["email_sent"] is True
    assert second_payload["is_baseline_sync"] is False
    assert third_payload["changes_created"] == 0
    assert third_payload["email_sent"] is False
    assert third_payload["is_baseline_sync"] is False

    snapshots_response = client.get(f"/v1/inputs/{source_id}/snapshots", headers=headers)
    assert snapshots_response.status_code == 200
    # third run returned identical feed, so snapshot creation is skipped.
    assert len(snapshots_response.json()) == 2

    # Baseline sync must not notify; only changed rerun sends one digest.
    assert len(send_calls) == 1
    assert send_calls[0][0] == "student@example.com"
    assert send_calls[0][3] == 1

    get_settings.cache_clear()


def test_manual_sync_prefers_user_notify_email_over_global(client, initialized_user, db_session, monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_NOTIFICATIONS", "true")
    monkeypatch.setenv("DEFAULT_NOTIFY_EMAIL", "global@example.com")
    get_settings.cache_clear()

    headers = {"X-API-Key": "test-api-key"}
    user_update_response = client.patch(
        "/v1/user",
        headers=headers,
        json={
            "notify_email": "profile-specific@example.com",
            "calendar_delay_seconds": 120,
        },
    )
    assert user_update_response.status_code == 200

    source_id = create_ics_input_for_user(
        db_session,
        user_id=initialized_user["id"],
        url="https://example.com/feed.ics",
    )
    prefs_response = client.put(
        "/v1/notification_prefs",
        headers=headers,
        json={"digest_enabled": False},
    )
    assert prefs_response.status_code == 200

    responses = [
        FetchResult(content=ICS_V1, etag="v1", fetched_at_utc=datetime(2026, 2, 20, 10, 0, tzinfo=timezone.utc)),
        FetchResult(content=ICS_V2, etag="v2", fetched_at_utc=datetime(2026, 2, 20, 11, 0, tzinfo=timezone.utc)),
    ]

    sent_to: list[str] = []

    def fake_fetch(self, url: str, source_id: int, **kwargs):  # noqa: ARG001
        return responses.pop(0)

    def fake_send_changes_digest(self, to_email: str, source_name: str, source_id: int, items):  # noqa: ANN001, ARG001
        sent_to.append(to_email)
        return SendResult(success=True)

    monkeypatch.setattr("app.modules.sync.service.ICSClient.fetch", fake_fetch)
    monkeypatch.setattr("app.modules.notify.email.SMTPEmailNotifier.send_changes_digest", fake_send_changes_digest)

    first_sync_response = client.post(f"/v1/inputs/{source_id}/sync", headers=headers)
    second_sync_response = client.post(f"/v1/inputs/{source_id}/sync", headers=headers)

    assert first_sync_response.status_code == 200
    assert second_sync_response.status_code == 200
    assert first_sync_response.json()["email_sent"] is False
    assert first_sync_response.json()["is_baseline_sync"] is True
    assert second_sync_response.json()["email_sent"] is True
    assert second_sync_response.json()["is_baseline_sync"] is False
    assert sent_to == ["profile-specific@example.com"]

    get_settings.cache_clear()


def test_identity_upsert_keeps_history_and_baseline(client, initialized_user, db_session, monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_NOTIFICATIONS", "false")
    get_settings.cache_clear()

    headers = {"X-API-Key": "test-api-key"}
    first_create = create_ics_input(
        db_session,
        user_id=initialized_user["id"],
        payload=InputCreateRequest(url="https://example.com/feed-v1.ics"),
    )
    assert first_create.upserted_existing is False
    source_id = first_create.input.id

    responses = [
        FetchResult(content=ICS_V1, etag="v1", fetched_at_utc=datetime(2026, 2, 20, 10, 0, tzinfo=timezone.utc)),
        FetchResult(content=ICS_V2, etag="v2", fetched_at_utc=datetime(2026, 2, 20, 11, 0, tzinfo=timezone.utc)),
        FetchResult(content=ICS_V2, etag="v2", fetched_at_utc=datetime(2026, 2, 20, 12, 0, tzinfo=timezone.utc)),
        FetchResult(content=ICS_V2, etag="v2", fetched_at_utc=datetime(2026, 2, 20, 13, 0, tzinfo=timezone.utc)),
    ]

    def fake_fetch(self, url: str, source_id: int, **kwargs):  # noqa: ARG001
        if not responses:
            raise RuntimeError("No stub responses left")
        return responses.pop(0)

    monkeypatch.setattr("app.modules.sync.service.ICSClient.fetch", fake_fetch)

    first_sync = client.post(f"/v1/inputs/{source_id}/sync", headers=headers)
    second_sync = client.post(f"/v1/inputs/{source_id}/sync", headers=headers)
    assert first_sync.status_code == 200
    assert second_sync.status_code == 200
    assert first_sync.json()["is_baseline_sync"] is True
    assert second_sync.json()["changes_created"] == 1

    before_replace_changes = client.get(f"/v1/inputs/{source_id}/changes", headers=headers)
    assert before_replace_changes.status_code == 200
    assert len(before_replace_changes.json()) == 1

    upserted = create_ics_input(
        db_session,
        user_id=initialized_user["id"],
        payload=InputCreateRequest(url="https://example.com/feed-v1.ics"),
    )
    assert upserted.upserted_existing is True
    assert upserted.input.id == source_id
    assert upserted.input.interval_minutes == 15

    after_upsert_changes = client.get(f"/v1/inputs/{source_id}/changes", headers=headers)
    assert after_upsert_changes.status_code == 200
    assert len(after_upsert_changes.json()) == 1

    sync_after_upsert = client.post(f"/v1/inputs/{source_id}/sync", headers=headers)
    assert sync_after_upsert.status_code == 200
    assert sync_after_upsert.json()["is_baseline_sync"] is False
    assert sync_after_upsert.json()["changes_created"] == 0

    get_settings.cache_clear()
