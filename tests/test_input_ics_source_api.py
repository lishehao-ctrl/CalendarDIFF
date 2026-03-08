from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.security import decrypt_secret
from app.db.models.input import InputSource
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
            config={},
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
            "config": {},
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
            "config": {},
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


def test_ics_source_patch_updates_url_and_preserves_identity(input_client, db_session, authenticate_client) -> None:
    user = _create_registered_user(db_session, notify_email="canvas-patch@example.com")
    source = _create_ics_source(db_session, user=user, url="https://example.com/canvas-a.ics")
    authenticate_client(input_client, user=user)

    response = input_client.patch(
        f"/sources/{source.id}",
        headers={"X-API-Key": "test-api-key"},
        json={
            "display_name": "Ignored Rename",
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
            "config": {},
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
            "config": {},
            "secrets": {"url": "https://example.com/b.ics"},
        },
    )
    assert response_b.status_code == 201
    assert response_a.json()["source_id"] != response_b.json()["source_id"]


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
