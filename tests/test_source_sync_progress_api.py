from __future__ import annotations

from datetime import datetime, timezone

from app.db.models.ingestion import CalendarComponentParseStatus, CalendarComponentParseTask, IngestJob, IngestJobStatus
from app.db.models.input import IngestTriggerType, InputSource, SyncRequest, SyncRequestStatus
from app.db.models.shared import User
from app.modules.input_control_plane.schemas import InputSourceCreateRequest
from app.modules.input_control_plane.sources_service import create_input_source


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
            config={"label_id": "INBOX", "term_key": "WI26", "term_from": "2026-01-05", "term_to": "2026-03-20"}
            if provider == "gmail"
            else {"term_key": "WI26", "term_from": "2026-01-05", "term_to": "2026-03-20"},
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
