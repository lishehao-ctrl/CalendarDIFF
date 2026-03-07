from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.security import decrypt_secret, encrypt_secret
from app.db.models.input import InputSource
from app.db.models.shared import User
from app.modules.input_control_plane.schemas import InputSourceCreateRequest
from app.modules.input_control_plane.sources_service import create_input_source


def _create_registered_user(db_session) -> User:
    user = User(
        email=None,
        notify_email="gmail-owner@example.com",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _create_gmail_source(db_session, *, user: User) -> InputSource:
    source = create_input_source(
        db_session,
        user=user,
        payload=InputSourceCreateRequest(
            source_kind="email",
            provider="gmail",
            display_name="Gmail Inbox",
            config={"label_id": "INBOX"},
            secrets={},
        ),
    )
    return source


def test_sources_list_includes_gmail_oauth_status(input_client, db_session, authenticate_client) -> None:
    user = _create_registered_user(db_session)
    source = _create_gmail_source(db_session, user=user)
    source.secrets.encrypted_payload = encrypt_secret(
        json.dumps(
            {
                "access_token": "token",
                "refresh_token": "refresh-token",
                "account_email": "student@example.edu",
            }
        )
    )
    db_session.commit()

    authenticate_client(input_client, user=user)
    response = input_client.get("/sources", headers={"X-API-Key": "test-api-key"})

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["source_id"] == source.id
    assert payload[0]["oauth_connection_status"] == "connected"
    assert payload[0]["oauth_account_email"] == "student@example.edu"


def test_gmail_source_create_is_singleton_per_user(input_client, db_session, authenticate_client) -> None:
    user = _create_registered_user(db_session)
    existing = _create_gmail_source(db_session, user=user)

    authenticate_client(input_client, user=user)

    response = input_client.post(
        "/sources",
        headers={"X-API-Key": "test-api-key"},
        json={
            "source_kind": "email",
            "provider": "gmail",
            "display_name": "Another Gmail",
            "config": {"label_id": "INBOX"},
            "secrets": {},
        },
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": {
            "code": "gmail_source_exists",
            "message": "gmail source already exists for this user",
            "existing_source_id": existing.id,
        }
    }


def test_delete_gmail_source_clears_connection_state(input_client, db_session, authenticate_client) -> None:
    user = _create_registered_user(db_session)
    source = _create_gmail_source(db_session, user=user)
    source.last_error_code = "gmail_auth_failed"
    source.last_error_message = "token expired"
    source.secrets.encrypted_payload = encrypt_secret(
        json.dumps(
            {
                "access_token": "token",
                "refresh_token": "refresh-token",
                "account_email": "student@example.edu",
            }
        )
    )
    source.cursor.cursor_json = {"history_id": "123"}
    db_session.commit()

    authenticate_client(input_client, user=user)
    response = input_client.delete(f"/sources/{source.id}", headers={"X-API-Key": "test-api-key"})
    assert response.status_code == 200
    assert response.json() == {"deleted": True}

    db_session.expire_all()
    refreshed = db_session.scalar(select(InputSource).where(InputSource.id == source.id))
    assert refreshed is not None
    assert refreshed.is_active is False
    assert refreshed.last_error_code is None
    assert refreshed.last_error_message is None
    assert refreshed.secrets is None
    assert refreshed.cursor is None

    list_response = input_client.get("/sources", headers={"X-API-Key": "test-api-key"})
    assert list_response.status_code == 200
    payload = list_response.json()[0]
    assert payload["oauth_connection_status"] == "not_connected"
    assert payload["oauth_account_email"] is None
