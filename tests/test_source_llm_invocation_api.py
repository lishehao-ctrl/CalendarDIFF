from __future__ import annotations

from datetime import datetime, timezone

from app.db.models.input import IngestTriggerType, InputSource, SyncRequest, SyncRequestStatus
from app.db.models.runtime import LlmInvocationLog
from app.db.models.shared import User
from app.modules.sources.schemas import InputSourceCreateRequest
from app.modules.sources.sources_service import create_input_source


def _create_user(db_session, *, email: str) -> User:
    user = User(
        email=email,
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
            config={"monitor_since": "2026-01-05"},
            secrets={} if provider == "gmail" else {"url": "https://example.com/calendar.ics"},
        ),
    )


def _seed_sync_request(db_session, *, source: InputSource, request_id: str) -> SyncRequest:
    row = SyncRequest(
        request_id=request_id,
        source_id=source.id,
        trigger_type=IngestTriggerType.MANUAL,
        status=SyncRequestStatus.RUNNING,
        idempotency_key=f"idemp:{request_id}",
        metadata_json={"kind": "test"},
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def _seed_invocation(
    db_session,
    *,
    request_id: str,
    source_id: int,
    task_name: str,
    success: bool,
    created_at: datetime,
    route_id: str,
    protocol: str = "responses",
    usage_json: dict | None = None,
    error_code: str | None = None,
) -> None:
    db_session.add(
        LlmInvocationLog(
            request_id=request_id,
            source_id=source_id,
            task_name=task_name,
            profile_family="ingestion",
            route_id=route_id,
            route_index=1,
            provider_id="env-default",
            vendor="openai",
            protocol=protocol,
            model="test-model",
            session_cache_enabled=False,
            success=success,
            latency_ms=180 if success else None,
            upstream_request_id="upstream-1" if success else None,
            response_id="resp-1" if success else None,
            error_code=error_code,
            retryable=None if success else True,
            http_status=None if success else 429,
            usage_json=usage_json,
            created_at=created_at,
        )
    )
    db_session.commit()


def test_sync_request_llm_invocations_returns_items_and_summary(input_client, db_session, authenticate_client) -> None:
    user = _create_user(db_session, email="llm-invocations-sync@example.com")
    source = _create_source(db_session, user=user, provider="gmail")
    _seed_sync_request(db_session, source=source, request_id="req-llm-1")
    _seed_invocation(
        db_session,
        request_id="req-llm-1",
        source_id=source.id,
        task_name="gmail_purpose_mode_classify",
        success=True,
        created_at=datetime(2026, 3, 24, 10, 0, tzinfo=timezone.utc),
        route_id="ingestion:env-default:responses:primary",
        usage_json={
            "input_tokens": 100,
            "cached_input_tokens": 40,
            "cache_creation_input_tokens": 10,
            "output_tokens": 20,
            "reasoning_tokens": 5,
            "total_tokens": 120,
        },
    )
    _seed_invocation(
        db_session,
        request_id="req-llm-1",
        source_id=source.id,
        task_name="gmail_atomic_identity_extract",
        success=False,
        created_at=datetime(2026, 3, 24, 10, 1, tzinfo=timezone.utc),
        route_id="ingestion:env-default:chat_completions:fallback",
        protocol="chat_completions",
        error_code="parse_llm_upstream_error",
    )

    authenticate_client(input_client, user=user)
    response = input_client.get("/sync-requests/req-llm-1/llm-invocations", headers={"X-API-Key": "test-api-key"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["request_id"] == "req-llm-1"
    assert len(payload["items"]) == 2
    assert payload["items"][0]["task_name"] == "gmail_atomic_identity_extract"
    assert payload["items"][0]["protocol"] == "chat_completions"
    assert payload["items"][1]["task_name"] == "gmail_purpose_mode_classify"
    assert payload["items"][1]["protocol"] == "responses"
    assert payload["summary"]["total_count"] == 2
    assert payload["summary"]["success_count"] == 1
    assert payload["summary"]["failure_count"] == 1
    assert payload["summary"]["protocol_counts"] == {"chat_completions": 1, "responses": 1}
    assert payload["summary"]["input_tokens"] == 100
    assert payload["summary"]["cached_input_tokens"] == 40


def test_source_llm_invocations_filters_by_request_id(input_client, db_session, authenticate_client) -> None:
    user = _create_user(db_session, email="llm-invocations-source@example.com")
    source = _create_source(db_session, user=user, provider="gmail")
    _seed_sync_request(db_session, source=source, request_id="req-llm-a")
    _seed_sync_request(db_session, source=source, request_id="req-llm-b")
    _seed_invocation(
        db_session,
        request_id="req-llm-a",
        source_id=source.id,
        task_name="gmail_purpose_mode_classify",
        success=True,
        created_at=datetime(2026, 3, 24, 11, 0, tzinfo=timezone.utc),
        route_id="ingestion:env-default:responses:primary",
    )
    _seed_invocation(
        db_session,
        request_id="req-llm-b",
        source_id=source.id,
        task_name="gmail_atomic_time_resolve",
        success=True,
        created_at=datetime(2026, 3, 24, 11, 1, tzinfo=timezone.utc),
        route_id="ingestion:env-default:responses:primary",
    )

    authenticate_client(input_client, user=user)
    response = input_client.get(
        f"/sources/{source.id}/llm-invocations",
        params={"request_id": "req-llm-a"},
        headers={"X-API-Key": "test-api-key"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_id"] == source.id
    assert payload["request_id"] == "req-llm-a"
    assert len(payload["items"]) == 1
    assert payload["items"][0]["request_id"] == "req-llm-a"
    assert payload["summary"]["total_count"] == 1
    assert payload["summary"]["task_counts"] == {"gmail_purpose_mode_classify": 1}


def test_sync_request_llm_invocations_enforces_ownership(input_client, db_session, authenticate_client) -> None:
    owner = _create_user(db_session, email="llm-owner@example.com")
    other = _create_user(db_session, email="llm-other@example.com")
    source = _create_source(db_session, user=owner, provider="gmail")
    _seed_sync_request(db_session, source=source, request_id="req-private")
    _seed_invocation(
        db_session,
        request_id="req-private",
        source_id=source.id,
        task_name="gmail_purpose_mode_classify",
        success=True,
        created_at=datetime(2026, 3, 24, 12, 0, tzinfo=timezone.utc),
        route_id="ingestion:env-default:responses:primary",
    )

    authenticate_client(input_client, user=other)
    response = input_client.get("/sync-requests/req-private/llm-invocations", headers={"X-API-Key": "test-api-key"})

    assert response.status_code == 404
