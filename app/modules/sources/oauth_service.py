from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.oauth_config import build_frontend_oauth_return_url, build_frontend_sources_return_url, build_oauth_runtime_config
from app.core.security import decrypt_secret, encrypt_secret
from app.db.models.input import IngestTriggerType, InputSource, InputSourceCursor, InputSourceSecret, SyncRequest
from app.modules.common.source_monitoring_window import parse_source_monitoring_window
from app.modules.sources.sync_requests_service import enqueue_sync_request_idempotent
from app.modules.runtime.connectors.clients.gmail_client import GmailClient, GmailOAuthTokens


@dataclass(frozen=True)
class OAuthBrowserCallbackResult:
    provider: str
    status: str
    source_id: int | None = None
    request_id: str | None = None
    message: str | None = None


def build_gmail_oauth_start_for_source(
    db: Session,
    *,
    source: InputSource,
    return_to: str = "sources",
    now: datetime | None = None,
    gmail_client: GmailClient | None = None,
) -> tuple[str, datetime]:
    del db
    current = now or datetime.now(timezone.utc)
    runtime = build_oauth_runtime_config()
    expires_at = current + timedelta(minutes=runtime.state_ttl_minutes)
    state_payload = {
        "source_id": source.id,
        "provider": source.provider,
        "return_to": return_to,
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
) -> tuple[InputSource, SyncRequest | None, str]:
    current = now or datetime.now(timezone.utc)
    state_payload = _parse_oauth_state(state)
    source_id = int(state_payload["source_id"])
    provider = str(state_payload["provider"])
    return_to = str(state_payload.get("return_to") or "sources").strip().lower() or "sources"
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
    previous_payload = _load_existing_gmail_secret_payload(source)
    tokens = client.exchange_code(code=code)
    merged_tokens = _merge_gmail_oauth_tokens(tokens=tokens, previous_payload=previous_payload)
    profile = client.get_profile(access_token=merged_tokens.access_token)

    merged_payload = {
        "access_token": merged_tokens.access_token,
        "refresh_token": merged_tokens.refresh_token,
        "expires_at": merged_tokens.expires_at.isoformat() if merged_tokens.expires_at is not None else None,
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
    source.last_error_code = None
    source.last_error_message = None
    term_window = parse_source_monitoring_window(source, required=False)
    if term_window is None:
        source.cursor.cursor_json = {}
        source.is_active = False
        source.next_poll_at = None
        db.commit()
        db.refresh(source)
        return source, None, return_to

    source.cursor.cursor_json = {"history_id": profile.history_id}
    source.is_active = True
    source.next_poll_at = current
    request = enqueue_sync_request_idempotent(
        db,
        source=source,
        trigger_type=IngestTriggerType.MANUAL,
        idempotency_key=f"oauth:init:{source.id}",
        metadata={"reason": "oauth_callback"},
    )
    return source, request, return_to


def build_oauth_browser_callback_redirect_url(
    *,
    provider: str,
    status: str,
    source_id: int | None = None,
    request_id: str | None = None,
    message: str | None = None,
    destination: str = "sources",
) -> str:
    if destination == "sources":
        return build_frontend_sources_return_url(
            oauth_provider=provider,
            oauth_status=status,
            source_id=source_id,
            request_id=request_id,
            message=message,
        )
    return build_frontend_oauth_return_url(
        oauth_provider=provider,
        oauth_status=status,
        source_id=source_id,
        request_id=request_id,
        message=message,
        destination=destination,
    )


def _parse_oauth_state(state_token: str) -> dict:
    try:
        decoded = decrypt_secret(state_token)
        parsed = json.loads(decoded)
    except Exception as exc:
        raise RuntimeError("Invalid OAuth state") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("Invalid OAuth state payload")
    return parsed


def _load_existing_gmail_secret_payload(source: InputSource) -> dict[str, object]:
    if source.secrets is None or not source.secrets.encrypted_payload:
        return {}
    try:
        decoded = decrypt_secret(source.secrets.encrypted_payload)
        payload = json.loads(decoded)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _merge_gmail_oauth_tokens(
    *,
    tokens: GmailOAuthTokens,
    previous_payload: dict[str, object],
) -> GmailOAuthTokens:
    if tokens.refresh_token:
        return tokens

    existing_refresh_token = previous_payload.get("refresh_token")
    if isinstance(existing_refresh_token, str) and existing_refresh_token.strip():
        return GmailOAuthTokens(
            access_token=tokens.access_token,
            refresh_token=existing_refresh_token.strip(),
            expires_at=tokens.expires_at,
        )
    return tokens


__all__ = [
    "OAuthBrowserCallbackResult",
    "build_gmail_oauth_start_for_source",
    "build_oauth_browser_callback_redirect_url",
    "handle_gmail_oauth_callback",
]
