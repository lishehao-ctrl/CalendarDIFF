from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.security import decrypt_secret
from app.db.models.input import InputSource
from app.db.models.shared import User
from app.modules.sources.schemas import InputSourceCreateRequest
from app.modules.sources.sources_service import create_input_source


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
            config={"monitor_since": "2026-01-05"},
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
    assert "monitor_since" in payload["config"]


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


def test_ics_source_create_defaults_monitoring_window(input_client, db_session, authenticate_client) -> None:
    user = _create_registered_user(db_session, notify_email="canvas-default-window@example.com")
    authenticate_client(input_client, user=user)

    response = input_client.post(
        "/sources",
        headers={"X-API-Key": "test-api-key"},
        json={
            "source_kind": "calendar",
            "provider": "ics",
            "config": {},
            "secrets": {"url": "https://example.com/canvas-default.ics"},
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert isinstance(payload["config"].get("monitor_since"), str)


def test_ics_source_patch_updates_url_and_preserves_identity(input_client, db_session, authenticate_client) -> None:
    user = _create_registered_user(db_session, notify_email="canvas-patch@example.com")
    source = _create_ics_source(db_session, user=user, url="https://example.com/canvas-a.ics")
    authenticate_client(input_client, user=user)

    response = input_client.patch(
        f"/sources/{source.id}",
        headers={"X-API-Key": "test-api-key"},
        json={
            "display_name": "Ignored Rename",
            "config": {"monitor_since": "2025-12-01"},
            "secrets": {"url": "https://example.com/canvas-b.ics"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_key"] == "canvas_ics"
    assert payload["display_name"] == "Canvas ICS"
    assert payload["config"]["monitor_since"] == "2025-12-01"

    db_session.expire_all()
    refreshed = db_session.scalar(select(InputSource).where(InputSource.id == source.id))
    assert refreshed is not None
    secret_payload = json.loads(decrypt_secret(refreshed.secrets.encrypted_payload))
    assert secret_payload == {"url": "https://example.com/canvas-b.ics"}
    assert refreshed.source_key == "canvas_ics"
    assert refreshed.display_name == "Canvas ICS"


def test_ics_source_archive_moves_row_to_archived_listing(input_client, db_session, authenticate_client) -> None:
    user = _create_registered_user(db_session, notify_email="canvas-archive@example.com")
    source = _create_ics_source(db_session, user=user, url="https://example.com/canvas-a.ics")
    authenticate_client(input_client, user=user)

    response = input_client.delete(f"/sources/{source.id}", headers={"X-API-Key": "test-api-key"})
    assert response.status_code == 200
    assert response.json() == {"deleted": True}

    archived = input_client.get("/sources?status=archived", headers={"X-API-Key": "test-api-key"})
    assert archived.status_code == 200
    payload = archived.json()
    assert len(payload) == 1
    assert payload[0]["source_id"] == source.id
    assert payload[0]["is_active"] is False
