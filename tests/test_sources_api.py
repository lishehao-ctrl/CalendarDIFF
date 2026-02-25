from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db.models import Input, InputType, SyncRun, SyncRunStatus, SyncTriggerType, User
from app.modules.inputs.schemas import InputCreateRequest
from app.modules.inputs.service import create_ics_input
from tests.helpers_inputs import create_ics_input_for_user


def test_sources_api_requires_api_key(client) -> None:
    response = client.get("/v1/inputs")
    assert response.status_code == 401


def test_create_input_rejects_legacy_name_field(client, initialized_user) -> None:
    headers = {"X-API-Key": "test-api-key"}

    legacy_name = client.post(
        "/v1/inputs/ics",
        headers=headers,
        json={"name": "   ", "url": "https://example.com/feed.ics"},
    )
    assert legacy_name.status_code == 404


def test_create_and_list_sources_hides_url(client, initialized_user, db_session) -> None:
    headers = {"X-API-Key": "test-api-key"}
    source_id = create_ics_input_for_user(
        db_session,
        user_id=initialized_user["id"],
        url="https://example.com/feed.ics",
    )

    list_response = client.get("/v1/inputs", headers=headers)
    assert list_response.status_code == 200

    items = list_response.json()
    assert len(items) == 1
    assert items[0]["id"] == source_id
    assert items[0]["display_label"].startswith("Calendar")
    assert items[0]["interval_minutes"] == 15
    assert items[0]["notify_email"] is None
    assert items[0]["provider"] is None
    assert items[0]["gmail_label"] is None
    assert items[0]["gmail_from_contains"] is None
    assert items[0]["gmail_subject_keywords"] is None
    assert items[0]["gmail_account_email"] is None
    assert "upserted_existing" not in items[0]
    assert "url" not in items[0]
    assert "encrypted_url" not in items[0]


def test_duplicate_identity_upserts_source_in_place(client, initialized_user, db_session) -> None:
    first = create_ics_input(
        db_session,
        user_id=initialized_user["id"],
        payload=InputCreateRequest(url="https://example.com/feed.ics"),
    )
    assert first.upserted_existing is False

    second = create_ics_input(
        db_session,
        user_id=initialized_user["id"],
        payload=InputCreateRequest(url="https://example.com/feed.ics"),
    )
    assert second.upserted_existing is True
    assert second.input.id == first.input.id
    assert second.input.notify_email is None
    assert second.input.interval_minutes == 15

    list_response = client.get("/v1/inputs", headers={"X-API-Key": "test-api-key"})
    assert list_response.status_code == 200
    items = list_response.json()
    assert len(items) == 1
    assert items[0]["id"] == first.input.id


def test_list_sources_includes_runtime_state_fields(client, db_session) -> None:
    user = User(
        email="owner@example.com",
        notify_email="student@example.com",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.flush()

    source = Input(
        user_id=user.id,
        type=InputType.ICS,
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
    user = User(
        email="owner@example.com",
        notify_email="student@example.com",
        onboarding_completed_at=now,
    )
    db_session.add(user)
    db_session.flush()

    source = Input(
        user_id=user.id,
        type=InputType.ICS,
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
    user = User(
        email="owner@example.com",
        notify_email="student@example.com",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.flush()

    source = Input(
        user_id=user.id,
        type=InputType.ICS,
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
