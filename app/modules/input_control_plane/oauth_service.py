from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.security import decrypt_secret, encrypt_secret
from app.db.models import IngestTriggerType, InputSource, InputSourceCursor, InputSourceSecret, SyncRequest
from app.modules.input_control_plane.sync_requests_service import enqueue_sync_request_idempotent
from app.modules.sync.gmail_client import GmailClient

GMAIL_OAUTH_STATE_TTL_MINUTES = 10


def build_gmail_oauth_start_for_source(
    db: Session,
    *,
    source: InputSource,
    now: datetime | None = None,
    gmail_client: GmailClient | None = None,
) -> tuple[str, datetime]:
    del db
    current = now or datetime.now(timezone.utc)
    expires_at = current + timedelta(minutes=GMAIL_OAUTH_STATE_TTL_MINUTES)
    state_payload = {
        "source_id": source.id,
        "provider": source.provider,
        "exp": expires_at.isoformat(),
    }
    state_token = encrypt_secret(json.dumps(state_payload, separators=(",", ":"), ensure_ascii=True))
    client = gmail_client or GmailClient()
    return client.build_authorization_url(state=state_token), expires_at


def handle_gmail_oauth_callback(
    db: Session,
    *,
    code: str,
    state: str,
    now: datetime | None = None,
    gmail_client: GmailClient | None = None,
) -> tuple[InputSource, SyncRequest]:
    current = now or datetime.now(timezone.utc)
    state_payload = _parse_oauth_state(state)
    source_id = int(state_payload["source_id"])
    provider = str(state_payload["provider"])
    if provider != "gmail":
        raise RuntimeError("Unsupported oauth provider in state payload")
    expires_raw = state_payload.get("exp")
    if not isinstance(expires_raw, str):
        raise RuntimeError("OAuth state missing expiration")
    expires_at = datetime.fromisoformat(expires_raw)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    else:
        expires_at = expires_at.astimezone(timezone.utc)
    if current > expires_at:
        raise RuntimeError("OAuth state expired")

    source = db.get(InputSource, source_id)
    if source is None or source.provider != "gmail":
        raise RuntimeError("Input source not found for oauth callback")

    client = gmail_client or GmailClient()
    tokens = client.exchange_code(code=code)
    profile = client.get_profile(access_token=tokens.access_token)

    merged_payload = {
        "access_token": tokens.access_token,
        "refresh_token": tokens.refresh_token,
        "expires_at": tokens.expires_at.isoformat() if tokens.expires_at is not None else None,
        "account_email": profile.email_address,
        "history_id": profile.history_id,
    }
    encrypted_payload = encrypt_secret(json.dumps(merged_payload, separators=(",", ":"), ensure_ascii=True))
    if source.secrets is None:
        source.secrets = InputSourceSecret(source_id=source.id, encrypted_payload=encrypted_payload)
    else:
        source.secrets.encrypted_payload = encrypted_payload

    if source.cursor is None:
        source.cursor = InputSourceCursor(source_id=source.id, version=1, cursor_json={})
    source.cursor.cursor_json = {"history_id": profile.history_id}

    request = enqueue_sync_request_idempotent(
        db,
        source=source,
        trigger_type=IngestTriggerType.MANUAL,
        idempotency_key=f"oauth:init:{source.id}",
        metadata={"reason": "oauth_callback"},
    )
    return source, request


def _parse_oauth_state(state_token: str) -> dict:
    try:
        decoded = decrypt_secret(state_token)
        parsed = json.loads(decoded)
    except Exception as exc:
        raise RuntimeError("Invalid OAuth state") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("Invalid OAuth state payload")
    return parsed


__all__ = [
    "build_gmail_oauth_start_for_source",
    "handle_gmail_oauth_callback",
]
