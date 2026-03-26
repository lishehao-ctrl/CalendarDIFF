from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.models.agents import ApprovalTicket
from app.db.models.input import InputSource, SyncRequest
from app.db.models.review import Change, ChangeIntakePhase, ChangeOrigin, ChangeReviewBucket, ChangeSourceRef, ChangeType, ReviewStatus
from app.db.models.shared import CourseWorkItemLabelFamily, User
from app.modules.auth.service import _hash_password
from app.modules.common.course_identity import normalize_label_token, normalized_course_identity_key, parse_course_display
from app.modules.common.request_rate_limit import reset_request_rate_limiters
from app.modules.runtime.connectors.calendar_fetcher import fetch_calendar_delta
from app.modules.runtime.connectors.gmail_fetcher import fetch_gmail_changes
from app.modules.sources.schemas import InputSourceCreateRequest
from app.modules.sources.sources_service import create_input_source
from services.mcp_server.main import get_workspace_context_impl


def _create_user(db_session, *, email: str, onboarded: bool = True) -> User:
    user = User(
        email=email,
        password_hash=_hash_password("password123"),
        timezone_name="America/Los_Angeles",
        timezone_source="manual",
        language_code="en",
        onboarding_completed_at=datetime.now(timezone.utc) if onboarded else None,
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


def _create_family(db_session, *, user_id: int, course_display: str, canonical_label: str) -> CourseWorkItemLabelFamily:
    parsed = parse_course_display(course_display)
    family = CourseWorkItemLabelFamily(
        user_id=user_id,
        course_dept=parsed["course_dept"],
        course_number=parsed["course_number"],
        course_suffix=parsed["course_suffix"],
        course_quarter=parsed["course_quarter"],
        course_year2=parsed["course_year2"],
        normalized_course_identity=normalized_course_identity_key(
            course_dept=parsed["course_dept"],
            course_number=parsed["course_number"],
            course_suffix=parsed["course_suffix"],
            course_quarter=parsed["course_quarter"],
            course_year2=parsed["course_year2"],
        ),
        canonical_label=canonical_label,
        normalized_canonical_label=normalize_label_token(canonical_label),
    )
    db_session.add(family)
    db_session.commit()
    db_session.refresh(family)
    return family


def _create_pending_change(db_session, *, user: User, source: InputSource, family: CourseWorkItemLabelFamily) -> Change:
    change = Change(
        user_id=user.id,
        entity_uid="backend-hardening-change-1",
        change_origin=ChangeOrigin.INGEST_PROPOSAL,
        change_type=ChangeType.DUE_CHANGED,
        intake_phase=ChangeIntakePhase.REPLAY,
        review_bucket=ChangeReviewBucket.CHANGES,
        detected_at=datetime.now(timezone.utc),
        before_semantic_json={
            "uid": "backend-hardening-change-1",
            "course_dept": "CSE",
            "course_number": 160,
            "course_quarter": "WI",
            "course_year2": 26,
            "family_id": family.id,
            "family_name": family.canonical_label,
            "event_name": "Homework 1",
            "ordinal": 1,
            "due_date": "2026-03-20",
            "due_time": "23:59:00",
            "time_precision": "datetime",
        },
        after_semantic_json={
            "uid": "backend-hardening-change-1",
            "course_dept": "CSE",
            "course_number": 160,
            "course_quarter": "WI",
            "course_year2": 26,
            "family_id": family.id,
            "family_name": family.canonical_label,
            "event_name": "Homework 1",
            "ordinal": 1,
            "due_date": "2026-03-21",
            "due_time": "23:59:00",
            "time_precision": "datetime",
        },
        before_evidence_json={"provider": source.provider},
        after_evidence_json={"provider": source.provider},
        review_status=ReviewStatus.PENDING,
    )
    db_session.add(change)
    db_session.flush()
    db_session.add(
        ChangeSourceRef(
            change_id=change.id,
            position=0,
            source_id=source.id,
            source_kind=source.source_kind,
            provider=source.provider,
            external_event_id="evt-backend-hardening",
            confidence=0.95,
        )
    )
    db_session.commit()
    db_session.refresh(change)
    return change


def test_auth_login_rate_limited(input_client, db_session, monkeypatch) -> None:
    monkeypatch.setenv("AUTH_RATE_LIMIT_MAX_REQUESTS", "2")
    monkeypatch.setenv("AUTH_RATE_LIMIT_WINDOW_SECONDS", "60")
    get_settings.cache_clear()
    reset_request_rate_limiters()
    try:
        _create_user(db_session, email="rate-limit-auth@example.com", onboarded=False)
        for _ in range(2):
            response = input_client.post(
                "/auth/login",
                headers={"X-API-Key": "test-api-key"},
                json={"email": "rate-limit-auth@example.com", "password": "wrong-pass"},
            )
            assert response.status_code == 401
        throttled = input_client.post(
            "/auth/login",
            headers={"X-API-Key": "test-api-key"},
            json={"email": "rate-limit-auth@example.com", "password": "wrong-pass"},
        )
        assert throttled.status_code == 429
        assert throttled.headers.get("Retry-After") == "60"
        assert throttled.json()["detail"]["message_code"] == "common.rate_limited"
    finally:
        get_settings.cache_clear()
        reset_request_rate_limiters()


def test_agent_mutation_route_rate_limited(input_client, db_session, auth_headers, monkeypatch) -> None:
    monkeypatch.setenv("MUTATION_RATE_LIMIT_MAX_REQUESTS", "1")
    monkeypatch.setenv("MUTATION_RATE_LIMIT_WINDOW_SECONDS", "60")
    get_settings.cache_clear()
    reset_request_rate_limiters()
    try:
        user = _create_user(db_session, email="rate-limit-mutation@example.com")
        source = _create_source(db_session, user=user, provider="ics")
        family = _create_family(db_session, user_id=user.id, course_display="CSE 160 WI26", canonical_label="Homework")
        change = _create_pending_change(db_session, user=user, source=source, family=family)
        headers = auth_headers(input_client, user=user)

        first = input_client.post(
            "/agent/proposals/change-decision",
            headers=headers,
            json={"change_id": change.id},
        )
        assert first.status_code == 201

        throttled = input_client.post(
            "/agent/proposals/change-decision",
            headers=headers,
            json={"change_id": change.id},
        )
        assert throttled.status_code == 429
        assert throttled.json()["detail"]["message_code"] == "common.rate_limited"
    finally:
        get_settings.cache_clear()
        reset_request_rate_limiters()


def test_manual_sync_reuses_existing_active_request(input_client, db_session, auth_headers) -> None:
    user = _create_user(db_session, email="sync-dedupe@example.com")
    source = _create_source(db_session, user=user, provider="ics")
    headers = auth_headers(input_client, user=user)

    first = input_client.post(
        f"/sources/{source.id}/sync-requests",
        headers=headers,
        json={"metadata": {"kind": "manual-1"}},
    )
    second = input_client.post(
        f"/sources/{source.id}/sync-requests",
        headers=headers,
        json={"metadata": {"kind": "manual-2"}},
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["request_id"] == second.json()["request_id"]
    assert int(
        db_session.scalar(
            select(func.count(SyncRequest.id)).where(SyncRequest.source_id == source.id)
        )
        or 0
    ) == 1


def test_webhook_rejects_oversized_payload(input_client, db_session, auth_headers, monkeypatch) -> None:
    monkeypatch.setenv("WEBHOOK_MAX_BODY_BYTES", "8")
    get_settings.cache_clear()
    try:
        user = _create_user(db_session, email="webhook-oversized@example.com")
        source = _create_source(db_session, user=user, provider="gmail")
        headers = auth_headers(input_client, user=user)
        response = input_client.post(
            f"/sources/{source.id}/webhooks/gmail",
            headers=headers,
            content=b'{"payload":"too-large"}',
        )
        assert response.status_code == 413
        assert int(
            db_session.scalar(
                select(func.count(SyncRequest.id)).where(SyncRequest.source_id == source.id)
            )
            or 0
        ) == 0
    finally:
        get_settings.cache_clear()


def test_webhook_metadata_keeps_only_hash_and_preview(input_client, db_session, auth_headers, monkeypatch) -> None:
    monkeypatch.setenv("WEBHOOK_MAX_BODY_BYTES", "1024")
    monkeypatch.setenv("WEBHOOK_METADATA_PREVIEW_MAX_BYTES", "12")
    get_settings.cache_clear()
    try:
        user = _create_user(db_session, email="webhook-preview@example.com")
        source = _create_source(db_session, user=user, provider="gmail")
        headers = auth_headers(input_client, user=user)
        body = json.dumps({"message": "x" * 200}).encode("utf-8")
        response = input_client.post(
            f"/sources/{source.id}/webhooks/gmail",
            headers=headers,
            content=body,
        )
        assert response.status_code == 200
        row = db_session.scalar(select(SyncRequest).where(SyncRequest.source_id == source.id).limit(1))
        assert row is not None
        metadata = row.metadata_json
        assert metadata["provider"] == "gmail"
        assert metadata["body_sha256"]
        assert isinstance(metadata.get("payload_preview"), str)
        assert len(metadata["payload_preview"]) <= 12
        assert metadata["payload_preview_truncated"] is True
        assert "payload" not in metadata
        assert "payload_raw" not in metadata
    finally:
        get_settings.cache_clear()


def test_mcp_public_mode_requires_bearer_token(db_session, monkeypatch) -> None:
    monkeypatch.setenv("CALENDARDIFF_MCP_MODE", "public")
    monkeypatch.setenv("MCP_PUBLIC_REQUIRE_BEARER_TOKEN", "true")
    get_settings.cache_clear()
    try:
        user = _create_user(db_session, email="mcp-public-auth@example.com")
        with pytest.raises(RuntimeError, match="MCP authentication required."):
            get_workspace_context_impl(email=user.email)
    finally:
        get_settings.cache_clear()


def test_create_approval_ticket_reuses_existing_open_ticket(input_client, db_session, auth_headers) -> None:
    user = _create_user(db_session, email="ticket-dedupe@example.com")
    source = _create_source(db_session, user=user, provider="ics")
    family = _create_family(db_session, user_id=user.id, course_display="CSE 160 WI26", canonical_label="Homework")
    change = _create_pending_change(db_session, user=user, source=source, family=family)
    headers = auth_headers(input_client, user=user)

    proposal = input_client.post(
        "/agent/proposals/change-decision",
        headers=headers,
        json={"change_id": change.id},
    )
    assert proposal.status_code == 201
    proposal_id = proposal.json()["proposal_id"]

    first = input_client.post(
        "/agent/approval-tickets",
        headers=headers,
        json={"proposal_id": proposal_id, "channel": "web"},
    )
    second = input_client.post(
        "/agent/approval-tickets",
        headers=headers,
        json={"proposal_id": proposal_id, "channel": "web"},
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["ticket_id"] == second.json()["ticket_id"]
    assert int(
        db_session.scalar(
            select(func.count(ApprovalTicket.ticket_id)).where(ApprovalTicket.proposal_id == proposal_id)
        )
        or 0
    ) == 1


def test_gmail_fetcher_fails_when_continuation_message_budget_exceeded(monkeypatch) -> None:
    monkeypatch.setenv("GMAIL_CONTINUATION_MAX_MESSAGE_IDS", "2")
    get_settings.cache_clear()
    try:
        monkeypatch.setattr(
            "app.modules.runtime.connectors.gmail_fetcher.decode_source_secrets",
            lambda _source: {"access_token": "token"},
        )

        class _FakeGmailClient:
            def get_profile(self, *, access_token: str):
                assert access_token == "token"
                return SimpleNamespace(email_address="student@example.com", history_id="history-1")

        monkeypatch.setattr("app.modules.runtime.connectors.gmail_fetcher.GmailClient", _FakeGmailClient)
        outcome = fetch_gmail_changes(
            source=SimpleNamespace(config=None, cursor=None),
            request_id="gmail-budget-req",
            job_payload={
                "connector_continuation": {
                    "provider": "gmail",
                    "gmail_message_ids": ["m1", "m2", "m3"],
                    "gmail_total_messages": 3,
                    "gmail_next_index": 0,
                    "gmail_matched_messages_buffer": [],
                    "gmail_matched_count": 0,
                }
            },
        )
        assert outcome.status.value == "FETCH_FAILED"
        assert outcome.error_code == "gmail_continuation_message_limit_exceeded"
    finally:
        get_settings.cache_clear()


def test_calendar_fetcher_fails_when_payload_too_large(monkeypatch) -> None:
    monkeypatch.setenv("ICS_MAX_PAYLOAD_BYTES", "8")
    get_settings.cache_clear()
    try:
        monkeypatch.setattr(
            "app.modules.runtime.connectors.calendar_fetcher.decode_source_secrets",
            lambda _source: {"url": "https://example.com/calendar.ics"},
        )

        class _FakeIcsClient:
            def fetch(self, url: str, source_id: int, if_none_match=None, if_modified_since=None):
                assert url == "https://example.com/calendar.ics"
                assert source_id == 1
                del if_none_match, if_modified_since
                return SimpleNamespace(
                    not_modified=False,
                    content=b"0123456789",
                    etag="etag-1",
                    last_modified="last-modified-1",
                )

        monkeypatch.setattr("app.modules.runtime.connectors.calendar_fetcher.ICSClient", _FakeIcsClient)
        outcome = fetch_calendar_delta(source=SimpleNamespace(id=1, cursor=None, config=None))
        assert outcome.status.value == "FETCH_FAILED"
        assert outcome.error_code == "calendar_payload_too_large"
    finally:
        get_settings.cache_clear()


def test_calendar_fetcher_fails_when_component_budget_exceeded(monkeypatch) -> None:
    monkeypatch.setenv("ICS_MAX_COMPONENTS", "1")
    get_settings.cache_clear()
    try:
        monkeypatch.setattr(
            "app.modules.runtime.connectors.calendar_fetcher.decode_source_secrets",
            lambda _source: {"url": "https://example.com/calendar.ics"},
        )

        ics_payload = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
            "BEGIN:VEVENT\r\nUID:evt-1\r\nDTSTART:20260301T100000Z\r\nDTEND:20260301T110000Z\r\nSUMMARY:Homework 1\r\nEND:VEVENT\r\n"
            "BEGIN:VEVENT\r\nUID:evt-2\r\nDTSTART:20260302T100000Z\r\nDTEND:20260302T110000Z\r\nSUMMARY:Homework 2\r\nEND:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        ).encode("utf-8")

        class _FakeIcsClient:
            def fetch(self, url: str, source_id: int, if_none_match=None, if_modified_since=None):
                assert url == "https://example.com/calendar.ics"
                assert source_id == 1
                del if_none_match, if_modified_since
                return SimpleNamespace(
                    not_modified=False,
                    content=ics_payload,
                    etag="etag-1",
                    last_modified="last-modified-1",
                )

        monkeypatch.setattr("app.modules.runtime.connectors.calendar_fetcher.ICSClient", _FakeIcsClient)
        outcome = fetch_calendar_delta(source=SimpleNamespace(id=1, cursor=None, config=None))
        assert outcome.status.value == "PARSE_FAILED"
        assert outcome.error_code == "calendar_delta_parse_failed"
        assert "component count exceeded configured limit" in str(outcome.error_message)
    finally:
        get_settings.cache_clear()
