from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select

from app.db.models.ingestion import IngestUnresolvedRecord
from app.core.security import decrypt_secret
from app.db.models.input import InputSource, InputSourceCursor, SyncRequest
from app.db.models.review import (
    Change,
    ChangeSourceRef,
    ChangeType,
    EventEntityLink,
    EventLinkBlock,
    EventLinkCandidate,
    EventLinkCandidateReason,
    EventLinkCandidateStatus,
    ReviewStatus,
    SourceEventObservation,
)
from app.db.models.shared import User
from app.modules.input_control_plane.schemas import InputSourceCreateRequest
from app.modules.input_control_plane.sources_service import create_input_source


def _create_registered_user(db_session, *, notify_email: str) -> User:
    user = User(
        email=None,
        notify_email=notify_email,
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _create_ics_source(db_session, *, user: User, url: str) -> InputSource:
    return create_input_source(
        db_session,
        user=user,
        payload=InputSourceCreateRequest(
            source_kind="calendar",
            provider="ics",
            config={"term_key": "WI26", "term_from": "2026-01-05", "term_to": "2026-03-20"},
            secrets={"url": url},
        ),
    )


def test_ics_source_create_normalizes_to_canvas_identity(input_client, db_session, authenticate_client) -> None:
    user = _create_registered_user(db_session, notify_email="canvas-owner@example.com")
    authenticate_client(input_client, user=user)

    response = input_client.post(
        "/sources",
        headers={"X-API-Key": "test-api-key"},
        json={
            "source_kind": "calendar",
            "provider": "ics",
            "source_key": "custom-calendar-key",
            "display_name": "Custom Calendar",
            "config": {"term_key": "WI26", "term_from": "2026-01-05", "term_to": "2026-03-20"},
            "secrets": {"url": "https://example.com/canvas-a.ics"},
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["provider"] == "ics"
    assert payload["source_key"] == "canvas_ics"
    assert payload["display_name"] == "Canvas ICS"


def test_ics_source_create_is_singleton_per_user(input_client, db_session, authenticate_client) -> None:
    user = _create_registered_user(db_session, notify_email="canvas-singleton@example.com")
    existing = _create_ics_source(db_session, user=user, url="https://example.com/canvas-a.ics")
    authenticate_client(input_client, user=user)

    response = input_client.post(
        "/sources",
        headers={"X-API-Key": "test-api-key"},
        json={
            "source_kind": "calendar",
            "provider": "ics",
            "config": {"term_key": "WI26", "term_from": "2026-01-05", "term_to": "2026-03-20"},
            "secrets": {"url": "https://example.com/canvas-b.ics"},
        },
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": {
            "code": "ics_source_exists",
            "message": "ics source already exists for this user",
            "existing_source_id": existing.id,
        }
    }


def test_ics_source_create_requires_term_window_config(input_client, db_session, authenticate_client) -> None:
    user = _create_registered_user(db_session, notify_email="canvas-term-required@example.com")
    authenticate_client(input_client, user=user)

    response = input_client.post(
        "/sources",
        headers={"X-API-Key": "test-api-key"},
        json={
            "source_kind": "calendar",
            "provider": "ics",
            "config": {},
            "secrets": {"url": "https://example.com/canvas-b.ics"},
        },
    )

    assert response.status_code == 422
    assert "term_key" in str(response.json()["detail"])


def test_ics_source_patch_updates_url_and_preserves_identity(input_client, db_session, authenticate_client) -> None:
    user = _create_registered_user(db_session, notify_email="canvas-patch@example.com")
    source = _create_ics_source(db_session, user=user, url="https://example.com/canvas-a.ics")
    authenticate_client(input_client, user=user)

    response = input_client.patch(
        f"/sources/{source.id}",
        headers={"X-API-Key": "test-api-key"},
        json={
            "display_name": "Ignored Rename",
            "config": {"term_key": "WI26", "term_from": "2026-01-05", "term_to": "2026-03-20"},
            "secrets": {"url": "https://example.com/canvas-b.ics"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_key"] == "canvas_ics"
    assert payload["display_name"] == "Canvas ICS"

    db_session.expire_all()
    refreshed = db_session.scalar(select(InputSource).where(InputSource.id == source.id))
    assert refreshed is not None
    secret_payload = json.loads(decrypt_secret(refreshed.secrets.encrypted_payload))
    assert secret_payload == {"url": "https://example.com/canvas-b.ics"}
    assert refreshed.source_key == "canvas_ics"
    assert refreshed.display_name == "Canvas ICS"


def test_ics_source_term_rebind_rescopes_state_and_enqueues_sync(input_client, db_session, authenticate_client) -> None:
    user = _create_registered_user(db_session, notify_email="canvas-rescope@example.com")
    source = _create_ics_source(db_session, user=user, url="https://example.com/canvas-a.ics")
    source.cursor.cursor_json = {"etag": "abc", "ics_component_fingerprints": {"evt-1": "fp"}}
    db_session.add(
        SourceEventObservation(
            user_id=user.id,
            source_id=source.id,
            source_kind=source.source_kind,
            provider=source.provider,
            external_event_id="evt-1",
            entity_uid="entity-rescope-1",
            event_payload={
                "source_facts": {"external_event_id": "evt-1", "source_dtstart_utc": "2026-02-10T20:00:00Z"},
                "semantic_event": {"family_id": 101, "due_date": "2026-02-10", "confidence": 0.9},
                "link_signals": {},
                "kind_resolution": {"status": "resolved", "family_id": 101},
            },
            event_hash="hash-evt-1",
            observed_at=datetime.now(timezone.utc),
            is_active=True,
            last_request_id="req-observation",
        )
    )
    change = Change(
        user_id=user.id,
        entity_uid="entity-rescope-1",
        change_type=ChangeType.CREATED,
        detected_at=datetime.now(timezone.utc),
        before_semantic_json=None,
        after_semantic_json={"event_name": "HW1"},
        delta_seconds=None,
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
            external_event_id="evt-1",
            confidence=0.9,
        )
    )
    db_session.add(
        EventEntityLink(
            user_id=user.id,
            entity_uid="entity-rescope-1",
            source_id=source.id,
            source_kind=source.source_kind,
            external_event_id="evt-1",
        )
    )
    db_session.add(
        EventLinkCandidate(
            user_id=user.id,
            source_id=source.id,
            external_event_id="evt-1",
            proposed_entity_uid="entity-rescope-1",
            reason_code=EventLinkCandidateReason.SCORE_BAND,
            status=EventLinkCandidateStatus.PENDING,
        )
    )
    db_session.add(
        EventLinkBlock(
            user_id=user.id,
            source_id=source.id,
            external_event_id="evt-1",
            blocked_entity_uid="entity-rescope-2",
        )
    )
    db_session.add(
        IngestUnresolvedRecord(
            user_id=user.id,
            source_id=source.id,
            source_kind=source.source_kind,
            provider=source.provider,
            external_event_id="evt-unresolved",
            request_id="req-unresolved",
            reason_code="term_out_of_scope",
            source_facts_json={"external_event_id": "evt-unresolved"},
            is_active=True,
        )
    )
    db_session.commit()
    authenticate_client(input_client, user=user)

    response = input_client.patch(
        f"/sources/{source.id}",
        headers={"X-API-Key": "test-api-key"},
        json={"config": {"term_key": "WI26-R2", "term_from": "2026-02-01", "term_to": "2026-04-01"}},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["config"] == {"term_key": "WI26-R2", "term_from": "2026-02-01", "term_to": "2026-04-01"}

    db_session.expire_all()
    refreshed = db_session.scalar(select(InputSource).where(InputSource.id == source.id))
    assert refreshed is not None
    assert refreshed.cursor is not None
    assert refreshed.cursor.cursor_json == {}
    assert db_session.scalar(select(InputSourceCursor.source_id).where(InputSourceCursor.source_id == source.id)) == source.id
    assert db_session.scalar(
        select(SourceEventObservation).where(SourceEventObservation.source_id == source.id)
    ) is None
    assert db_session.scalar(select(EventEntityLink).where(EventEntityLink.source_id == source.id)) is None
    assert db_session.scalar(select(EventLinkCandidate).where(EventLinkCandidate.source_id == source.id)) is None
    assert db_session.scalar(select(EventLinkBlock).where(EventLinkBlock.source_id == source.id)) is None
    assert db_session.scalar(select(IngestUnresolvedRecord).where(IngestUnresolvedRecord.source_id == source.id)) is None

    rejected_change = db_session.scalar(select(Change).where(Change.id == change.id))
    assert rejected_change is not None
    assert rejected_change.review_status == ReviewStatus.REJECTED
    assert rejected_change.review_note == "proposal_resolved_no_active_observation"

    rescope_request = db_session.scalar(
        select(SyncRequest)
        .where(SyncRequest.source_id == source.id, SyncRequest.idempotency_key.like("term_rescope:%"))
        .order_by(SyncRequest.id.desc())
    )
    assert rescope_request is not None
    assert rescope_request.metadata_json["kind"] == "term_rescope"


def test_ics_source_term_rebind_to_future_window_does_not_enqueue_sync(input_client, db_session, authenticate_client) -> None:
    user = _create_registered_user(db_session, notify_email="canvas-future-rescope@example.com")
    source = _create_ics_source(db_session, user=user, url="https://example.com/canvas-a.ics")
    authenticate_client(input_client, user=user)

    response = input_client.patch(
        f"/sources/{source.id}",
        headers={"X-API-Key": "test-api-key"},
        json={"config": {"term_key": "SP99", "term_from": "2099-04-01", "term_to": "2099-06-01"}},
    )

    assert response.status_code == 200
    db_session.expire_all()
    rescope_request = db_session.scalar(
        select(SyncRequest).where(
            SyncRequest.source_id == source.id,
            SyncRequest.idempotency_key.like("term_rescope:%"),
        )
    )
    assert rescope_request is None


def test_ics_source_term_rebind_to_expired_window_archives_source(input_client, db_session, authenticate_client) -> None:
    user = _create_registered_user(db_session, notify_email="canvas-expired-rescope@example.com")
    source = _create_ics_source(db_session, user=user, url="https://example.com/canvas-a.ics")
    authenticate_client(input_client, user=user)

    response = input_client.patch(
        f"/sources/{source.id}",
        headers={"X-API-Key": "test-api-key"},
        json={"config": {"term_key": "WI20", "term_from": "2020-01-01", "term_to": "2020-03-01"}},
    )

    assert response.status_code == 200
    db_session.expire_all()
    refreshed = db_session.scalar(select(InputSource).where(InputSource.id == source.id))
    assert refreshed is not None
    assert refreshed.is_active is False
    assert refreshed.next_poll_at is None
    assert db_session.scalar(
        select(SyncRequest).where(
            SyncRequest.source_id == source.id,
            SyncRequest.idempotency_key.like("term_rescope:%"),
        )
    ) is None


def test_ics_source_archive_moves_row_to_archived_listing(input_client, db_session, authenticate_client) -> None:
    user = _create_registered_user(db_session, notify_email="canvas-archive@example.com")
    source = _create_ics_source(db_session, user=user, url="https://example.com/archive.ics")
    authenticate_client(input_client, user=user)

    delete_response = input_client.delete(f"/sources/{source.id}", headers={"X-API-Key": "test-api-key"})
    assert delete_response.status_code == 200

    active_response = input_client.get("/sources", headers={"X-API-Key": "test-api-key"})
    assert active_response.status_code == 200
    assert active_response.json() == []

    archived_response = input_client.get("/sources?status=archived", headers={"X-API-Key": "test-api-key"})
    assert archived_response.status_code == 200
    payload = archived_response.json()
    assert len(payload) == 1
    assert payload[0]["source_id"] == source.id

    reactivate_response = input_client.patch(
        f"/sources/{source.id}",
        headers={"X-API-Key": "test-api-key"},
        json={"is_active": True},
    )
    assert reactivate_response.status_code == 200
    assert reactivate_response.json()["is_active"] is True


def test_ics_source_singleton_is_scoped_per_user(input_client, db_session, authenticate_client) -> None:
    user_a = _create_registered_user(db_session, notify_email="canvas-a@example.com")
    user_b = _create_registered_user(db_session, notify_email="canvas-b@example.com")

    authenticate_client(input_client, user=user_a)
    response_a = input_client.post(
        "/sources",
        headers={"X-API-Key": "test-api-key"},
        json={
            "source_kind": "calendar",
            "provider": "ics",
            "config": {"term_key": "WI26", "term_from": "2026-01-05", "term_to": "2026-03-20"},
            "secrets": {"url": "https://example.com/a.ics"},
        },
    )
    assert response_a.status_code == 201

    authenticate_client(input_client, user=user_b)
    response_b = input_client.post(
        "/sources",
        headers={"X-API-Key": "test-api-key"},
        json={
            "source_kind": "calendar",
            "provider": "ics",
            "config": {"term_key": "WI26", "term_from": "2026-01-05", "term_to": "2026-03-20"},
            "secrets": {"url": "https://example.com/b.ics"},
        },
    )
    assert response_b.status_code == 201
    assert response_a.json()["source_id"] != response_b.json()["source_id"]


def test_manual_sync_request_blocks_before_term_start(input_client, db_session, authenticate_client) -> None:
    user = _create_registered_user(db_session, notify_email="future-term@example.com")
    source = create_input_source(
        db_session,
        user=user,
        payload=InputSourceCreateRequest(
            source_kind="calendar",
            provider="ics",
            config={"term_key": "SP26", "term_from": "2099-04-01", "term_to": "2099-06-01"},
            secrets={"url": "https://example.com/future.ics"},
        ),
    )
    authenticate_client(input_client, user=user)

    response = input_client.post(
        f"/sources/{source.id}/sync-requests",
        headers={"X-API-Key": "test-api-key"},
        json={"metadata": {"kind": "manual"}},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "source_term_not_started"


def test_manual_sync_request_archives_expired_term_source(input_client, db_session, authenticate_client) -> None:
    user = _create_registered_user(db_session, notify_email="expired-term@example.com")
    source = create_input_source(
        db_session,
        user=user,
        payload=InputSourceCreateRequest(
            source_kind="calendar",
            provider="ics",
            config={"term_key": "WI20", "term_from": "2020-01-01", "term_to": "2020-03-01"},
            secrets={"url": "https://example.com/expired.ics"},
        ),
    )
    authenticate_client(input_client, user=user)

    response = input_client.post(
        f"/sources/{source.id}/sync-requests",
        headers={"X-API-Key": "test-api-key"},
        json={"metadata": {"kind": "manual"}},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "source_term_archived"
    db_session.expire_all()
    refreshed = db_session.scalar(select(InputSource).where(InputSource.id == source.id))
    assert refreshed is not None
    assert refreshed.is_active is False
    assert refreshed.next_poll_at is None


def test_onboarding_status_reports_structured_source_health(input_client, db_session, authenticate_client) -> None:
    user = _create_registered_user(db_session, notify_email="canvas-health@example.com")
    authenticate_client(input_client, user=user)

    disconnected_response = input_client.get("/onboarding/status", headers={"X-API-Key": "test-api-key"})
    assert disconnected_response.status_code == 200
    assert disconnected_response.json()["source_health"] == {
        "status": "disconnected",
        "message": "No active sources connected yet.",
        "affected_source_id": None,
        "affected_provider": None,
    }

    source = _create_ics_source(db_session, user=user, url="https://example.com/health.ics")
    source.last_error_code = "ics_fetch_failed"
    source.last_error_message = "ssl verify failed"
    db_session.commit()

    attention_response = input_client.get("/onboarding/status", headers={"X-API-Key": "test-api-key"})
    assert attention_response.status_code == 200
    payload = attention_response.json()
    assert payload["stage"] == "ready"
    assert payload["source_health"] == {
        "status": "attention",
        "message": "A connected source needs attention before syncs are reliable.",
        "affected_source_id": source.id,
        "affected_provider": "ics",
    }


def test_archived_listing_excludes_active_sources(input_client, db_session, authenticate_client) -> None:
    user = _create_registered_user(db_session, notify_email="mixed-sources@example.com")
    archived_ics = _create_ics_source(db_session, user=user, url="https://example.com/mixed-ics.ics")
    active_gmail = create_input_source(
        db_session,
        user=user,
        payload=InputSourceCreateRequest(
            source_kind="email",
            provider="gmail",
            display_name="Workspace Gmail",
            config={"label_id": "INBOX", "term_key": "WI26", "term_from": "2026-01-05", "term_to": "2026-03-20"},
            secrets={},
        ),
    )
    authenticate_client(input_client, user=user)

    delete_response = input_client.delete(f"/sources/{archived_ics.id}", headers={"X-API-Key": "test-api-key"})
    assert delete_response.status_code == 200

    active_response = input_client.get("/sources", headers={"X-API-Key": "test-api-key"})
    assert active_response.status_code == 200
    assert [row["source_id"] for row in active_response.json()] == [active_gmail.id]

    archived_response = input_client.get("/sources?status=archived", headers={"X-API-Key": "test-api-key"})
    assert archived_response.status_code == 200
    assert [row["source_id"] for row in archived_response.json()] == [archived_ics.id]
