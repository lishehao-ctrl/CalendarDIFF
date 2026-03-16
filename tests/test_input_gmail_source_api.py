from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.security import decrypt_secret, encrypt_secret
from app.db.models.input import IngestTriggerType, InputSource, SyncRequest, SyncRequestStatus
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
            config={"label_id": "INBOX", "term_key": "WI26", "term_from": "2026-01-05", "term_to": "2026-03-20"},
            secrets={},
        ),
    )
    return source


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
    return row


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
    assert payload[0]["lifecycle_state"] == "active"
    assert payload[0]["sync_state"] == "idle"
    assert payload[0]["config_state"] == "stable"
    assert payload[0]["runtime_state"] == "active"


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
            "config": {"label_id": "INBOX", "term_key": "WI26", "term_from": "2026-01-05", "term_to": "2026-03-20"},
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


def test_gmail_source_create_requires_term_window_config(input_client, db_session, authenticate_client) -> None:
    user = _create_registered_user(db_session)
    authenticate_client(input_client, user=user)

    response = input_client.post(
        "/sources",
        headers={"X-API-Key": "test-api-key"},
        json={
            "source_kind": "email",
            "provider": "gmail",
            "display_name": "Gmail Inbox",
            "config": {"label_id": "INBOX"},
            "secrets": {},
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "config must include term_from and term_to"


def test_gmail_source_create_rejects_inverted_term_window(input_client, db_session, authenticate_client) -> None:
    user = _create_registered_user(db_session)
    authenticate_client(input_client, user=user)

    response = input_client.post(
        "/sources",
        headers={"X-API-Key": "test-api-key"},
        json={
            "source_kind": "email",
            "provider": "gmail",
            "display_name": "Gmail Inbox",
            "config": {"label_id": "INBOX", "term_key": "WI26", "term_from": "2026-03-20", "term_to": "2026-01-05"},
            "secrets": {},
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "invalid term window config: Value error, term_to must be on or after term_from"


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

    active_list_response = input_client.get("/sources", headers={"X-API-Key": "test-api-key"})
    assert active_list_response.status_code == 200
    assert active_list_response.json() == []

    archived_list_response = input_client.get("/sources?status=archived", headers={"X-API-Key": "test-api-key"})
    assert archived_list_response.status_code == 200
    payload = archived_list_response.json()[0]
    assert payload["oauth_connection_status"] == "not_connected"
    assert payload["oauth_account_email"] is None

    reactivate_response = input_client.patch(
        f"/sources/{source.id}",
        headers={"X-API-Key": "test-api-key"},
        json={"is_active": True},
    )
    assert reactivate_response.status_code == 200
    assert reactivate_response.json()["is_active"] is True


def test_gmail_term_rebind_queues_whole_config_when_sync_running(input_client, db_session, authenticate_client) -> None:
    user = _create_registered_user(db_session)
    source = _create_gmail_source(db_session, user=user)
    _seed_sync_request(
        db_session,
        source=source,
        request_id="gmail-running-rebind",
        status=SyncRequestStatus.RUNNING,
    )
    authenticate_client(input_client, user=user)

    response = input_client.patch(
        f"/sources/{source.id}",
        headers={"X-API-Key": "test-api-key"},
        json={
            "config": {
                "label_id": "COURSE",
                "subject_keywords": ["homework"],
                "term_key": "SP26",
                "term_from": "2026-03-25",
                "term_to": "2026-06-10",
            }
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["config"]["label_id"] == "INBOX"
    assert payload["config"]["term_key"] == "WI26"
    pending = payload["config"]["pending_term_rebind"]
    assert pending["term_key"] == "SP26"
    assert pending["requested_config"]["label_id"] == "COURSE"
    assert pending["requested_config"]["subject_keywords"] == ["homework"]
    assert payload["lifecycle_state"] == "active"
    assert payload["sync_state"] == "running"
    assert payload["config_state"] == "rebind_pending"
    assert payload["runtime_state"] == "rebind_pending"

    db_session.expire_all()
    refreshed = db_session.scalar(select(InputSource).where(InputSource.id == source.id))
    assert refreshed is not None
    assert refreshed.config is not None
    assert refreshed.config.config_json["label_id"] == "INBOX"
    assert refreshed.config.config_json["term_key"] == "WI26"
    assert refreshed.config.config_json["pending_term_rebind"]["requested_config"]["label_id"] == "COURSE"
