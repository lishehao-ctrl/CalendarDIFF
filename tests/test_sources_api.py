from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db.models import Source, SourceType, SyncRun, SyncRunStatus, SyncTriggerType, User


def test_sources_api_requires_api_key(client) -> None:
    response = client.post(
        "/v1/inputs/ics",
        json={"url": "https://example.com/feed.ics"},
    )
    assert response.status_code == 401


def test_create_input_rejects_legacy_name_field(client, initialized_user) -> None:
    headers = {"X-API-Key": "test-api-key"}

    no_name_required = client.post(
        "/v1/inputs/ics",
        headers=headers,
        json={"url": "https://example.com/feed.ics"},
    )
    assert no_name_required.status_code == 201

    legacy_name = client.post(
        "/v1/inputs/ics",
        headers=headers,
        json={"name": "   ", "url": "https://example.com/feed.ics"},
    )
    assert legacy_name.status_code == 422


def test_create_and_list_sources_hides_url(client, initialized_user) -> None:
    headers = {"X-API-Key": "test-api-key"}

    create_response = client.post(
        "/v1/inputs/ics",
        headers=headers,
        json={
            "url": "https://example.com/feed.ics",
        },
    )
    assert create_response.status_code == 201
    payload = create_response.json()

    assert payload["display_label"].startswith("Calendar")
    assert payload["interval_minutes"] == 15
    assert payload["notify_email"] is None
    assert payload["upserted_existing"] is False
    assert "url" not in payload
    assert "encrypted_url" not in payload

    list_response = client.get("/v1/inputs", headers=headers)
    assert list_response.status_code == 200

    items = list_response.json()
    assert len(items) == 1
    assert items[0]["notify_email"] is None
    assert items[0]["provider"] is None
    assert items[0]["gmail_label"] is None
    assert items[0]["gmail_from_contains"] is None
    assert items[0]["gmail_subject_keywords"] is None
    assert items[0]["gmail_account_email"] is None
    assert "upserted_existing" not in items[0]
    assert "url" not in items[0]
    assert "encrypted_url" not in items[0]


def test_duplicate_identity_upserts_source_in_place(client, initialized_user) -> None:
    headers = {"X-API-Key": "test-api-key"}

    first = client.post(
        "/v1/inputs/ics",
        headers=headers,
        json={"url": "https://example.com/feed.ics"},
    )
    assert first.status_code == 201
    first_payload = first.json()
    assert first_payload["upserted_existing"] is False

    second = client.post(
        "/v1/inputs/ics",
        headers=headers,
        json={
            "url": "https://example.com/feed.ics",
        },
    )
    assert second.status_code == 200
    second_payload = second.json()
    assert second_payload["upserted_existing"] is True
    assert second_payload["id"] == first_payload["id"]
    assert second_payload["notify_email"] is None
    assert second_payload["interval_minutes"] == 15

    list_response = client.get("/v1/inputs", headers=headers)
    assert list_response.status_code == 200
    items = list_response.json()
    assert len(items) == 1
    assert items[0]["id"] == first_payload["id"]


def test_list_sources_includes_runtime_state_fields(client, db_session) -> None:
    user = User(email="owner@example.com")
    db_session.add(user)
    db_session.flush()

    source = Source(
        user_id=user.id,
        type=SourceType.ICS,
        identity_key="ics-observed",
        encrypted_url="encrypted-source",
        interval_minutes=15,
        is_active=True,
        last_checked_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        last_ok_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    db_session.add(source)
    db_session.flush()
    db_session.add(
        SyncRun(
            input_id=source.id,
            trigger_type=SyncTriggerType.SCHEDULER,
            started_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            finished_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            status=SyncRunStatus.NO_CHANGE,
            changes_count=0,
            duration_ms=120,
        )
    )
    db_session.commit()

    response = client.get("/v1/inputs", headers={"X-API-Key": "test-api-key"})
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    row = payload[0]

    assert row["last_ok_at"] is not None
    assert row["last_change_detected_at"] is None
    assert row["last_error_at"] is None
    assert row["next_check_at"] is not None
    assert row["last_result"] == "NO_CHANGE"


def test_list_sources_applies_scheduler_lock_skipped_cooldown_to_next_check(client, db_session) -> None:
    now = datetime.now(timezone.utc)
    user = User(email="owner@example.com")
    db_session.add(user)
    db_session.flush()

    source = Source(
        user_id=user.id,
        type=SourceType.ICS,
        identity_key="ics-cooldown",
        encrypted_url="encrypted-source",
        interval_minutes=15,
        is_active=True,
        last_checked_at=now - timedelta(minutes=30),
    )
    db_session.add(source)
    db_session.flush()

    lock_skipped_started_at = now - timedelta(seconds=8)
    db_session.add(
        SyncRun(
            input_id=source.id,
            trigger_type=SyncTriggerType.SCHEDULER,
            started_at=lock_skipped_started_at,
            finished_at=lock_skipped_started_at,
            status=SyncRunStatus.LOCK_SKIPPED,
            changes_count=0,
            duration_ms=0,
        )
    )
    db_session.commit()

    response = client.get("/v1/inputs", headers={"X-API-Key": "test-api-key"})
    assert response.status_code == 200
    row = response.json()[0]

    next_check_at = datetime.fromisoformat(row["next_check_at"].replace("Z", "+00:00"))
    expected_cooldown_until = lock_skipped_started_at + timedelta(seconds=30)
    assert next_check_at >= expected_cooldown_until
    assert row["last_result"] == "LOCK_SKIPPED"


def test_source_runs_endpoint_returns_recent_timeline(client, db_session) -> None:
    user = User(email="owner@example.com")
    db_session.add(user)
    db_session.flush()

    source = Source(
        user_id=user.id,
        type=SourceType.ICS,
        identity_key="ics-run",
        encrypted_url="encrypted-source",
        interval_minutes=15,
        is_active=True,
    )
    db_session.add(source)
    db_session.flush()

    older = SyncRun(
        input_id=source.id,
        trigger_type=SyncTriggerType.SCHEDULER,
        started_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        finished_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        status=SyncRunStatus.NO_CHANGE,
        changes_count=0,
        duration_ms=88,
    )
    newer = SyncRun(
        input_id=source.id,
        trigger_type=SyncTriggerType.MANUAL,
        started_at=datetime.now(timezone.utc) - timedelta(minutes=2),
        finished_at=datetime.now(timezone.utc) - timedelta(minutes=2),
        status=SyncRunStatus.CHANGED,
        changes_count=2,
        duration_ms=144,
    )
    db_session.add_all([older, newer])
    db_session.commit()

    response = client.get(f"/v1/inputs/{source.id}/runs?limit=1", headers={"X-API-Key": "test-api-key"})
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["status"] == "CHANGED"
    assert payload[0]["trigger_type"] == "manual"
    assert payload[0]["changes_count"] == 2
