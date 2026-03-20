from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db.models.runtime import CalendarComponentParseStatus, CalendarComponentParseTask, IngestJob, IngestJobStatus
from app.db.models.input import IngestTriggerType, InputSource, SyncRequest, SyncRequestStatus
from app.db.models.shared import User
from app.modules.sources.schemas import InputSourceCreateRequest
from app.modules.sources.sources_service import create_input_source


def _create_user(db_session, *, email: str) -> User:
    user = User(
        email=email,
        notify_email=email,
        timezone_name="America/Los_Angeles",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _create_source(db_session, *, user: User, provider: str) -> InputSource:
    return create_input_source(
        db_session,
        user=user,
        payload=InputSourceCreateRequest(
            source_kind="email" if provider == "gmail" else "calendar",
            provider=provider,
            config={"label_id": "INBOX", "monitor_since": "2026-01-05"}
            if provider == "gmail"
            else {"monitor_since": "2026-01-05"},
            secrets={} if provider == "gmail" else {"url": "https://example.com/calendar.ics"},
        ),
    )


def _seed_sync_request(db_session, *, source: InputSource, request_id: str, status: SyncRequestStatus) -> SyncRequest:
    row = SyncRequest(
        request_id=request_id,
        source_id=source.id,
        trigger_type=IngestTriggerType.MANUAL,
        status=status,
        idempotency_key=f"idemp:{request_id}",
        metadata_json={"kind": "test"},
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def _seed_job(db_session, *, source: InputSource, request_id: str, payload_json: dict) -> IngestJob:
    row = IngestJob(
        request_id=request_id,
        source_id=source.id,
        status=IngestJobStatus.CLAIMED,
        attempt=0,
        claimed_by="test-worker",
        claim_token="token",
        payload_json=payload_json,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def test_sources_api_exposes_gmail_sync_progress(input_client, db_session, authenticate_client) -> None:
    user = _create_user(db_session, email="progress-gmail@example.com")
    source = _create_source(db_session, user=user, provider="gmail")
    _seed_sync_request(db_session, source=source, request_id="gmail-progress-req", status=SyncRequestStatus.RUNNING)
    _seed_job(
        db_session,
        source=source,
        request_id="gmail-progress-req",
        payload_json={
            "provider": "gmail",
            "workflow_stage": "CONNECTOR_FETCH_RUNNING",
            "sync_progress": {
                "phase": "gmail_bootstrap_fetch",
                "label": "Scanning Gmail bootstrap window",
                "detail": "Inspected 25 of 100 emails in the bootstrap window.",
                "current": 25,
                "total": 100,
                "percent": 25,
                "unit": "emails",
            },
        },
    )

    authenticate_client(input_client, user=user)
    response = input_client.get("/sources", headers={"X-API-Key": "test-api-key"})

    assert response.status_code == 200
    payload = response.json()[0]
    assert payload["source_id"] == source.id
    assert payload["active_request_id"] == "gmail-progress-req"
    assert payload["runtime_state"] == "running"
    assert payload["sync_progress"]["phase"] == "gmail_bootstrap_fetch"
    assert payload["sync_progress"]["current"] == 25
    assert payload["sync_progress"]["total"] == 100
    assert payload["sync_progress"]["unit"] == "emails"
    assert payload["operator_guidance"]["recommended_action"] == "continue_review_with_caution"


def test_sync_request_status_exposes_calendar_component_progress(input_client, db_session, authenticate_client) -> None:
    user = _create_user(db_session, email="progress-calendar@example.com")
    source = _create_source(db_session, user=user, provider="ics")
    _seed_sync_request(db_session, source=source, request_id="calendar-progress-req", status=SyncRequestStatus.RUNNING)
    _seed_job(
        db_session,
        source=source,
        request_id="calendar-progress-req",
        payload_json={
            "provider": "ics",
            "workflow_stage": "LLM_CALENDAR_FANOUT_QUEUED",
        },
    )
    db_session.add_all(
        [
            CalendarComponentParseTask(
                request_id="calendar-progress-req",
                source_id=source.id,
                component_key="evt-1",
                external_event_id="evt-1",
                vevent_uid="evt-1",
                recurrence_id=None,
                fingerprint="fp-1",
                component_ical_b64="Zm9v",
                status=CalendarComponentParseStatus.SUCCEEDED,
            ),
            CalendarComponentParseTask(
                request_id="calendar-progress-req",
                source_id=source.id,
                component_key="evt-2",
                external_event_id="evt-2",
                vevent_uid="evt-2",
                recurrence_id=None,
                fingerprint="fp-2",
                component_ical_b64="YmFy",
                status=CalendarComponentParseStatus.RUNNING,
            ),
            CalendarComponentParseTask(
                request_id="calendar-progress-req",
                source_id=source.id,
                component_key="evt-3",
                external_event_id="evt-3",
                vevent_uid="evt-3",
                recurrence_id=None,
                fingerprint="fp-3",
                component_ical_b64="YmF6",
                status=CalendarComponentParseStatus.FAILED,
            ),
            CalendarComponentParseTask(
                request_id="calendar-progress-req",
                source_id=source.id,
                component_key="evt-4",
                external_event_id="evt-4",
                vevent_uid="evt-4",
                recurrence_id=None,
                fingerprint="fp-4",
                component_ical_b64="cXV4",
                status=CalendarComponentParseStatus.PENDING,
            ),
        ]
    )
    db_session.commit()

    authenticate_client(input_client, user=user)
    response = input_client.get("/sync-requests/calendar-progress-req", headers={"X-API-Key": "test-api-key"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["progress"]["phase"] == "calendar_parsing"
    assert payload["progress"]["current"] == 2
    assert payload["progress"]["total"] == 4
    assert payload["progress"]["unit"] == "events"
    assert isinstance(payload["progress"]["updated_at"], str)


def test_source_observability_exposes_idle_operator_guidance(input_client, db_session, authenticate_client) -> None:
    user = _create_user(db_session, email="guidance-idle@example.com")
    source = _create_source(db_session, user=user, provider="gmail")

    authenticate_client(input_client, user=user)
    response = input_client.get(f"/sources/{source.id}/observability", headers={"X-API-Key": "test-api-key"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["operator_guidance"]["recommended_action"] == "continue_review"
    assert payload["operator_guidance"]["reason_code"] == "source_idle"


def test_source_observability_exposes_stale_running_operator_guidance(input_client, db_session, authenticate_client) -> None:
    user = _create_user(db_session, email="guidance-stale@example.com")
    source = _create_source(db_session, user=user, provider="ics")
    sync_request = _seed_sync_request(db_session, source=source, request_id="guidance-stale-req", status=SyncRequestStatus.RUNNING)
    sync_request.updated_at = datetime.now(timezone.utc)
    _seed_job(
        db_session,
        source=source,
        request_id="guidance-stale-req",
        payload_json={
            "provider": "ics",
            "workflow_stage": "LLM_CALENDAR_REDUCE_WAITING",
            "sync_progress": {
                "phase": "calendar_parsing",
                "label": "Parsing calendar events",
                "detail": "0 of 12 calendar events have finished parsing.",
                "current": 0,
                "total": 12,
                "percent": 0,
                "unit": "events",
            },
            "sync_progress_updated_at": (datetime.now(timezone.utc) - timedelta(seconds=240)).isoformat(),
        },
    )

    authenticate_client(input_client, user=user)
    response = input_client.get(f"/sources/{source.id}/observability", headers={"X-API-Key": "test-api-key"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["operator_guidance"]["recommended_action"] == "wait_for_runtime"
    assert payload["operator_guidance"]["severity"] == "blocking"


def test_sync_request_status_exposes_llm_usage_summary_and_elapsed_ms(input_client, db_session, authenticate_client) -> None:
    user = _create_user(db_session, email="progress-usage@example.com")
    source = _create_source(db_session, user=user, provider="gmail")
    row = _seed_sync_request(db_session, source=source, request_id="gmail-usage-req", status=SyncRequestStatus.SUCCEEDED)
    row.metadata_json = {
        "kind": "test",
        "llm_usage_summary": {
            "successful_call_count": 4,
            "usage_record_count": 4,
            "latency_ms_total": 2400,
            "latency_ms_max": 900,
            "input_tokens": 3000,
            "cached_input_tokens": 1200,
            "cache_creation_input_tokens": 300,
            "output_tokens": 500,
            "reasoning_tokens": 0,
            "total_tokens": 3500,
            "api_modes": {"chat_completions": 4},
            "models": {"qwen3.5-flash": 4},
            "task_counts": {"gmail_purpose_mode_classify": 4},
            "last_observed_at": "2026-03-18T00:00:10+00:00",
        },
    }
    row.created_at = datetime(2026, 3, 18, 0, 0, 0, tzinfo=timezone.utc)
    row.updated_at = datetime(2026, 3, 18, 0, 0, 5, tzinfo=timezone.utc)
    db_session.commit()

    authenticate_client(input_client, user=user)
    response = input_client.get("/sync-requests/gmail-usage-req", headers={"X-API-Key": "test-api-key"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["elapsed_ms"] == 5000
    assert payload["llm_usage"]["successful_call_count"] == 4
    assert payload["llm_usage"]["cached_input_tokens"] == 1200
    assert payload["llm_usage"]["cache_hit_ratio"] == 0.4
    assert payload["llm_usage"]["avg_latency_ms"] == 600


def test_sources_api_prefers_running_sync_over_newer_pending_sync(input_client, db_session, authenticate_client) -> None:
    user = _create_user(db_session, email="progress-priority@example.com")
    source = _create_source(db_session, user=user, provider="gmail")
    _seed_sync_request(db_session, source=source, request_id="older-running", status=SyncRequestStatus.RUNNING)
    _seed_sync_request(db_session, source=source, request_id="newer-pending", status=SyncRequestStatus.PENDING)
    _seed_job(
        db_session,
        source=source,
        request_id="older-running",
        payload_json={
            "provider": "gmail",
            "workflow_stage": "CONNECTOR_FETCH_RUNNING",
            "sync_progress": {
                "phase": "gmail_bootstrap_fetch",
                "label": "Scanning Gmail bootstrap window",
                "detail": "Inspected 10 of 20 emails in the bootstrap window.",
                "current": 10,
                "total": 20,
                "percent": 50,
                "unit": "emails",
            },
        },
    )

    authenticate_client(input_client, user=user)
    response = input_client.get("/sources", headers={"X-API-Key": "test-api-key"})

    assert response.status_code == 200
    payload = response.json()[0]
    assert payload["active_request_id"] == "older-running"
    assert payload["sync_progress"]["current"] == 10


def test_source_observability_splits_bootstrap_and_latest_replay(input_client, db_session, authenticate_client) -> None:
    user = _create_user(db_session, email="progress-observability@example.com")
    source = _create_source(db_session, user=user, provider="gmail")
    bootstrap = _seed_sync_request(db_session, source=source, request_id="bootstrap-req", status=SyncRequestStatus.SUCCEEDED)
    bootstrap.trigger_type = IngestTriggerType.SCHEDULER
    bootstrap.created_at = datetime(2026, 3, 18, 0, 0, 0, tzinfo=timezone.utc)
    bootstrap.updated_at = datetime(2026, 3, 18, 0, 2, 0, tzinfo=timezone.utc)
    bootstrap.metadata_json = {
        "kind": "scheduler",
        "llm_usage_summary": {
            "successful_call_count": 10,
            "usage_record_count": 10,
            "latency_ms_total": 10000,
            "latency_ms_max": 1400,
            "input_tokens": 9000,
            "cached_input_tokens": 100,
            "cache_creation_input_tokens": 2200,
            "output_tokens": 300,
            "reasoning_tokens": 0,
            "total_tokens": 9300,
            "api_modes": {"chat_completions": 10},
            "models": {"qwen3.5-flash": 10},
            "task_counts": {"gmail_purpose_mode_classify": 10},
        },
    }
    replay = _seed_sync_request(db_session, source=source, request_id="replay-req", status=SyncRequestStatus.RUNNING)
    replay.trigger_type = IngestTriggerType.MANUAL
    replay.created_at = datetime(2026, 3, 18, 1, 0, 0, tzinfo=timezone.utc)
    replay.updated_at = datetime(2026, 3, 18, 1, 0, 30, tzinfo=timezone.utc)
    replay.metadata_json = {
        "kind": "timeline_replay",
        "llm_usage_summary": {
            "successful_call_count": 2,
            "usage_record_count": 2,
            "latency_ms_total": 1200,
            "latency_ms_max": 700,
            "input_tokens": 1200,
            "cached_input_tokens": 500,
            "cache_creation_input_tokens": 0,
            "output_tokens": 80,
            "reasoning_tokens": 0,
            "total_tokens": 1280,
            "api_modes": {"chat_completions": 2},
            "models": {"qwen3.5-flash": 2},
            "task_counts": {"gmail_purpose_mode_classify": 2},
        },
    }
    _seed_job(
        db_session,
        source=source,
        request_id="replay-req",
        payload_json={
            "provider": "gmail",
            "workflow_stage": "CONNECTOR_FETCH_RUNNING",
            "sync_progress": {
                "phase": "gmail_bootstrap_fetch",
                "label": "Scanning Gmail bootstrap window",
                "detail": "Inspected 20 of 100 emails in the bootstrap window.",
                "current": 20,
                "total": 100,
                "percent": 20,
                "unit": "emails",
            },
        },
    )
    db_session.commit()

    authenticate_client(input_client, user=user)
    response = input_client.get(f"/sources/{source.id}/observability", headers={"X-API-Key": "test-api-key"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_id"] == source.id
    assert payload["active_request_id"] == "replay-req"
    assert payload["bootstrap"]["request_id"] == "bootstrap-req"
    assert payload["bootstrap"]["phase"] == "bootstrap"
    assert payload["bootstrap"]["llm_usage"]["successful_call_count"] == 10
    assert payload["latest_replay"]["request_id"] == "replay-req"
    assert payload["latest_replay"]["phase"] == "replay"
    assert payload["latest_replay"]["progress"]["current"] == 20
    assert payload["active"]["request_id"] == "replay-req"


def test_source_sync_history_lists_bootstrap_and_replay_newest_first(input_client, db_session, authenticate_client) -> None:
    user = _create_user(db_session, email="progress-sync-history@example.com")
    source = _create_source(db_session, user=user, provider="gmail")

    bootstrap = _seed_sync_request(db_session, source=source, request_id="history-bootstrap", status=SyncRequestStatus.SUCCEEDED)
    bootstrap.trigger_type = IngestTriggerType.SCHEDULER
    bootstrap.created_at = datetime(2026, 3, 18, 0, 0, 0, tzinfo=timezone.utc)
    bootstrap.updated_at = datetime(2026, 3, 18, 0, 2, 0, tzinfo=timezone.utc)

    replay_a = _seed_sync_request(db_session, source=source, request_id="history-replay-a", status=SyncRequestStatus.SUCCEEDED)
    replay_a.trigger_type = IngestTriggerType.MANUAL
    replay_a.created_at = datetime(2026, 3, 18, 1, 0, 0, tzinfo=timezone.utc)
    replay_a.updated_at = datetime(2026, 3, 18, 1, 1, 0, tzinfo=timezone.utc)

    replay_b = _seed_sync_request(db_session, source=source, request_id="history-replay-b", status=SyncRequestStatus.RUNNING)
    replay_b.trigger_type = IngestTriggerType.MANUAL
    replay_b.created_at = datetime(2026, 3, 18, 2, 0, 0, tzinfo=timezone.utc)
    replay_b.updated_at = datetime(2026, 3, 18, 2, 0, 30, tzinfo=timezone.utc)

    _seed_job(
        db_session,
        source=source,
        request_id="history-replay-b",
        payload_json={
            "provider": "gmail",
            "workflow_stage": "CONNECTOR_FETCH_RUNNING",
            "sync_progress": {
                "phase": "gmail_bootstrap_fetch",
                "label": "Scanning Gmail bootstrap window",
                "detail": "Inspected 5 of 10 emails in the bootstrap window.",
                "current": 5,
                "total": 10,
                "percent": 50,
                "unit": "emails",
            },
        },
    )
    db_session.commit()

    authenticate_client(input_client, user=user)
    response = input_client.get(
        f"/sources/{source.id}/sync-history?limit=2",
        headers={"X-API-Key": "test-api-key"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_id"] == source.id
    assert [item["request_id"] for item in payload["items"]] == ["history-replay-b", "history-replay-a"]
    assert [item["phase"] for item in payload["items"]] == ["replay", "replay"]
    assert payload["items"][0]["progress"]["current"] == 5

    bootstrap_response = input_client.get(
        f"/sources/{source.id}/sync-history?limit=10",
        headers={"X-API-Key": "test-api-key"},
    )
    assert bootstrap_response.status_code == 200
    bootstrap_payload = bootstrap_response.json()
    assert [item["request_id"] for item in bootstrap_payload["items"]] == [
        "history-replay-b",
        "history-replay-a",
        "history-bootstrap",
    ]
    assert bootstrap_payload["items"][-1]["phase"] == "bootstrap"
